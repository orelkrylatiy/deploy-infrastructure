from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECTS_ROOT = Path("/var/www/projects")
CONFIG_ROOT = Path("/etc/deploy-manager/projects")
INCOMING_ROOT = Path("/var/lib/deploy-manager/incoming")
LOG_ROOT = Path("/var/log/deploy-manager")
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,46}[a-z0-9])?$")
RELEASE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
UNIT_RE = re.compile(r"^[A-Za-z0-9_.@:-]+\.service$")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    app_type: str
    delivery: str
    root: Path
    keep_releases: int
    healthcheck_url: str | None
    build_commands: tuple[tuple[str, ...], ...]
    build_output: str
    build_timeout: int
    shared_files: tuple[str, ...]
    shared_dirs: tuple[str, ...]
    service_unit: str | None


def validate_slug(value: str) -> str:
    if not isinstance(value, str) or not SLUG_RE.fullmatch(value):
        raise ConfigError("Project name must be a lowercase slug (letters, numbers, hyphens).")
    return value


def validate_release_id(value: str) -> str:
    if not isinstance(value, str) or not RELEASE_RE.fullmatch(value) or value in {".", ".."}:
        raise ConfigError("Invalid release ID.")
    return value


def _relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or chr(92) in value:
        raise ConfigError(f"{label} must be a non-empty relative POSIX path.")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ConfigError(f"{label} must not be absolute or contain '.'/'..' segments.")
    return value


def _commands(value: Any) -> tuple[tuple[str, ...], ...]:
    if not isinstance(value, list):
        raise ConfigError("project.build_commands must be an array of command arrays.")
    result: list[tuple[str, ...]] = []
    for command in value:
        if not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command):
            raise ConfigError("Each build command must be a non-empty array of strings.")
        result.append(tuple(command))
    return tuple(result)


def load_config(name: str) -> ProjectConfig:
    validate_slug(name)
    path = CONFIG_ROOT / f"{name}.toml"
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {path}: {exc}") from exc

    project = data.get("project")
    if not isinstance(project, dict):
        raise ConfigError("Configuration must contain a [project] table.")

    app_type = project.get("type")
    delivery = project.get("delivery")
    if app_type not in {"static", "service"}:
        raise ConfigError("project.type must be 'static' or 'service'.")
    if delivery not in {"artifact", "source"}:
        raise ConfigError("project.delivery must be 'artifact' or 'source'.")

    keep = project.get("keep_releases", 10)
    timeout = project.get("build_timeout_seconds", 1800)
    if not isinstance(keep, int) or not 2 <= keep <= 100:
        raise ConfigError("project.keep_releases must be an integer between 2 and 100.")
    if not isinstance(timeout, int) or not 30 <= timeout <= 7200:
        raise ConfigError("project.build_timeout_seconds must be between 30 and 7200.")

    healthcheck = project.get("healthcheck_url")
    if healthcheck is not None:
        if not isinstance(healthcheck, str) or not healthcheck.startswith(("http://", "https://")):
            raise ConfigError("project.healthcheck_url must be an http(s) URL.")

    commands = _commands(project.get("build_commands", []))
    build_output = _relative_path(project.get("build_output", "dist"), "project.build_output")
    if delivery == "source" and app_type == "static":
        if not commands:
            raise ConfigError("Static + source requires project.build_commands.")
        if not project.get("build_output"):
            raise ConfigError("Static + source requires project.build_output.")

    shared_files_raw = project.get("shared_files", [])
    shared_dirs_raw = project.get("shared_dirs", [])
    if not isinstance(shared_files_raw, list) or not isinstance(shared_dirs_raw, list):
        raise ConfigError("shared_files and shared_dirs must be arrays.")
    shared_files = tuple(_relative_path(x, "shared_files entry") for x in shared_files_raw)
    shared_dirs = tuple(_relative_path(x, "shared_dirs entry") for x in shared_dirs_raw)
    if app_type == "static" and shared_files:
        raise ConfigError("Static sites cannot use shared_files; files under the web root may be publicly served.")
    all_shared = list(shared_files) + list(shared_dirs)
    if set(shared_files) & set(shared_dirs):
        raise ConfigError("A path cannot be both a shared file and a shared directory.")
    for item in all_shared:
        if any(other.startswith(item + "/") for other in all_shared if other != item):
            raise ConfigError("Shared paths must not overlap.")

    service_unit = None
    if app_type == "service":
        service = data.get("service", {})
        service_unit = service.get("unit") if isinstance(service, dict) else None
        if not isinstance(service_unit, str) or not UNIT_RE.fullmatch(service_unit):
            raise ConfigError("Service projects require [service] unit = 'name.service'.")

    return ProjectConfig(
        name=name,
        app_type=app_type,
        delivery=delivery,
        root=PROJECTS_ROOT / name,
        keep_releases=keep,
        healthcheck_url=healthcheck,
        build_commands=commands,
        build_output=build_output,
        build_timeout=timeout,
        shared_files=shared_files,
        shared_dirs=shared_dirs,
        service_unit=service_unit,
    )
