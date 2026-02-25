"""Gitignore pattern handling for ShredGuard."""

from __future__ import annotations

from pathlib import Path

import pathspec


def find_gitignore_files(root: Path) -> list[Path]:
    """Find all .gitignore files in a directory tree.

    Args:
        root: Root directory to search from.

    Returns:
        List of .gitignore file paths, ordered from root to deepest.
    """
    gitignores = []

    # First check parents for .gitignore files (for when running in subdirectory)
    current = root.resolve()
    parent_gitignores = []
    while current != current.parent:
        gitignore = current / ".gitignore"
        if gitignore.exists():
            parent_gitignores.append(gitignore)
        current = current.parent

    # Reverse so root-level comes first
    gitignores.extend(reversed(parent_gitignores))

    # Then find .gitignore files within the root directory
    if root.is_dir():
        for gitignore in sorted(root.rglob(".gitignore")):
            if gitignore not in gitignores:
                gitignores.append(gitignore)

    return gitignores


def load_gitignore_spec(gitignore_path: Path) -> pathspec.PathSpec:
    """Load a .gitignore file into a PathSpec.

    Args:
        gitignore_path: Path to .gitignore file.

    Returns:
        PathSpec for matching against the patterns.
    """
    with open(gitignore_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    return pathspec.PathSpec.from_lines("gitignore", lines)


class GitignoreFilter:
    """Filter files based on .gitignore patterns."""

    def __init__(self, root: Path, respect_gitignore: bool = True):
        """Initialize the filter.

        Args:
            root: Root directory for relative path calculations.
            respect_gitignore: Whether to actually filter files.
        """
        self.root = root.resolve()
        self.respect_gitignore = respect_gitignore
        self._specs: list[tuple[Path, pathspec.PathSpec]] = []

        if respect_gitignore:
            self._load_gitignores()

    def _load_gitignores(self) -> None:
        """Load all .gitignore files."""
        for gitignore_path in find_gitignore_files(self.root):
            try:
                spec = load_gitignore_spec(gitignore_path)
                # Store the directory containing the .gitignore
                self._specs.append((gitignore_path.parent.resolve(), spec))
            except OSError:
                # Skip unreadable .gitignore files
                pass

    def is_ignored(self, path: Path) -> bool:
        """Check if a path should be ignored.

        Args:
            path: Path to check (can be absolute or relative).

        Returns:
            True if the path matches any .gitignore pattern.
        """
        if not self.respect_gitignore:
            return False

        path = path.resolve()

        for gitignore_dir, spec in self._specs:
            # Calculate path relative to the .gitignore's directory
            try:
                rel_path = path.relative_to(gitignore_dir)
                rel_str = str(rel_path)

                # pathspec expects forward slashes
                rel_str = rel_str.replace("\\", "/")

                if spec.match_file(rel_str):
                    return True

                # Also check with trailing slash for directories
                if path.is_dir() and spec.match_file(rel_str + "/"):
                    return True

            except ValueError:
                # Path is not relative to this .gitignore's directory
                continue

        return False

    def filter_paths(self, paths: list[Path]) -> list[Path]:
        """Filter a list of paths, removing ignored ones.

        Args:
            paths: List of paths to filter.

        Returns:
            List of paths that are not ignored.
        """
        if not self.respect_gitignore:
            return paths

        return [p for p in paths if not self.is_ignored(p)]
