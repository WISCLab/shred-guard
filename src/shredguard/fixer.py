"""Replacement logic for ShredGuard."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .scanner import Match


class PrefixCollisionError(Exception):
    """Raised when the prefix already exists in files."""

    def __init__(self, prefix: str, collisions: list[tuple[Path, int, str]]):
        self.prefix = prefix
        self.collisions = collisions
        super().__init__(f"Prefix '{prefix}' already exists in {len(collisions)} location(s)")


@dataclass
class FixResult:
    """Result of a fix operation."""

    files_modified: int
    total_replacements: int
    unique_values: int
    mapping: dict[str, str]  # original -> pseudonym


@dataclass
class Fixer:
    """Handles deterministic pseudonym replacement."""

    prefix: str
    _mapping: dict[str, str] = field(default_factory=dict, init=False)
    _next_id: int = field(default=0, init=False)

    def get_pseudonym(self, original: str) -> str:
        """Get or create a pseudonym for a value.

        The same original value always gets the same pseudonym.

        Args:
            original: The original matched text.

        Returns:
            The pseudonym (e.g., "REDACTED-0").
        """
        if original not in self._mapping:
            self._mapping[original] = f"{self.prefix}-{self._next_id}"
            self._next_id += 1
        return self._mapping[original]

    @property
    def mapping(self) -> dict[str, str]:
        """Get the current mapping of originals to pseudonyms."""
        return dict(self._mapping)


def check_prefix_collisions(
    files: list[Path], prefix: str
) -> list[tuple[Path, int, str]]:
    """Check for existing occurrences of the prefix pattern in files.

    Args:
        files: List of files to check.
        prefix: The prefix to check for.

    Returns:
        List of (file, line_number, matched_text) tuples for collisions.
    """
    # Escape prefix for regex and look for PREFIX-digits pattern
    pattern = re.compile(re.escape(prefix) + r"-\d+")
    collisions: list[tuple[Path, int, str]] = []

    for file_path in files:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                for line_num, line in enumerate(f, 1):
                    for match in pattern.finditer(line):
                        collisions.append((file_path, line_num, match.group()))
        except OSError:
            continue

    return collisions


def apply_fixes(
    matches: list[Match], prefix: str, output_map: Path | None = None
) -> FixResult:
    """Apply fixes to all matched files.

    Args:
        matches: List of matches to fix.
        prefix: Prefix for pseudonyms.
        output_map: Optional path to write JSON mapping.

    Returns:
        FixResult with statistics.

    Raises:
        PrefixCollisionError: If prefix already exists in files.
    """
    if not matches:
        return FixResult(
            files_modified=0,
            total_replacements=0,
            unique_values=0,
            mapping={},
        )

    # Get unique files
    files = list({m.file for m in matches})

    # Check for prefix collisions first
    collisions = check_prefix_collisions(files, prefix)
    if collisions:
        raise PrefixCollisionError(prefix, collisions)

    fixer = Fixer(prefix=prefix)

    # Group matches by file
    matches_by_file: dict[Path, list[Match]] = {}
    for match in matches:
        if match.file not in matches_by_file:
            matches_by_file[match.file] = []
        matches_by_file[match.file].append(match)

    files_modified = 0
    total_replacements = 0

    for file_path, file_matches in matches_by_file.items():
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue

        # Build replacement map for this file
        # We need to replace longer matches first to avoid partial replacements
        # Sort by match text length (descending) then by text (for determinism)
        sorted_matches = sorted(
            file_matches,
            key=lambda m: (-len(m.matched_text), m.matched_text),
        )

        # Get unique matched texts in this file
        unique_texts = []
        seen = set()
        for m in sorted_matches:
            if m.matched_text not in seen:
                unique_texts.append(m.matched_text)
                seen.add(m.matched_text)

        # Apply replacements
        new_content = content
        for text in unique_texts:
            pseudonym = fixer.get_pseudonym(text)
            new_content = new_content.replace(text, pseudonym)

        # Count replacements in this file
        file_replacement_count = sum(content.count(text) for text in unique_texts)

        if new_content != content:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            files_modified += 1
            total_replacements += file_replacement_count

    # Write mapping file if requested
    mapping = fixer.mapping
    if output_map is not None:
        output_map.parent.mkdir(parents=True, exist_ok=True)
        with open(output_map, "w", encoding="utf-8") as f:
            json.dump(mapping, f, indent=2)

    return FixResult(
        files_modified=files_modified,
        total_replacements=total_replacements,
        unique_values=len(mapping),
        mapping=mapping,
    )
