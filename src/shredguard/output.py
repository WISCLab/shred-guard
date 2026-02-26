"""Output formatting for ShredGuard."""

from __future__ import annotations

import sys
from pathlib import Path

from .fixer import FixResult, PrefixCollisionError
from .scanner import Match


# ANSI color codes
class Colors:
    """ANSI color codes for terminal output."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    DIM = "\033[2m"


def supports_color() -> bool:
    """Check if the terminal supports color output."""
    # Check for NO_COLOR environment variable
    import os

    if os.environ.get("NO_COLOR"):
        return False

    # Check for FORCE_COLOR environment variable
    if os.environ.get("FORCE_COLOR"):
        return True

    # Check if stdout is a TTY
    if not hasattr(sys.stdout, "isatty"):
        return False

    return sys.stdout.isatty()


def supports_unicode() -> bool:
    """Check if the terminal supports Unicode output."""
    import os

    if os.environ.get("FORCE_ASCII"):
        return False

    if os.environ.get("FORCE_UNICODE"):
        return True

    # Check stdout encoding - this is the most reliable way to determine
    # if Unicode characters can be written without encoding errors
    encoding = getattr(sys.stdout, "encoding", None) or ""
    encoding = encoding.lower().replace("-", "").replace("_", "")

    # Only allow Unicode if we have a Unicode-capable encoding
    return encoding in ("utf8", "utf16", "utf32")


class Formatter:
    """Formats output for the terminal."""

    def __init__(self, use_color: bool | None = None, use_unicode: bool | None = None):
        """Initialize the formatter.

        Args:
            use_color: Whether to use color. None = auto-detect.
            use_unicode: Whether to use Unicode symbols. None = auto-detect.
        """
        if use_color is None:
            use_color = supports_color()
        if use_unicode is None:
            use_unicode = supports_unicode()
        self.use_color = use_color
        self.use_unicode = use_unicode

    @property
    def check_mark(self) -> str:
        """Return check mark symbol (Unicode or ASCII fallback)."""
        return "\u2713" if self.use_unicode else "[OK]"

    @property
    def x_mark(self) -> str:
        """Return X mark symbol (Unicode or ASCII fallback)."""
        return "\u2717" if self.use_unicode else "[X]"

    def _color(self, text: str, *codes: str) -> str:
        """Apply color codes to text."""
        if not self.use_color:
            return text
        return "".join(codes) + text + Colors.RESET

    def format_match(self, match: Match, base_path: Path | None = None) -> str:
        """Format a single match in ruff-style output.

        Format: file:line:col: SGxxx Description [matched text]

        Args:
            match: The match to format.
            base_path: Base path for relative path display.

        Returns:
            Formatted string.
        """
        # Make path relative if possible
        file_path = match.file
        if base_path:
            try:
                file_path = match.file.relative_to(base_path)
            except ValueError:
                pass

        location = self._color(
            f"{file_path}:{match.line}:{match.column}:",
            Colors.BOLD,
        )

        code = self._color(match.pattern.code, Colors.RED, Colors.BOLD)
        description = match.pattern.description
        matched = self._color(f"[{match.matched_text}]", Colors.YELLOW)

        return f"{location} {code} {description} {matched}"

    def format_matches(
        self, matches: list[Match], base_path: Path | None = None
    ) -> str:
        """Format multiple matches.

        Args:
            matches: List of matches to format.
            base_path: Base path for relative path display.

        Returns:
            Formatted string with newlines between matches.
        """
        return "\n".join(self.format_match(m, base_path) for m in matches)

    def format_check_summary(
        self, match_count: int, file_count: int, pattern_count: int
    ) -> str:
        """Format the check command summary.

        Args:
            match_count: Total number of matches.
            file_count: Number of files with matches.
            pattern_count: Number of patterns checked.

        Returns:
            Formatted summary string.
        """
        if match_count == 0:
            check = self._color(self.check_mark, Colors.GREEN, Colors.BOLD)
            return f"{check} No PHI patterns found ({pattern_count} patterns checked)"

        x_mark = self._color(self.x_mark, Colors.RED, Colors.BOLD)
        matches_word = "match" if match_count == 1 else "matches"
        files_word = "file" if file_count == 1 else "files"

        return (
            f"{x_mark} Found {match_count} {matches_word} "
            f"in {file_count} {files_word}"
        )

    def format_fix_summary(self, result: FixResult) -> str:
        """Format the fix command summary.

        Args:
            result: The fix result.

        Returns:
            Formatted summary string.
        """
        if result.total_replacements == 0:
            check = self._color(self.check_mark, Colors.GREEN, Colors.BOLD)
            return f"{check} No replacements needed"

        check = self._color(self.check_mark, Colors.GREEN, Colors.BOLD)
        files_word = "file" if result.files_modified == 1 else "files"
        values_word = "value" if result.unique_values == 1 else "values"

        return (
            f"{check} Replaced {result.total_replacements} occurrences "
            f"of {result.unique_values} unique {values_word} "
            f"in {result.files_modified} {files_word}"
        )

    def format_prefix_collision_error(self, error: PrefixCollisionError) -> str:
        """Format a prefix collision error.

        Args:
            error: The error to format.

        Returns:
            Formatted error string.
        """
        lines = [
            self._color(
                f"Error: Prefix '{error.prefix}' already exists in files",
                Colors.RED,
                Colors.BOLD,
            ),
            "",
            "The following collisions were found:",
        ]

        for file_path, line_num, text in error.collisions[:10]:  # Limit output
            lines.append(f"  {file_path}:{line_num}: {text}")

        if len(error.collisions) > 10:
            lines.append(f"  ... and {len(error.collisions) - 10} more")

        lines.append("")
        lines.append("Choose a different prefix with --prefix")

        return "\n".join(lines)

    def format_error(self, message: str) -> str:
        """Format a generic error message.

        Args:
            message: The error message.

        Returns:
            Formatted error string.
        """
        error_label = self._color("Error:", Colors.RED, Colors.BOLD)
        return f"{error_label} {message}"

    def format_warning(self, message: str) -> str:
        """Format a warning message.

        Args:
            message: The warning message.

        Returns:
            Formatted warning string.
        """
        warning_label = self._color("Warning:", Colors.YELLOW, Colors.BOLD)
        return f"{warning_label} {message}"

    def format_verbose_binary_skip(self, path: Path) -> str:
        """Format a verbose message about skipping a binary file.

        Args:
            path: Path to the skipped file.

        Returns:
            Formatted message.
        """
        skip_label = self._color("Skip:", Colors.DIM)
        return f"{skip_label} {path} (binary file)"
