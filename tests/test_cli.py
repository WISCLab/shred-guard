"""Tests for shredguard.cli module."""

import json
import pytest
from pathlib import Path
from click.testing import CliRunner

from shredguard.cli import main


@pytest.fixture
def runner():
    """Create a CLI runner."""
    return CliRunner()


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    """Create a test configuration file."""
    config = tmp_path / "pyproject.toml"
    config.write_text("""
[tool.shredguard]
[[tool.shredguard.patterns]]
regex = "SUB-\\\\d{4}"
description = "Subject ID"

[[tool.shredguard.patterns]]
regex = "MRN\\\\d{6}"
description = "Medical Record Number"
""")
    return config


class TestCheckCommand:
    """Tests for the check command."""

    def test_no_matches_success(self, runner: CliRunner, tmp_path: Path, config_file: Path):
        """Test that check succeeds with no matches."""
        test_file = tmp_path / "clean.txt"
        test_file.write_text("No PHI here\n")

        result = runner.invoke(main, ["check", "--config", str(config_file), str(test_file)])

        assert result.exit_code == 0
        assert "No PHI patterns found" in result.output

    def test_matches_found_failure(self, runner: CliRunner, tmp_path: Path, config_file: Path):
        """Test that check fails when matches are found."""
        test_file = tmp_path / "phi.txt"
        test_file.write_text("Subject SUB-1234 enrolled\n")

        result = runner.invoke(main, ["check", "--config", str(config_file), str(test_file)])

        assert result.exit_code == 1
        assert "SUB-1234" in result.output
        assert "SG001" in result.output
        assert "Found 1 match" in result.output

    def test_multiple_matches(self, runner: CliRunner, tmp_path: Path, config_file: Path):
        """Test output with multiple matches."""
        test_file = tmp_path / "phi.txt"
        test_file.write_text("SUB-1234 and MRN123456\n")

        result = runner.invoke(main, ["check", "--config", str(config_file), str(test_file)])

        assert result.exit_code == 1
        assert "SUB-1234" in result.output
        assert "MRN123456" in result.output
        assert "Found 2 matches" in result.output

    def test_config_not_found(self, runner: CliRunner, tmp_path: Path):
        """Test error when config is not found."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test\n")

        # Run in isolated directory with no config
        with runner.isolated_filesystem():
            Path("test.txt").write_text("test\n")
            result = runner.invoke(main, ["check", "test.txt"])

        assert result.exit_code == 1
        assert "No shredguard configuration found" in result.output

    def test_verbose_shows_binary_skips(self, runner: CliRunner, tmp_path: Path, config_file: Path):
        """Test that --verbose shows skipped binary files."""
        binary_file = tmp_path / "test.bin"
        binary_file.write_bytes(b"\x00binary")

        result = runner.invoke(
            main, ["check", "--config", str(config_file), "--verbose", str(binary_file)]
        )

        assert "binary file" in result.output.lower() or "skip" in result.output.lower()

    def test_respects_gitignore(self, runner: CliRunner, tmp_path: Path, config_file: Path):
        """Test that .gitignore is respected by default."""
        # Create .gitignore
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("ignored.txt\n")

        # Create files
        ignored_file = tmp_path / "ignored.txt"
        ignored_file.write_text("SUB-1234\n")

        scanned_file = tmp_path / "scanned.txt"
        scanned_file.write_text("Clean file\n")

        result = runner.invoke(main, ["check", "--config", str(config_file), str(tmp_path)])

        # Should not find the match in ignored file
        assert "SUB-1234" not in result.output

    def test_no_gitignore_flag(self, runner: CliRunner, tmp_path: Path, config_file: Path):
        """Test that --no-gitignore disables gitignore."""
        # Create .gitignore
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("ignored.txt\n")

        # Create file that would be ignored
        ignored_file = tmp_path / "ignored.txt"
        ignored_file.write_text("SUB-1234\n")

        result = runner.invoke(
            main, ["check", "--config", str(config_file), "--no-gitignore", str(tmp_path)]
        )

        # Should find the match now
        assert result.exit_code == 1
        assert "SUB-1234" in result.output

    def test_ruff_style_output(self, runner: CliRunner, tmp_path: Path, config_file: Path):
        """Test that output is in ruff style format."""
        test_file = tmp_path / "phi.txt"
        test_file.write_text("SUB-1234\n")

        result = runner.invoke(main, ["check", "--config", str(config_file), str(test_file)])

        # Should have file:line:col format
        assert ":1:1:" in result.output or "phi.txt:1:1" in result.output


class TestFixCommand:
    """Tests for the fix command."""

    def test_basic_fix(self, runner: CliRunner, tmp_path: Path, config_file: Path):
        """Test basic fix operation."""
        test_file = tmp_path / "phi.txt"
        test_file.write_text("Subject SUB-1234 enrolled\n")

        result = runner.invoke(
            main, ["fix", "--config", str(config_file), "--prefix", "ID", str(test_file)]
        )

        assert result.exit_code == 0
        assert "Replaced" in result.output
        assert test_file.read_text() == "Subject ID-0 enrolled\n"

    def test_fix_no_matches(self, runner: CliRunner, tmp_path: Path, config_file: Path):
        """Test fix when no matches exist."""
        test_file = tmp_path / "clean.txt"
        test_file.write_text("No PHI here\n")

        result = runner.invoke(
            main, ["fix", "--config", str(config_file), str(test_file)]
        )

        assert result.exit_code == 0
        assert "No replacements needed" in result.output

    def test_fix_with_output_map(self, runner: CliRunner, tmp_path: Path, config_file: Path):
        """Test fix with --output-map flag."""
        test_file = tmp_path / "phi.txt"
        test_file.write_text("SUB-1234\n")

        mapping_file = tmp_path / "mapping.json"

        result = runner.invoke(
            main,
            [
                "fix",
                "--config", str(config_file),
                "--prefix", "ID",
                "--output-map", str(mapping_file),
                str(test_file),
            ],
        )

        assert result.exit_code == 0
        assert mapping_file.exists()

        mapping = json.loads(mapping_file.read_text())
        assert mapping == {"SUB-1234": "ID-0"}

    def test_fix_default_prefix(self, runner: CliRunner, tmp_path: Path, config_file: Path):
        """Test that default prefix is REDACTED."""
        test_file = tmp_path / "phi.txt"
        test_file.write_text("SUB-1234\n")

        result = runner.invoke(
            main, ["fix", "--config", str(config_file), str(test_file)]
        )

        assert result.exit_code == 0
        assert test_file.read_text() == "REDACTED-0\n"

    def test_fix_prefix_collision(self, runner: CliRunner, tmp_path: Path, config_file: Path):
        """Test that prefix collision is detected."""
        test_file = tmp_path / "phi.txt"
        test_file.write_text("SUB-1234 and REDACTED-0 already\n")

        result = runner.invoke(
            main, ["fix", "--config", str(config_file), str(test_file)]
        )

        assert result.exit_code == 1
        assert "already exists" in result.output.lower() or "collision" in result.output.lower()

    def test_fix_multiple_files(self, runner: CliRunner, tmp_path: Path, config_file: Path):
        """Test fixing multiple files."""
        file1 = tmp_path / "file1.txt"
        file1.write_text("SUB-1234\n")

        file2 = tmp_path / "file2.txt"
        file2.write_text("SUB-5678\n")

        result = runner.invoke(
            main,
            ["fix", "--config", str(config_file), "--prefix", "ID", str(file1), str(file2)],
        )

        assert result.exit_code == 0
        assert "2 files" in result.output


class TestVersionFlag:
    """Tests for --version flag."""

    def test_version(self, runner: CliRunner):
        """Test that --version shows version."""
        result = runner.invoke(main, ["--version"])

        assert result.exit_code == 0
        assert "shredguard" in result.output.lower()
        assert "0.1.0" in result.output


class TestHelpFlag:
    """Tests for --help flag."""

    def test_main_help(self, runner: CliRunner):
        """Test main --help."""
        result = runner.invoke(main, ["--help"])

        assert result.exit_code == 0
        assert "check" in result.output
        assert "fix" in result.output

    def test_check_help(self, runner: CliRunner):
        """Test check --help."""
        result = runner.invoke(main, ["check", "--help"])

        assert result.exit_code == 0
        assert "--config" in result.output
        assert "--verbose" in result.output
        assert "--no-gitignore" in result.output

    def test_fix_help(self, runner: CliRunner):
        """Test fix --help."""
        result = runner.invoke(main, ["fix", "--help"])

        assert result.exit_code == 0
        assert "--prefix" in result.output
        assert "--output-map" in result.output
