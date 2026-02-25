"""
End-to-end CLI tests for ShredGuard.

These tests invoke the CLI as a user would, documenting expected behavior
through executable examples. Each test class represents a feature area,
and each test method documents a specific use case.

Run with: pytest tests/test_cli_e2e.py -v
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest


class CLIRunner:
    """Helper to run shredguard CLI commands and capture output."""

    def __init__(self, workdir: Path):
        self.workdir = workdir
        self.env = None  # Can be extended to modify env vars

    def run(self, *args: str, expect_fail: bool = False) -> "CLIResult":
        """Run shredguard with the given arguments.

        Args:
            *args: Command line arguments (e.g., "check", "file.txt")
            expect_fail: If True, expect non-zero exit code

        Returns:
            CLIResult with stdout, stderr, and exit_code
        """
        cmd = [sys.executable, "-m", "shredguard", *args]
        result = subprocess.run(
            cmd,
            cwd=self.workdir,
            capture_output=True,
            text=True,
            env=self.env,
        )

        cli_result = CLIResult(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
            command=" ".join(["shredguard", *args]),
        )

        if expect_fail:
            assert cli_result.exit_code != 0, (
                f"Expected command to fail: {cli_result.command}\n"
                f"stdout: {cli_result.stdout}\n"
                f"stderr: {cli_result.stderr}"
            )
        else:
            assert cli_result.exit_code == 0, (
                f"Command failed: {cli_result.command}\n"
                f"stdout: {cli_result.stdout}\n"
                f"stderr: {cli_result.stderr}"
            )

        return cli_result


class CLIResult:
    """Result of a CLI invocation."""

    def __init__(self, stdout: str, stderr: str, exit_code: int, command: str):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.command = command
        self.output = stdout + stderr  # Combined for easier assertions

    def __repr__(self) -> str:
        return f"CLIResult(exit_code={self.exit_code}, command={self.command!r})"

    def assert_contains(self, text: str) -> "CLIResult":
        """Assert output contains text. Returns self for chaining."""
        assert text in self.output, (
            f"Expected output to contain: {text!r}\n"
            f"Actual output: {self.output}"
        )
        return self

    def assert_not_contains(self, text: str) -> "CLIResult":
        """Assert output does not contain text. Returns self for chaining."""
        assert text not in self.output, (
            f"Expected output NOT to contain: {text!r}\n"
            f"Actual output: {self.output}"
        )
        return self

    def assert_match_format(self, file: str, line: int, col: int, code: str) -> "CLIResult":
        """Assert output contains a match in ruff-style format."""
        pattern = f"{file}:{line}:{col}: {code}"
        assert pattern in self.output, (
            f"Expected match format: {pattern}\n"
            f"Actual output: {self.output}"
        )
        return self


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Create a test project with default config."""
    config = tmp_path / "pyproject.toml"
    config.write_text(dedent("""
        [tool.shredguard]
        [[tool.shredguard.patterns]]
        regex = "SUB-\\\\d{4,6}"
        description = "Subject ID"

        [[tool.shredguard.patterns]]
        regex = "\\\\b\\\\d{3}-\\\\d{2}-\\\\d{4}\\\\b"
        description = "SSN-like pattern"

        [[tool.shredguard.patterns]]
        regex = "MRN\\\\d{6,10}"
        description = "Medical Record Number"
    """).strip())
    return tmp_path


@pytest.fixture
def cli(project: Path) -> CLIRunner:
    """Create a CLI runner for the test project."""
    return CLIRunner(project)


# =============================================================================
# CHECK COMMAND
# =============================================================================

class TestCheckCommand:
    """
    shredguard check [OPTIONS] [FILES]...

    Scan files for PHI patterns. Exit code 0 if clean, 1 if matches found.
    """

    def test_clean_file_returns_success(self, cli: CLIRunner, project: Path):
        """
        GIVEN a file with no PHI patterns
        WHEN running `shredguard check <file>`
        THEN exit code is 0 and output confirms no patterns found
        """
        (project / "clean.txt").write_text("This file has no PHI.\n")

        result = cli.run("check", "clean.txt")

        result.assert_contains("No PHI patterns found")

    def test_file_with_phi_returns_failure(self, cli: CLIRunner, project: Path):
        """
        GIVEN a file containing a PHI pattern (Subject ID)
        WHEN running `shredguard check <file>`
        THEN exit code is 1 and output shows the match location
        """
        (project / "data.txt").write_text("Patient SUB-1234 was enrolled.\n")

        result = cli.run("check", "data.txt", expect_fail=True)

        result.assert_match_format("data.txt", 1, 9, "SG001")
        result.assert_contains("SUB-1234")
        result.assert_contains("Subject ID")

    def test_multiple_patterns_detected(self, cli: CLIRunner, project: Path):
        """
        GIVEN a file with multiple different PHI patterns
        WHEN running `shredguard check <file>`
        THEN all patterns are reported with their respective codes
        """
        (project / "data.txt").write_text(dedent("""
            Subject: SUB-1234
            SSN: 123-45-6789
            MRN: MRN12345678
        """).strip())

        result = cli.run("check", "data.txt", expect_fail=True)

        result.assert_contains("SG001")  # Subject ID
        result.assert_contains("SG002")  # SSN
        result.assert_contains("SG003")  # MRN
        result.assert_contains("Found 3 matches")

    def test_scan_directory_recursively(self, cli: CLIRunner, project: Path):
        """
        GIVEN a directory with PHI in nested files
        WHEN running `shredguard check <directory>`
        THEN files in subdirectories are scanned
        """
        subdir = project / "data" / "patients"
        subdir.mkdir(parents=True)
        (subdir / "record.txt").write_text("SUB-5678\n")

        result = cli.run("check", "data", expect_fail=True)

        result.assert_contains("SUB-5678")

    def test_respects_gitignore(self, cli: CLIRunner, project: Path):
        """
        GIVEN a .gitignore that excludes certain files
        WHEN running `shredguard check <directory>`
        THEN ignored files are not scanned
        """
        (project / ".gitignore").write_text("ignored/\n")
        ignored_dir = project / "ignored"
        ignored_dir.mkdir()
        (ignored_dir / "secret.txt").write_text("SUB-1234\n")
        (project / "scanned.txt").write_text("Clean file\n")

        result = cli.run("check", ".")

        result.assert_not_contains("SUB-1234")
        result.assert_contains("No PHI patterns found")

    def test_no_gitignore_flag_disables_gitignore(self, cli: CLIRunner, project: Path):
        """
        GIVEN a .gitignore that excludes certain files
        WHEN running `shredguard check --no-gitignore <directory>`
        THEN ignored files ARE scanned
        """
        (project / ".gitignore").write_text("ignored.txt\n")
        (project / "ignored.txt").write_text("SUB-1234\n")

        result = cli.run("check", "--no-gitignore", ".", expect_fail=True)

        result.assert_contains("SUB-1234")

    def test_skips_binary_files(self, cli: CLIRunner, project: Path):
        """
        GIVEN a directory with both text and binary files
        WHEN running `shredguard check <directory>`
        THEN binary files are silently skipped
        """
        (project / "text.txt").write_text("Clean text\n")
        (project / "binary.bin").write_bytes(b"SUB-1234\x00binary")

        result = cli.run("check", ".")

        result.assert_contains("No PHI patterns found")

    def test_verbose_shows_skipped_files(self, cli: CLIRunner, project: Path):
        """
        GIVEN a directory with binary files
        WHEN running `shredguard check --verbose <directory>`
        THEN skipped binary files are reported
        """
        (project / "binary.bin").write_bytes(b"\x00binary")

        result = cli.run("check", "--verbose", ".")

        result.assert_contains("binary")


# =============================================================================
# FIX COMMAND
# =============================================================================

class TestFixCommand:
    """
    shredguard fix [OPTIONS] [FILES]...

    Replace PHI patterns with deterministic pseudonyms.
    """

    def test_basic_replacement(self, cli: CLIRunner, project: Path):
        """
        GIVEN a file with a PHI pattern
        WHEN running `shredguard fix --prefix ID <file>`
        THEN the pattern is replaced with ID-0
        """
        data_file = project / "data.txt"
        data_file.write_text("Patient SUB-1234 enrolled.\n")

        cli.run("fix", "--prefix", "ID", "data.txt")

        assert data_file.read_text() == "Patient ID-0 enrolled.\n"

    def test_deterministic_replacement(self, cli: CLIRunner, project: Path):
        """
        GIVEN a file with the same PHI value multiple times
        WHEN running `shredguard fix`
        THEN all occurrences get the same pseudonym
        """
        data_file = project / "data.txt"
        data_file.write_text("SUB-1234 and SUB-1234 again\n")

        cli.run("fix", "--prefix", "ID", "data.txt")

        assert data_file.read_text() == "ID-0 and ID-0 again\n"

    def test_different_values_get_different_ids(self, cli: CLIRunner, project: Path):
        """
        GIVEN a file with different PHI values
        WHEN running `shredguard fix`
        THEN each unique value gets a different pseudonym
        """
        data_file = project / "data.txt"
        data_file.write_text("SUB-1111 and SUB-2222\n")

        cli.run("fix", "--prefix", "ID", "data.txt")

        content = data_file.read_text()
        assert "ID-0" in content
        assert "ID-1" in content

    def test_default_prefix_is_redacted(self, cli: CLIRunner, project: Path):
        """
        GIVEN a file with PHI
        WHEN running `shredguard fix` without --prefix
        THEN the default prefix "REDACTED" is used
        """
        data_file = project / "data.txt"
        data_file.write_text("SUB-1234\n")

        cli.run("fix", "data.txt")

        assert data_file.read_text() == "REDACTED-0\n"

    def test_output_map_creates_json_mapping(self, cli: CLIRunner, project: Path):
        """
        GIVEN a file with PHI
        WHEN running `shredguard fix --output-map mapping.json`
        THEN a JSON file is created with original -> pseudonym mapping
        """
        (project / "data.txt").write_text("SUB-1234 and SUB-5678\n")

        cli.run("fix", "--prefix", "ID", "--output-map", "mapping.json", "data.txt")

        mapping = json.loads((project / "mapping.json").read_text())
        assert mapping == {"SUB-1234": "ID-0", "SUB-5678": "ID-1"}

    def test_no_matches_reports_nothing_to_do(self, cli: CLIRunner, project: Path):
        """
        GIVEN a file with no PHI
        WHEN running `shredguard fix`
        THEN output indicates no replacements needed
        """
        (project / "clean.txt").write_text("No PHI here\n")

        result = cli.run("fix", "clean.txt")

        result.assert_contains("No replacements needed")


# =============================================================================
# PREFIX COLLISION DETECTION
# =============================================================================

class TestPrefixCollisionDetection:
    """
    ShredGuard prevents accidental double-redaction by detecting
    existing pseudonyms before making any changes.
    """

    def test_collision_in_file_with_phi(self, cli: CLIRunner, project: Path):
        """
        GIVEN a file that has both PHI AND an existing pseudonym
        WHEN running `shredguard fix`
        THEN the command fails before making any changes
        """
        data_file = project / "data.txt"
        data_file.write_text("SUB-1234 and REDACTED-0 already here\n")

        result = cli.run("fix", "data.txt", expect_fail=True)

        result.assert_contains("already exists")
        # Verify file unchanged
        assert "SUB-1234" in data_file.read_text()

    def test_collision_in_file_without_phi(self, cli: CLIRunner, project: Path):
        """
        GIVEN multiple files where one has PHI and another has existing pseudonyms
        WHEN running `shredguard fix` on the directory
        THEN the command fails because of collision in the non-PHI file

        This is a critical test - collisions must be detected in ALL files,
        not just files that contain PHI patterns.
        """
        # File WITH PHI
        phi_file = project / "phi.txt"
        phi_file.write_text("SUB-1234\n")

        # File WITHOUT PHI but with existing pseudonym
        other_file = project / "other.txt"
        other_file.write_text("Some notes about REDACTED-0 from previous run\n")

        result = cli.run("fix", ".", expect_fail=True)

        result.assert_contains("already exists")
        # Verify PHI file was NOT modified
        assert phi_file.read_text() == "SUB-1234\n"

    def test_different_prefix_avoids_collision(self, cli: CLIRunner, project: Path):
        """
        GIVEN a file with existing REDACTED-0 pseudonyms
        WHEN running `shredguard fix --prefix ANON`
        THEN the command succeeds because ANON-* doesn't collide
        """
        data_file = project / "data.txt"
        data_file.write_text("SUB-1234 and REDACTED-0 from before\n")

        cli.run("fix", "--prefix", "ANON", "data.txt")

        content = data_file.read_text()
        assert "ANON-0" in content
        assert "REDACTED-0" in content  # Unchanged


# =============================================================================
# PATTERN FILE SCOPING
# =============================================================================

class TestPatternFileScoping:
    """
    Patterns can be scoped to specific file types using `files` and
    `exclude_files` glob patterns in the configuration.
    """

    def test_pattern_only_applies_to_specified_files(self, cli: CLIRunner, project: Path):
        """
        GIVEN a pattern configured to only match *.csv files
        WHEN running check on both .csv and .txt files
        THEN only the .csv file triggers a match
        """
        (project / "pyproject.toml").write_text(dedent("""
            [tool.shredguard]
            [[tool.shredguard.patterns]]
            regex = "SUB-\\\\d{4}"
            description = "Subject ID"
            files = ["*.csv"]
        """).strip())

        (project / "data.csv").write_text("SUB-1234\n")
        (project / "data.txt").write_text("SUB-1234\n")

        result = cli.run("check", ".", expect_fail=True)

        result.assert_contains("data.csv")
        result.assert_not_contains("data.txt")

    def test_exclude_files_pattern(self, cli: CLIRunner, project: Path):
        """
        GIVEN a pattern that excludes *_test.* files
        WHEN running check on both regular and test files
        THEN test files are not scanned for that pattern
        """
        (project / "pyproject.toml").write_text(dedent("""
            [tool.shredguard]
            [[tool.shredguard.patterns]]
            regex = "SUB-\\\\d{4}"
            description = "Subject ID"
            exclude_files = ["*_test.*"]
        """).strip())

        (project / "data.txt").write_text("SUB-1234\n")
        (project / "data_test.txt").write_text("SUB-5678\n")

        result = cli.run("check", ".", expect_fail=True)

        result.assert_contains("SUB-1234")
        result.assert_not_contains("SUB-5678")


# =============================================================================
# ERROR HANDLING
# =============================================================================

class TestErrorHandling:
    """
    ShredGuard provides clear error messages for common issues.
    """

    def test_missing_config(self, tmp_path: Path):
        """
        GIVEN a directory with no pyproject.toml
        WHEN running any shredguard command
        THEN a helpful error message is shown with example config
        """
        cli = CLIRunner(tmp_path)
        (tmp_path / "data.txt").write_text("SUB-1234\n")

        result = cli.run("check", "data.txt", expect_fail=True)

        result.assert_contains("No shredguard configuration found")
        result.assert_contains("[tool.shredguard]")

    def test_invalid_regex_in_config(self, tmp_path: Path):
        """
        GIVEN a config with an invalid regex pattern
        WHEN running any shredguard command
        THEN a clear error identifies the problematic pattern
        """
        (tmp_path / "pyproject.toml").write_text(dedent("""
            [tool.shredguard]
            [[tool.shredguard.patterns]]
            regex = "[invalid"
            description = "Bad pattern"
        """).strip())

        cli = CLIRunner(tmp_path)
        (tmp_path / "data.txt").write_text("test\n")

        result = cli.run("check", "data.txt", expect_fail=True)

        result.assert_contains("Invalid regex")

    def test_nonexistent_file(self, cli: CLIRunner, project: Path):
        """
        GIVEN a file path that doesn't exist
        WHEN running shredguard check
        THEN an error is shown
        """
        result = cli.run("check", "nonexistent.txt", expect_fail=True)

        # Click handles this with its own error message
        result.assert_contains("does not exist")
