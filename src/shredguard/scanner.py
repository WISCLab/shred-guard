"""Core scanning logic for ShredGuard."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

from .config import Pattern

# Number of bytes to check for binary detection
BINARY_CHECK_SIZE = 8192


@dataclass
class Match:
    """A single pattern match in a file."""

    file: Path
    line: int  # 1-indexed
    column: int  # 1-indexed
    matched_text: str
    pattern: Pattern

    @property
    def location(self) -> str:
        """Format as file:line:col string."""
        return f"{self.file}:{self.line}:{self.column}"


def is_binary_file(path: Path) -> bool:
    """Check if a file is binary using null byte heuristic.

    Args:
        path: Path to the file to check.

    Returns:
        True if the file appears to be binary.
    """
    try:
        with open(path, "rb") as f:
            chunk = f.read(BINARY_CHECK_SIZE)
            return b"\x00" in chunk
    except OSError:
        return True  # Treat unreadable files as binary


def file_matches_globs(
    path: Path, include_globs: list[str], exclude_globs: list[str]
) -> bool:
    """Check if a file matches the include/exclude glob patterns.

    Args:
        path: Path to check.
        include_globs: Glob patterns to include (empty = include all).
        exclude_globs: Glob patterns to exclude.

    Returns:
        True if the file should be scanned for this pattern.
    """
    # Convert to string for fnmatch
    path_str = str(path)
    name = path.name

    # Check exclude patterns first
    for glob in exclude_globs:
        if fnmatch.fnmatch(name, glob) or fnmatch.fnmatch(path_str, glob):
            return False

    # If no include patterns, include all
    if not include_globs:
        return True

    # Check include patterns
    for glob in include_globs:
        if fnmatch.fnmatch(name, glob) or fnmatch.fnmatch(path_str, glob):
            return True

    return False


def scan_file(path: Path, patterns: list[Pattern]) -> tuple[list[Match], bool]:
    """Scan a single file for pattern matches.

    Args:
        path: Path to the file to scan.
        patterns: List of patterns to scan for.

    Returns:
        Tuple of (list of matches, was_binary). If was_binary is True,
        the file was skipped and matches will be empty.
    """
    if is_binary_file(path):
        return [], True

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return [], True  # Treat unreadable as binary

    # Normalize line endings for consistent processing
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    matches: list[Match] = []

    # Filter patterns by file globs
    applicable_patterns = [
        p
        for p in patterns
        if file_matches_globs(path, p.files, p.exclude_files)
    ]

    for pattern in applicable_patterns:
        for match in pattern.compiled.finditer(content):
            # Calculate line and column
            start = match.start()
            line_start = content.rfind("\n", 0, start) + 1
            line_num = content.count("\n", 0, start) + 1
            col_num = start - line_start + 1

            matches.append(
                Match(
                    file=path,
                    line=line_num,
                    column=col_num,
                    matched_text=match.group(),
                    pattern=pattern,
                )
            )

    return matches, False


def scan_files(
    files: list[Path], patterns: list[Pattern], verbose: bool = False
) -> tuple[list[Match], list[Path]]:
    """Scan multiple files for pattern matches.

    Args:
        files: List of files to scan.
        patterns: List of patterns to scan for.
        verbose: If True, track skipped binary files.

    Returns:
        Tuple of (all matches, list of skipped binary files).
    """
    all_matches: list[Match] = []
    binary_files: list[Path] = []

    for file_path in files:
        matches, was_binary = scan_file(file_path, patterns)
        if was_binary:
            binary_files.append(file_path)
        else:
            all_matches.extend(matches)

    # Sort matches by file, then line, then column
    all_matches.sort(key=lambda m: (str(m.file), m.line, m.column))

    return all_matches, binary_files
