"""Configuration loading for ShredGuard."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


class ConfigError(Exception):
    """Raised when configuration is invalid or missing."""


@dataclass
class Pattern:
    """A pattern to scan for in files."""

    regex: str
    description: str
    code: str  # e.g., "SG001"
    compiled: re.Pattern[str] = field(repr=False)
    files: list[str] = field(default_factory=list)
    exclude_files: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict, index: int) -> Pattern:
        """Create a Pattern from a config dictionary."""
        regex = data.get("regex")
        if not regex:
            raise ConfigError(f"Pattern {index + 1} missing 'regex' field")

        description = data.get("description", f"Pattern {index + 1}")

        try:
            compiled = re.compile(regex)
        except re.error as e:
            raise ConfigError(
                f"Invalid regex in pattern {index + 1} ({description!r}): {e}"
            ) from e

        code = f"SG{index + 1:03d}"

        files = data.get("files", [])
        if not isinstance(files, list):
            files = [files]

        exclude_files = data.get("exclude_files", [])
        if not isinstance(exclude_files, list):
            exclude_files = [exclude_files]

        return cls(
            regex=regex,
            description=description,
            code=code,
            compiled=compiled,
            files=files,
            exclude_files=exclude_files,
        )


@dataclass
class Config:
    """ShredGuard configuration."""

    patterns: list[Pattern]
    config_path: Path | None = None

    @classmethod
    def load(cls, config_path: Path | None = None) -> Config:
        """Load configuration from a file.

        Args:
            config_path: Path to config file. If None, searches for pyproject.toml
                        in current directory and parents.

        Returns:
            Loaded configuration.

        Raises:
            ConfigError: If config is missing or invalid.
        """
        if config_path is not None:
            return cls._load_from_file(config_path)

        # Search for pyproject.toml
        search_path = Path.cwd()
        while True:
            pyproject = search_path / "pyproject.toml"
            if pyproject.exists():
                try:
                    return cls._load_from_file(pyproject)
                except ConfigError as e:
                    if "No [tool.shredguard]" in str(e):
                        # Keep searching parent directories
                        pass
                    else:
                        raise

            parent = search_path.parent
            if parent == search_path:
                break
            search_path = parent

        raise ConfigError(
            "No shredguard configuration found.\n\n"
            "Add a [tool.shredguard] section to your pyproject.toml:\n\n"
            "    [tool.shredguard]\n"
            "    [[tool.shredguard.patterns]]\n"
            '    regex = "SUB-\\\\d{4,6}"\n'
            '    description = "Subject ID"\n'
        )

    @classmethod
    def _load_from_file(cls, path: Path) -> Config:
        """Load configuration from a specific file."""
        if not path.exists():
            raise ConfigError(f"Config file not found: {path}")

        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"Invalid TOML in {path}: {e}") from e

        # Navigate to [tool.shredguard] section
        tool_section = data.get("tool", {})
        if "shredguard" not in tool_section:
            raise ConfigError(f"No [tool.shredguard] section found in {path}")

        shredguard_section = tool_section.get("shredguard", {})

        patterns_data = shredguard_section.get("patterns", [])

        if not patterns_data:
            raise ConfigError(
                f"No patterns defined in {path}.\n\n"
                "Add at least one pattern:\n\n"
                "    [[tool.shredguard.patterns]]\n"
                '    regex = "SUB-\\\\d{4,6}"\n'
                '    description = "Subject ID"\n'
            )

        patterns = []
        for i, pattern_data in enumerate(patterns_data):
            patterns.append(Pattern.from_dict(pattern_data, i))

        return cls(patterns=patterns, config_path=path)
