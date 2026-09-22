"""Repository boundary checks shared by DataLoom runtime adapters."""

from __future__ import annotations

from pathlib import Path


class WorkspaceViolation(ValueError):
    """Raised when a requested path escapes its declared workspace."""


class WorkspaceGuard:
    """Resolve paths without allowing absolute paths or parent traversal.

    Symlinks are resolved before the boundary check, so a repository symlink
    cannot be used to read a host file outside the frozen checkout.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise WorkspaceViolation(f"workspace root is not a directory: {root}")

    def resolve(self, relative_path: str | Path, *, must_exist: bool = True) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise WorkspaceViolation(f"path escapes workspace: {relative_path}")
        candidate = (self.root / relative).resolve(strict=must_exist)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceViolation(f"path escapes workspace: {relative_path}") from exc
        return candidate

    def file(self, relative_path: str | Path) -> Path:
        candidate = self.resolve(relative_path)
        if not candidate.is_file():
            raise WorkspaceViolation(f"path is not a workspace file: {relative_path}")
        return candidate

    def relative(self, path: Path) -> str:
        resolved = path.resolve(strict=True)
        try:
            return resolved.relative_to(self.root).as_posix()
        except ValueError as exc:
            raise WorkspaceViolation(f"path escapes workspace: {path}") from exc

