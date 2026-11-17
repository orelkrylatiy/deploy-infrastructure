from __future__ import annotations

import os
import shutil
import stat
import uuid
from pathlib import Path

from .config import INCOMING_ROOT, PROJECTS_ROOT, ProjectConfig, validate_release_id


class FilesystemError(RuntimeError):
    pass


def ensure_project_layout(config: ProjectConfig) -> None:
    base = PROJECTS_ROOT
    if base.is_symlink():
        raise FilesystemError(f"Projects root must not be a symlink: {base}")
    base.mkdir(parents=True, exist_ok=True)
    root = config.root
    if root.is_symlink():
        raise FilesystemError(f"Project root must not be a symlink: {root}")
    if root.exists() and not root.is_dir():
        raise FilesystemError(f"Project root is not a directory: {root}")
    root.mkdir(mode=0o755, parents=True, exist_ok=True)
    for directory in (root / "releases", root / "shared", root / ".deploy", root / ".deploy" / "metadata"):
        if directory.is_symlink():
            raise FilesystemError(f"Managed directory must not be a symlink: {directory}")
        directory.mkdir(mode=0o755, parents=True, exist_ok=True)


def incoming_path(project: str, release_id: str, kind: str) -> Path:
    validate_release_id(release_id)
    if kind not in {"payload", "source"}:
        raise FilesystemError("Invalid incoming directory kind.")
    base = INCOMING_ROOT
    if base.is_symlink():
        raise FilesystemError(f"Incoming root must not be a symlink: {base}")
    path = base / project / release_id / kind
    current = base
    for part in (project, release_id, kind):
        current = current / part
        if current.is_symlink():
            raise FilesystemError(f"Incoming path contains a symlink: {current}")
    resolved_base = base.resolve()
    resolved = path.resolve()
    if resolved != resolved_base and resolved_base not in resolved.parents:
        raise FilesystemError("Incoming path escapes the incoming root.")
    return path


def validate_tree(source: Path, allow_internal_symlinks: bool = False) -> None:
    if source.is_symlink() or not source.is_dir():
        raise FilesystemError(f"Input must be a real directory: {source}")
    root = source.resolve()
    for current, dirs, files in os.walk(source, followlinks=False):
        current_path = Path(current)
        for name in list(dirs) + files:
            item = current_path / name
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode):
                if not allow_internal_symlinks:
                    raise FilesystemError(f"Symlinks are not allowed in this input: {item}")
                if Path(os.readlink(item)).is_absolute():
                    raise FilesystemError(f"Absolute symlinks are not allowed in this input: {item}")
                target = item.resolve()
                if target != root and root not in target.parents:
                    raise FilesystemError(f"Symlink escapes the input directory: {item}")
            elif not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise FilesystemError(f"Unsupported special file in input: {item}")


def copy_tree(source: Path, destination: Path, allow_internal_symlinks: bool = False) -> None:
    validate_tree(source, allow_internal_symlinks=allow_internal_symlinks)
    if destination.exists():
        raise FilesystemError(f"Destination already exists: {destination}")
    shutil.copytree(source, destination, symlinks=allow_internal_symlinks)
    normalize_permissions(destination)


def normalize_permissions(root: Path) -> None:
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        try:
            current_path.chmod(0o755)
        except OSError:
            pass
        for name in dirs:
            path = current_path / name
            if not path.is_symlink():
                path.chmod(0o755)
        for name in files:
            path = current_path / name
            if path.is_symlink():
                continue
            mode = path.stat().st_mode
            path.chmod(0o755 if mode & stat.S_IXUSR else 0o644)


def atomic_symlink(root: Path, release_id: str) -> None:
    validate_release_id(release_id)
    releases = root / "releases"
    target = releases / release_id
    if not target.is_dir() or target.is_symlink():
        raise FilesystemError(f"Release does not exist or is unsafe: {target}")
    current = root / "current"
    if current.exists() and not current.is_symlink():
        raise FilesystemError(f"Refusing to replace non-symlink current path: {current}")
    temporary = root / f".current-{uuid.uuid4().hex}"
    try:
        temporary.symlink_to(Path("releases") / release_id)
        os.replace(temporary, current)
    finally:
        if temporary.is_symlink():
            temporary.unlink()


def current_release(root: Path) -> str | None:
    current = root / "current"
    if not current.is_symlink():
        if current.exists():
            raise FilesystemError(f"Current path exists but is not a symlink: {current}")
        return None
    target = Path(os.readlink(current))
    if target.is_absolute() or len(target.parts) != 2 or target.parts[0] != "releases":
        raise FilesystemError(f"Unexpected current symlink target: {target}")
    release_id = validate_release_id(target.parts[1])
    release = root / "releases" / release_id
    if not release.is_dir() or release.is_symlink():
        raise FilesystemError(f"Current release is missing or unsafe: {release}")
    return release_id


def safe_remove(path: Path, expected_parent: Path) -> None:
    if path.is_symlink() or path.parent.resolve() != expected_parent.resolve():
        raise FilesystemError(f"Refusing unsafe removal: {path}")
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()
