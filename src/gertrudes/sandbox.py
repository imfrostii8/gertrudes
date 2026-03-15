"""Path traversal protection for repository operations."""

from __future__ import annotations

from pathlib import Path


def safe_resolve(repo_path: Path, relative_path: str) -> Path:
    """Resolve a relative path within repo_path, raising ValueError if it escapes.

    Args:
        repo_path: The repository root path.
        relative_path: A path relative to the repo root.

    Returns:
        Resolved absolute Path within the repo.

    Raises:
        ValueError: If the resolved path escapes the repo root.
    """
    resolved = (repo_path / relative_path).resolve()
    repo_resolved = repo_path.resolve()
    if not resolved.is_relative_to(repo_resolved):
        raise ValueError(
            f"Path '{relative_path}' escapes the repository root '{repo_path}'"
        )
    return resolved
