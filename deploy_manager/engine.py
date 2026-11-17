from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import INCOMING_ROOT, ProjectConfig, validate_release_id
from .filesystem import (
    atomic_symlink, copy_tree, current_release, ensure_project_layout, incoming_path,
    normalize_permissions, safe_remove, validate_tree,
)
from .locking import project_lock

METADATA_DIR = ".deploy/metadata"


class DeployError(RuntimeError):
    pass


def _metadata_path(root: Path, release_id: str) -> Path:
    validate_release_id(release_id)
    return root / METADATA_DIR / f"{release_id}.json"


def _write_metadata(root: Path, release_id: str, data: dict[str, Any]) -> None:
    path = _metadata_path(root, release_id)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_metadata(root: Path, release_id: str) -> dict[str, Any] | None:
    try:
        return json.loads(_metadata_path(root, release_id).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _run_build(config: ProjectConfig, workspace: Path, release_id: str, logger) -> None:
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/home/deploy"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "CI": "true",
        "DEPLOY_PROJECT": config.name,
        "DEPLOY_RELEASE_ID": release_id,
    }
    for command in config.build_commands:
        logger.info("Running build command: %s", " ".join(command))
        try:
            subprocess.run(
                list(command), cwd=workspace, env=env, check=True,
                timeout=config.build_timeout, text=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise DeployError(f"Build command timed out after {config.build_timeout}s: {command[0]}") from exc
        except subprocess.CalledProcessError as exc:
            raise DeployError(f"Build command failed with exit code {exc.returncode}: {command[0]}") from exc
        except FileNotFoundError as exc:
            raise DeployError(f"Build executable not found: {command[0]}") from exc


def _apply_shared(config: ProjectConfig, payload: Path, absolute_links: bool = False) -> None:
    shared_root = config.root / "shared"
    for relative in config.shared_files + config.shared_dirs:
        source = payload / relative
        shared = shared_root / relative
        for candidate in (source.parent, shared.parent):
            parent = candidate
            while parent != payload and parent != shared_root and parent != parent.parent:
                if parent.is_symlink():
                    raise DeployError(f"Shared path parent must not be a symlink: {parent}")
                parent = parent.parent
        shared.parent.mkdir(parents=True, exist_ok=True)
        if shared.is_symlink():
            raise DeployError(f"Shared path must not be a symlink: {shared}")
        if source.exists() or source.is_symlink():
            if not shared.exists():
                if source.is_symlink():
                    raise DeployError(f"Cannot initialize shared data from symlink: {source}")
                shutil.move(str(source), str(shared))
            elif source.is_dir() and not source.is_symlink():
                shutil.rmtree(source)
            else:
                source.unlink()
        if relative in config.shared_files:
            if not shared.exists():
                shared.touch(mode=0o600)
            if not shared.is_file():
                raise DeployError(f"Configured shared file is not a file: {shared}")
            shared.chmod(0o600)
        else:
            if not shared.exists():
                shared.mkdir(parents=True, mode=0o755)
            if not shared.is_dir():
                raise DeployError(f"Configured shared directory is not a directory: {shared}")
        source.parent.mkdir(parents=True, exist_ok=True)
        link_target = str(shared) if absolute_links else os.path.relpath(shared, source.parent)
        source.symlink_to(link_target)


def _systemctl(config: ProjectConfig, action: str, logger) -> None:
    if not config.service_unit:
        return
    systemctl = shutil.which("systemctl")
    if not systemctl:
        raise DeployError("systemctl was not found; service deployment requires systemd.")
    command = [systemctl, action, config.service_unit]
    if os.geteuid() != 0:
        sudo = shutil.which("sudo")
        if not sudo:
            raise DeployError("sudo is required to manage systemd services as a non-root user.")
        command = [sudo, "-n", *command]
    logger.info("Running: %s", " ".join(command))
    try:
        subprocess.run(command, check=True, timeout=60, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise DeployError(f"systemctl {action} failed for {config.service_unit}: {detail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise DeployError(f"systemctl {action} timed out for {config.service_unit}.") from exc
    except FileNotFoundError as exc:
        raise DeployError(f"Required executable not found: {command[0]}") from exc


def _healthcheck(config: ProjectConfig, release_path: Path, logger) -> None:
    if config.app_type == "static" and not (release_path / "index.html").is_file():
        raise DeployError("Static release does not contain index.html at its root.")
    if config.app_type == "service":
        _systemctl(config, "is-active", logger)
    if not config.healthcheck_url:
        logger.info("No HTTP healthcheck URL configured; local checks passed.")
        return
    request = urllib.request.Request(
        config.healthcheck_url, headers={"User-Agent": "deploy-manager/0.1"}
    )
    last_error = "unknown error"
    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                if 200 <= response.status < 400:
                    logger.info("HTTP healthcheck passed: %s (%s)", config.healthcheck_url, response.status)
                    return
                last_error = f"HTTP {response.status}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
        if attempt < 5:
            time.sleep(2)
    raise DeployError(f"HTTP healthcheck failed for {config.healthcheck_url}: {last_error}")


def _restore_previous(config: ProjectConfig, previous: str | None, logger) -> None:
    if previous:
        atomic_symlink(config.root, previous)
        if config.app_type == "service":
            _systemctl(config, "restart", logger)
    else:
        current = config.root / "current"
        if current.is_symlink():
            current.unlink()
        if config.app_type == "service":
            _systemctl(config, "stop", logger)


def _prepare_payload(config: ProjectConfig, release_id: str, staging: Path, logger) -> Path:
    kind = "payload" if config.delivery == "artifact" else "source"
    source = incoming_path(config.name, release_id, kind)
    if not source.is_dir():
        raise DeployError(f"Incoming {kind} directory not found: {source}")
    workspace = staging / "workspace"
    payload = staging / "payload"

    if config.delivery == "artifact":
        copy_tree(source, payload, allow_internal_symlinks=(config.app_type == "service"))
        if config.app_type == "static" and not (payload / "index.html").is_file():
            raise DeployError("Static artifact must contain index.html at its root.")
        return payload

    copy_tree(source, workspace, allow_internal_symlinks=False)
    _apply_shared(config, workspace, absolute_links=True)
    _run_build(config, workspace, release_id, logger)
    if config.app_type == "static":
        build_path = (workspace / config.build_output).resolve()
        if build_path != workspace.resolve() and workspace.resolve() not in build_path.parents:
            raise DeployError("Configured build_output escapes the source workspace.")
        if not build_path.is_dir():
            raise DeployError(f"Build output directory not found: {build_path}")
        copy_tree(build_path, payload, allow_internal_symlinks=False)
        if not (payload / "index.html").is_file():
            raise DeployError("Static build output must contain index.html at its root.")
        return payload

    validate_tree(workspace, allow_internal_symlinks=True)
    workspace.rename(payload)
    normalize_permissions(payload)
    return payload


def _cleanup(config: ProjectConfig, logger) -> None:
    root = config.root
    current = current_release(root)
    metadata_dir = root / METADATA_DIR
    successful: list[tuple[str, str]] = []
    for file in metadata_dir.glob("*.json"):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("status") == "success":
            successful.append((str(data.get("deployed_at", "")), file.stem))
    successful.sort(reverse=True)
    keep = {release_id for _, release_id in successful[:config.keep_releases]}
    if current:
        keep.add(current)
    releases_dir = root / "releases"
    for path in releases_dir.iterdir():
        if not path.is_dir() or path.is_symlink() or path.name.startswith(".staging-"):
            continue
        if path.name not in keep:
            safe_remove(path, releases_dir)
            metadata = _metadata_path(root, path.name)
            if metadata.exists():
                metadata.unlink()
            logger.info("Removed old release: %s", path.name)


def init_project(config: ProjectConfig) -> None:
    ensure_project_layout(config)


def deploy(config: ProjectConfig, release_id: str, logger) -> None:
    validate_release_id(release_id)
    ensure_project_layout(config)
    with project_lock(config.root):
        releases = config.root / "releases"
        final_release = releases / release_id
        if final_release.exists() or final_release.is_symlink():
            raise DeployError(f"Release already exists: {release_id}")
        staging = releases / f".staging-{release_id}-{uuid.uuid4().hex}"
        previous = current_release(config.root)
        started = datetime.now(timezone.utc).isoformat()
        logger.info("Starting %s/%s (%s + %s)", config.name, release_id, config.app_type, config.delivery)
        staging.mkdir(mode=0o755)
        switched = False
        try:
            payload = _prepare_payload(config, release_id, staging, logger)
            os.replace(payload, final_release)
            _apply_shared(config, final_release)
            normalize_permissions(final_release)
            _write_metadata(config.root, release_id, {
                "release_id": release_id, "status": "pending", "started_at": started,
                "app_type": config.app_type, "delivery": config.delivery,
            })
            atomic_symlink(config.root, release_id)
            switched = True
            if config.app_type == "service":
                _systemctl(config, "restart", logger)
            _healthcheck(config, final_release, logger)
            _write_metadata(config.root, release_id, {
                "release_id": release_id, "status": "success", "started_at": started,
                "deployed_at": datetime.now(timezone.utc).isoformat(),
                "app_type": config.app_type, "delivery": config.delivery,
            })
            logger.info("Deployment succeeded: %s", release_id)
            try:
                _cleanup(config, logger)
            except Exception:
                logger.exception("Release cleanup failed after successful deployment; active release remains live.")
            incoming_release = INCOMING_ROOT / config.name / release_id
            if incoming_release.exists() and not incoming_release.is_symlink():
                try:
                    shutil.rmtree(incoming_release)
                except OSError:
                    logger.exception("Could not remove completed incoming upload: %s", incoming_release)
        except Exception as exc:
            logger.exception("Deployment failed: %s", exc)
            try:
                if switched:
                    _restore_previous(config, previous, logger)
                if final_release.exists():
                    _write_metadata(config.root, release_id, {
                        "release_id": release_id, "status": "failed", "started_at": started,
                        "failed_at": datetime.now(timezone.utc).isoformat(),
                        "error": str(exc)[:1000], "app_type": config.app_type, "delivery": config.delivery,
                    })
            except Exception as rollback_exc:
                logger.exception("Rollback also failed: %s", rollback_exc)
                raise DeployError(
                    f"Deployment failed ({exc}); automatic rollback also failed ({rollback_exc})."
                ) from exc
            raise DeployError(str(exc)) from exc
        finally:
            if staging.exists() and not staging.is_symlink():
                shutil.rmtree(staging, ignore_errors=True)


def rollback(config: ProjectConfig, logger) -> str:
    ensure_project_layout(config)
    with project_lock(config.root):
        previous_current = current_release(config.root)
        candidates: list[tuple[str, str]] = []
        for file in (config.root / METADATA_DIR).glob("*.json"):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("status") == "success" and file.stem != previous_current:
                release = config.root / "releases" / file.stem
                if release.is_dir() and not release.is_symlink():
                    candidates.append((str(data.get("deployed_at", "")), file.stem))
        if not candidates:
            raise DeployError("No previous successful release is available for rollback.")
        candidates.sort(reverse=True)
        target = candidates[0][1]
        logger.info("Rolling back %s from %s to %s", config.name, previous_current, target)
        atomic_symlink(config.root, target)
        try:
            if config.app_type == "service":
                _systemctl(config, "restart", logger)
            _healthcheck(config, config.root / "releases" / target, logger)
        except Exception as exc:
            logger.exception("Rollback target failed healthcheck: %s", exc)
            _restore_previous(config, previous_current, logger)
            raise DeployError(
                f"Rollback to {target} failed; restored {previous_current or 'no current release'}."
            ) from exc
        logger.info("Rollback succeeded: %s", target)
        return target


def status(config: ProjectConfig) -> dict[str, Any]:
    current = current_release(config.root) if config.root.exists() else None
    result: dict[str, Any] = {
        "project": config.name, "type": config.app_type,
        "delivery": config.delivery, "current": current,
    }
    if config.app_type == "service" and config.service_unit:
        systemctl = shutil.which("systemctl")
        if systemctl:
            command = [systemctl, "is-active", config.service_unit]
            if os.geteuid() != 0 and shutil.which("sudo"):
                command = [shutil.which("sudo"), "-n", *command]
            proc = subprocess.run(command, capture_output=True, text=True, timeout=15)
            result["service"] = proc.stdout.strip() or proc.stderr.strip() or "unknown"
    return result


def list_releases(config: ProjectConfig) -> list[dict[str, Any]]:
    result = []
    metadata_dir = config.root / METADATA_DIR
    if not metadata_dir.exists():
        return result
    current = current_release(config.root)
    for file in metadata_dir.glob("*.json"):
        try:
            item = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        item["current"] = file.stem == current
        result.append(item)
    return sorted(result, key=lambda item: item.get("deployed_at", item.get("started_at", "")), reverse=True)


def read_logs(project: str, lines: int = 100) -> str:
    path = Path("/var/log/deploy-manager") / f"{project}.log"
    if not path.exists():
        return f"No log file yet: {path}"
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])
