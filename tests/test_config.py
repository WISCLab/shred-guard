"""Tests for shredguard.config module."""

import pytest
from pathlib import Path

from shredguard.config import Config, ConfigError, Pattern


class TestPattern:
    """Tests for Pattern class."""

    def test_from_dict_valid(self):
        """Test creating a pattern from a valid dictionary."""
        data = {
            "regex": r"SUB-\d{4}",
            "description": "Subject ID",
            "files": ["*.txt"],
            "exclude_files": ["*_test.txt"],
        }
        pattern = Pattern.from_dict(data, 0)

        assert pattern.regex == r"SUB-\d{4}"
        assert pattern.description == "Subject ID"
        assert pattern.code == "SG001"
        assert pattern.files == ["*.txt"]
        assert pattern.exclude_files == ["*_test.txt"]
        assert pattern.compiled.pattern == r"SUB-\d{4}"

    def test_from_dict_minimal(self):
        """Test creating a pattern with only required fields."""
        data = {"regex": r"\d{3}-\d{2}-\d{4}"}
        pattern = Pattern.from_dict(data, 2)

        assert pattern.regex == r"\d{3}-\d{2}-\d{4}"
        assert pattern.description == "Pattern 3"  # Default description
        assert pattern.code == "SG003"
        assert pattern.files == []
        assert pattern.exclude_files == []

    def test_from_dict_missing_regex(self):
        """Test that missing regex raises ConfigError."""
        data = {"description": "No regex"}
        with pytest.raises(ConfigError, match="missing 'regex' field"):
            Pattern.from_dict(data, 0)

    def test_from_dict_invalid_regex(self):
        """Test that invalid regex raises ConfigError."""
        data = {"regex": r"[invalid", "description": "Bad regex"}
        with pytest.raises(ConfigError, match="Invalid regex"):
            Pattern.from_dict(data, 0)

    def test_from_dict_single_file_glob(self):
        """Test that single file glob is converted to list."""
        data = {"regex": r"test", "files": "*.txt"}
        pattern = Pattern.from_dict(data, 0)
        assert pattern.files == ["*.txt"]


class TestConfig:
    """Tests for Config class."""

    def test_load_from_file(self, tmp_path: Path):
        """Test loading config from a pyproject.toml file."""
        config_file = tmp_path / "pyproject.toml"
        config_file.write_text("""
[tool.shredguard]
[[tool.shredguard.patterns]]
regex = "SUB-\\\\d{4}"
description = "Subject ID"

[[tool.shredguard.patterns]]
regex = "MRN\\\\d{6}"
description = "MRN"
""")
        config = Config.load(config_file)

        assert len(config.patterns) == 2
        assert config.patterns[0].code == "SG001"
        assert config.patterns[1].code == "SG002"
        assert config.config_path == config_file

    def test_load_missing_file(self, tmp_path: Path):
        """Test that missing config file raises ConfigError."""
        with pytest.raises(ConfigError, match="not found"):
            Config.load(tmp_path / "nonexistent.toml")

    def test_load_no_shredguard_section(self, tmp_path: Path):
        """Test that missing [tool.shredguard] section raises ConfigError."""
        config_file = tmp_path / "pyproject.toml"
        config_file.write_text("""
[tool.other]
key = "value"
""")
        with pytest.raises(ConfigError, match="No \\[tool.shredguard\\] section"):
            Config.load(config_file)

    def test_load_no_patterns(self, tmp_path: Path):
        """Test that empty patterns list raises ConfigError."""
        config_file = tmp_path / "pyproject.toml"
        config_file.write_text("""
[tool.shredguard]
# No patterns defined
""")
        with pytest.raises(ConfigError, match="No patterns defined"):
            Config.load(config_file)

    def test_load_invalid_toml(self, tmp_path: Path):
        """Test that invalid TOML raises ConfigError."""
        config_file = tmp_path / "pyproject.toml"
        config_file.write_text("invalid toml [[[")
        with pytest.raises(ConfigError, match="Invalid TOML"):
            Config.load(config_file)

    def test_load_searches_parent_directories(self, tmp_path: Path):
        """Test that config loading searches parent directories."""
        # Create config in parent directory
        config_file = tmp_path / "pyproject.toml"
        config_file.write_text("""
[tool.shredguard]
[[tool.shredguard.patterns]]
regex = "TEST-\\\\d+"
description = "Test"
""")

        # Create subdirectory
        subdir = tmp_path / "sub" / "dir"
        subdir.mkdir(parents=True)

        # Change to subdirectory and load (simulated by using the subdir's parent search)
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(subdir)
            config = Config.load()
            assert len(config.patterns) == 1
        finally:
            os.chdir(original_cwd)

    def test_load_no_config_found(self, tmp_path: Path, monkeypatch):
        """Test helpful error when no config is found."""
        # Create an empty directory with no config
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        monkeypatch.chdir(empty_dir)

        with pytest.raises(ConfigError, match="No shredguard configuration found"):
            Config.load()
