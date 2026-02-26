"""Tests for shredguard.scanner module."""

import pytest
from pathlib import Path

from shredguard.config import Pattern
from shredguard.scanner import (
    Match,
    is_binary_file,
    file_matches_globs,
    scan_file,
    scan_files,
)


def make_pattern(regex: str, description: str = "Test", index: int = 0, **kwargs) -> Pattern:
    """Helper to create a Pattern for testing."""
    data = {"regex": regex, "description": description, **kwargs}
    return Pattern.from_dict(data, index)


class TestIsBinaryFile:
    """Tests for is_binary_file function."""

    def test_text_file(self, tmp_path: Path):
        """Test that text files are not detected as binary."""
        text_file = tmp_path / "test.txt"
        text_file.write_text("Hello, world!")

        assert not is_binary_file(text_file)

    def test_binary_file(self, tmp_path: Path):
        """Test that binary files are detected."""
        binary_file = tmp_path / "test.bin"
        binary_file.write_bytes(b"Hello\x00World")

        assert is_binary_file(binary_file)

    def test_nonexistent_file(self, tmp_path: Path):
        """Test that nonexistent files are treated as binary."""
        assert is_binary_file(tmp_path / "nonexistent.txt")

    def test_unicode_file(self, tmp_path: Path):
        """Test that unicode text files are not binary."""
        unicode_file = tmp_path / "unicode.txt"
        # Use UTF-8 encoding explicitly and characters that won't cause
        # Windows console encoding issues when pytest displays errors
        unicode_file.write_text("Hello, caf\u00e9! \u00e9\u00e8\u00e0", encoding="utf-8")

        assert not is_binary_file(unicode_file)


class TestFileMatchesGlobs:
    """Tests for file_matches_globs function."""

    def test_no_globs_matches_all(self):
        """Test that empty globs match all files."""
        path = Path("test.txt")
        assert file_matches_globs(path, [], [])

    def test_include_glob_matches(self):
        """Test that include globs work."""
        path = Path("data.csv")
        assert file_matches_globs(path, ["*.csv"], [])
        assert not file_matches_globs(path, ["*.txt"], [])

    def test_exclude_glob_excludes(self):
        """Test that exclude globs work."""
        path = Path("test_data.csv")
        assert not file_matches_globs(path, [], ["test_*"])
        assert file_matches_globs(path, [], ["prod_*"])

    def test_exclude_takes_precedence(self):
        """Test that exclude patterns take precedence over include."""
        path = Path("test.csv")
        assert not file_matches_globs(path, ["*.csv"], ["test.*"])

    def test_path_glob_matching(self):
        """Test matching against full path."""
        path = Path("data/files/test.csv")
        assert file_matches_globs(path, ["data/**"], [])


class TestScanFile:
    """Tests for scan_file function."""

    def test_finds_matches(self, tmp_path: Path):
        """Test that matches are found correctly."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Subject SUB-1234 enrolled\n")

        pattern = make_pattern(r"SUB-\d{4}", "Subject ID")
        matches, was_binary = scan_file(test_file, [pattern])

        assert not was_binary
        assert len(matches) == 1
        assert matches[0].matched_text == "SUB-1234"
        assert matches[0].line == 1
        assert matches[0].column == 9

    def test_multiple_matches(self, tmp_path: Path):
        """Test finding multiple matches in a file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("SUB-1234 and SUB-5678 enrolled\n")

        pattern = make_pattern(r"SUB-\d{4}", "Subject ID")
        matches, _ = scan_file(test_file, [pattern])

        assert len(matches) == 2
        assert matches[0].matched_text == "SUB-1234"
        assert matches[1].matched_text == "SUB-5678"

    def test_multiple_patterns(self, tmp_path: Path):
        """Test scanning with multiple patterns."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("SUB-1234 MRN123456\n")

        patterns = [
            make_pattern(r"SUB-\d{4}", "Subject ID", 0),
            make_pattern(r"MRN\d{6}", "MRN", 1),
        ]
        matches, _ = scan_file(test_file, patterns)

        assert len(matches) == 2
        codes = {m.pattern.code for m in matches}
        assert "SG001" in codes
        assert "SG002" in codes

    def test_line_column_positions(self, tmp_path: Path):
        """Test that line and column positions are correct."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("first line\n  SUB-1234 on line 2\nthird line\n")

        pattern = make_pattern(r"SUB-\d{4}", "Subject ID")
        matches, _ = scan_file(test_file, [pattern])

        assert len(matches) == 1
        assert matches[0].line == 2
        assert matches[0].column == 3  # After "  "

    def test_binary_file_skipped(self, tmp_path: Path):
        """Test that binary files are skipped."""
        binary_file = tmp_path / "test.bin"
        binary_file.write_bytes(b"SUB-1234\x00binary")

        pattern = make_pattern(r"SUB-\d{4}", "Subject ID")
        matches, was_binary = scan_file(binary_file, [pattern])

        assert was_binary
        assert len(matches) == 0

    def test_file_glob_scoping(self, tmp_path: Path):
        """Test that patterns respect file glob scoping."""
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("SUB-1234,data\n")

        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("SUB-5678 in notes\n")

        # Pattern only applies to CSV files
        pattern = make_pattern(r"SUB-\d{4}", "Subject ID", files=["*.csv"])

        csv_matches, _ = scan_file(csv_file, [pattern])
        txt_matches, _ = scan_file(txt_file, [pattern])

        assert len(csv_matches) == 1
        assert len(txt_matches) == 0

    def test_exclude_file_glob(self, tmp_path: Path):
        """Test that exclude file globs work."""
        test_file = tmp_path / "test_data.txt"
        test_file.write_text("SUB-1234\n")

        pattern = make_pattern(r"SUB-\d{4}", "Subject ID", exclude_files=["test_*"])
        matches, _ = scan_file(test_file, [pattern])

        assert len(matches) == 0

    def test_handles_crlf_line_endings(self, tmp_path: Path):
        """Test handling of Windows line endings."""
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"line1\r\nSUB-1234\r\nline3\r\n")

        pattern = make_pattern(r"SUB-\d{4}", "Subject ID")
        matches, _ = scan_file(test_file, [pattern])

        assert len(matches) == 1
        assert matches[0].line == 2


class TestScanFiles:
    """Tests for scan_files function."""

    def test_scans_multiple_files(self, tmp_path: Path):
        """Test scanning multiple files."""
        file1 = tmp_path / "file1.txt"
        file1.write_text("SUB-1234\n")

        file2 = tmp_path / "file2.txt"
        file2.write_text("SUB-5678\n")

        pattern = make_pattern(r"SUB-\d{4}", "Subject ID")
        matches, binary_files = scan_files([file1, file2], [pattern])

        assert len(matches) == 2
        assert len(binary_files) == 0

    def test_returns_sorted_matches(self, tmp_path: Path):
        """Test that matches are sorted by file, line, column."""
        file1 = tmp_path / "a.txt"
        file1.write_text("SUB-2222\nSUB-1111\n")

        file2 = tmp_path / "b.txt"
        file2.write_text("SUB-3333\n")

        pattern = make_pattern(r"SUB-\d{4}", "Subject ID")
        matches, _ = scan_files([file2, file1], [pattern])

        # Should be sorted: a.txt line 1, a.txt line 2, b.txt line 1
        assert matches[0].file.name == "a.txt"
        assert matches[0].line == 1
        assert matches[1].file.name == "a.txt"
        assert matches[1].line == 2
        assert matches[2].file.name == "b.txt"

    def test_tracks_binary_files(self, tmp_path: Path):
        """Test that binary files are tracked."""
        text_file = tmp_path / "text.txt"
        text_file.write_text("SUB-1234\n")

        binary_file = tmp_path / "binary.bin"
        binary_file.write_bytes(b"\x00binary")

        pattern = make_pattern(r"SUB-\d{4}", "Subject ID")
        matches, binary_files = scan_files([text_file, binary_file], [pattern])

        assert len(matches) == 1
        assert len(binary_files) == 1
        assert binary_files[0] == binary_file


class TestMatch:
    """Tests for Match class."""

    def test_location_property(self, tmp_path: Path):
        """Test the location property format."""
        match = Match(
            file=Path("test.txt"),
            line=10,
            column=5,
            matched_text="SUB-1234",
            pattern=make_pattern(r"SUB-\d{4}"),
        )

        assert match.location == "test.txt:10:5"
