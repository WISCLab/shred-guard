"""Tests for shredguard.fixer module."""

import json
import pytest
from pathlib import Path

from shredguard.config import Pattern
from shredguard.fixer import (
    Fixer,
    FixResult,
    PrefixCollisionError,
    check_prefix_collisions,
    apply_fixes,
)
from shredguard.scanner import Match


def make_pattern(regex: str, description: str = "Test", index: int = 0) -> Pattern:
    """Helper to create a Pattern for testing."""
    data = {"regex": regex, "description": description}
    return Pattern.from_dict(data, index)


class TestFixer:
    """Tests for Fixer class."""

    def test_deterministic_pseudonyms(self):
        """Test that same value gets same pseudonym."""
        fixer = Fixer(prefix="TEST")

        id1 = fixer.get_pseudonym("SUB-1234")
        id2 = fixer.get_pseudonym("SUB-5678")
        id3 = fixer.get_pseudonym("SUB-1234")  # Same as first

        assert id1 == "TEST-0"
        assert id2 == "TEST-1"
        assert id3 == "TEST-0"  # Same as id1

    def test_pseudonyms_assigned_in_order(self):
        """Test that pseudonyms are assigned in encounter order."""
        fixer = Fixer(prefix="ID")

        fixer.get_pseudonym("first")
        fixer.get_pseudonym("second")
        fixer.get_pseudonym("third")

        assert fixer.mapping == {
            "first": "ID-0",
            "second": "ID-1",
            "third": "ID-2",
        }

    def test_mapping_property(self):
        """Test that mapping property returns a copy."""
        fixer = Fixer(prefix="TEST")
        fixer.get_pseudonym("value")

        mapping = fixer.mapping
        mapping["new"] = "TEST-99"  # Modify the copy

        # Original should be unchanged
        assert "new" not in fixer.mapping


class TestCheckPrefixCollisions:
    """Tests for check_prefix_collisions function."""

    def test_no_collisions(self, tmp_path: Path):
        """Test when no collisions exist."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("No collisions here\n")

        collisions = check_prefix_collisions([test_file], "REDACTED")
        assert len(collisions) == 0

    def test_finds_collisions(self, tmp_path: Path):
        """Test that existing prefix patterns are found."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Already has REDACTED-0 and REDACTED-1\n")

        collisions = check_prefix_collisions([test_file], "REDACTED")

        assert len(collisions) == 2
        assert collisions[0][0] == test_file
        assert collisions[0][1] == 1  # Line number
        assert "REDACTED-0" in collisions[0][2]

    def test_collision_in_multiple_files(self, tmp_path: Path):
        """Test finding collisions across multiple files."""
        file1 = tmp_path / "file1.txt"
        file1.write_text("ANON-0 here\n")

        file2 = tmp_path / "file2.txt"
        file2.write_text("ANON-1 there\n")

        collisions = check_prefix_collisions([file1, file2], "ANON")

        assert len(collisions) == 2

    def test_different_prefix_no_collision(self, tmp_path: Path):
        """Test that different prefixes don't collide."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Has OTHER-0 but checking for REDACTED\n")

        collisions = check_prefix_collisions([test_file], "REDACTED")
        assert len(collisions) == 0


class TestApplyFixes:
    """Tests for apply_fixes function."""

    def test_basic_replacement(self, tmp_path: Path):
        """Test basic replacement of matches."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Subject SUB-1234 enrolled\n")

        pattern = make_pattern(r"SUB-\d{4}")
        match = Match(
            file=test_file,
            line=1,
            column=9,
            matched_text="SUB-1234",
            pattern=pattern,
        )

        result = apply_fixes([match], "REDACTED")

        assert result.files_modified == 1
        assert result.total_replacements == 1
        assert result.unique_values == 1
        assert result.mapping == {"SUB-1234": "REDACTED-0"}

        # Verify file was modified
        assert test_file.read_text() == "Subject REDACTED-0 enrolled\n"

    def test_multiple_occurrences_same_value(self, tmp_path: Path):
        """Test that same value is replaced consistently."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("SUB-1234 and SUB-1234 again\n")

        pattern = make_pattern(r"SUB-\d{4}")
        matches = [
            Match(file=test_file, line=1, column=1, matched_text="SUB-1234", pattern=pattern),
            Match(file=test_file, line=1, column=14, matched_text="SUB-1234", pattern=pattern),
        ]

        result = apply_fixes(matches, "ID")

        assert result.unique_values == 1
        assert result.total_replacements == 2
        assert test_file.read_text() == "ID-0 and ID-0 again\n"

    def test_multiple_different_values(self, tmp_path: Path):
        """Test replacing multiple different values."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("SUB-1234 and SUB-5678\n")

        pattern = make_pattern(r"SUB-\d{4}")
        matches = [
            Match(file=test_file, line=1, column=1, matched_text="SUB-1234", pattern=pattern),
            Match(file=test_file, line=1, column=14, matched_text="SUB-5678", pattern=pattern),
        ]

        result = apply_fixes(matches, "ID")

        assert result.unique_values == 2
        assert "SUB-1234" in result.mapping
        assert "SUB-5678" in result.mapping

    def test_prefix_collision_error(self, tmp_path: Path):
        """Test that prefix collision raises error."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Already has REDACTED-0\n")

        pattern = make_pattern(r"SUB-\d{4}")
        match = Match(
            file=test_file,
            line=1,
            column=1,
            matched_text="SUB-1234",
            pattern=pattern,
        )

        with pytest.raises(PrefixCollisionError) as exc_info:
            apply_fixes([match], "REDACTED")

        assert exc_info.value.prefix == "REDACTED"
        assert len(exc_info.value.collisions) == 1

    def test_writes_mapping_file(self, tmp_path: Path):
        """Test that mapping file is written correctly."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("SUB-1234\n")

        mapping_file = tmp_path / "mapping.json"

        pattern = make_pattern(r"SUB-\d{4}")
        match = Match(
            file=test_file,
            line=1,
            column=1,
            matched_text="SUB-1234",
            pattern=pattern,
        )

        apply_fixes([match], "ID", output_map=mapping_file)

        assert mapping_file.exists()
        mapping = json.loads(mapping_file.read_text())
        assert mapping == {"SUB-1234": "ID-0"}

    def test_empty_matches_no_error(self):
        """Test that empty matches list works."""
        result = apply_fixes([], "REDACTED")

        assert result.files_modified == 0
        assert result.total_replacements == 0
        assert result.unique_values == 0

    def test_creates_mapping_dir_if_needed(self, tmp_path: Path):
        """Test that output_map parent directories are created."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("SUB-1234\n")

        mapping_file = tmp_path / "subdir" / "deep" / "mapping.json"

        pattern = make_pattern(r"SUB-\d{4}")
        match = Match(
            file=test_file,
            line=1,
            column=1,
            matched_text="SUB-1234",
            pattern=pattern,
        )

        apply_fixes([match], "ID", output_map=mapping_file)

        assert mapping_file.exists()

    def test_multiple_files(self, tmp_path: Path):
        """Test fixing matches across multiple files."""
        file1 = tmp_path / "file1.txt"
        file1.write_text("SUB-1234\n")

        file2 = tmp_path / "file2.txt"
        file2.write_text("SUB-5678\n")

        pattern = make_pattern(r"SUB-\d{4}")
        matches = [
            Match(file=file1, line=1, column=1, matched_text="SUB-1234", pattern=pattern),
            Match(file=file2, line=1, column=1, matched_text="SUB-5678", pattern=pattern),
        ]

        result = apply_fixes(matches, "ID")

        assert result.files_modified == 2
        assert file1.read_text() == "ID-0\n"
        assert file2.read_text() == "ID-1\n"


class TestPrefixCollisionError:
    """Tests for PrefixCollisionError class."""

    def test_error_message(self):
        """Test error message format."""
        error = PrefixCollisionError(
            "TEST",
            [(Path("file.txt"), 1, "TEST-0"), (Path("file.txt"), 2, "TEST-1")],
        )

        assert "TEST" in str(error)
        assert "2 location" in str(error)

    def test_attributes(self):
        """Test error attributes."""
        collisions = [(Path("file.txt"), 1, "TEST-0")]
        error = PrefixCollisionError("TEST", collisions)

        assert error.prefix == "TEST"
        assert error.collisions == collisions
