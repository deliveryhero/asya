"""Discovery utilities for .asya/ project directories and git roots."""

from __future__ import annotations

from pathlib import Path


def find_git_root(start_dir: Path) -> Path | None:
    """Walk up from start_dir to find the nearest .git/ directory.

    Returns the directory containing .git/, or None if not found.
    """
    current = start_dir.resolve()
    while True:
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def find_asya_dir(start_dir: Path) -> Path | None:
    """Walk up from start_dir to find the nearest .asya/ directory.

    Returns the .asya/ directory path, or None if not found.
    Stops at git root (inclusive) or filesystem root.
    """
    current = start_dir.resolve()
    git_root = find_git_root(current)

    while True:
        asya_dir = current / ".asya"
        if asya_dir.is_dir():
            return asya_dir
        if git_root and current == git_root:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def collect_asya_dirs(start_dir: Path) -> list[Path]:
    """Collect all .asya/ directories from git root down to start_dir.

    Returns directories root-first (outermost first, most local last).
    """
    current = start_dir.resolve()
    git_root = find_git_root(current)
    if git_root is None:
        asya_dir = current / ".asya"
        return [asya_dir] if asya_dir.is_dir() else []

    dirs: list[Path] = []

    while True:
        asya_dir = current / ".asya"
        if asya_dir.is_dir():
            dirs.append(asya_dir)
        if current == git_root:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    dirs.reverse()
    return dirs
