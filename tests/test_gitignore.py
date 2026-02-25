"""Tests for shredguard.gitignore module."""

import pytest
from pathlib import Path

from shredguard.gitignore import (
    find_gitignore_files,
    load_gitignore_spec,
    GitignoreFilter,
)


class TestFindGitignoreFiles:
    """Tests for find_gitignore_files function."""

    def test_finds_root_gitignore(self, tmp_path: Path):
        """Test finding .gitignore in root directory."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n")

        result = find_gitignore_files(tmp_path)
        assert gitignore in result

    def test_finds_nested_gitignores(self, tmp_path: Path):
        """Test finding .gitignore files in subdirectories."""
        root_gitignore = tmp_path / ".gitignore"
        root_gitignore.write_text("*.pyc\n")

        subdir = tmp_path / "subdir"
        subdir.mkdir()
        sub_gitignore = subdir / ".gitignore"
        sub_gitignore.write_text("local.txt\n")

        result = find_gitignore_files(tmp_path)
        assert root_gitignore in result
        assert sub_gitignore in result

    def test_no_gitignore(self, tmp_path: Path):
        """Test when no .gitignore exists."""
        result = find_gitignore_files(tmp_path)
        # May find parent .gitignore files but not in tmp_path
        for path in result:
            assert tmp_path not in path.parents or path.parent == tmp_path.parent


class TestLoadGitignoreSpec:
    """Tests for load_gitignore_spec function."""

    def test_loads_patterns(self, tmp_path: Path):
        """Test loading patterns from .gitignore."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n__pycache__/\n.env\n")

        spec = load_gitignore_spec(gitignore)

        assert spec.match_file("test.pyc")
        assert spec.match_file("__pycache__/")
        assert spec.match_file(".env")
        assert not spec.match_file("test.py")

    def test_ignores_comments(self, tmp_path: Path):
        """Test that comments are ignored."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("# This is a comment\n*.pyc\n")

        spec = load_gitignore_spec(gitignore)

        assert spec.match_file("test.pyc")
        assert not spec.match_file("# This is a comment")


class TestGitignoreFilter:
    """Tests for GitignoreFilter class."""

    def test_respects_gitignore(self, tmp_path: Path):
        """Test that filter respects .gitignore patterns."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n__pycache__/\n")

        # Create test files
        py_file = tmp_path / "test.py"
        py_file.write_text("print('hello')")
        pyc_file = tmp_path / "test.pyc"
        pyc_file.write_text("bytecode")

        filter = GitignoreFilter(tmp_path, respect_gitignore=True)

        assert not filter.is_ignored(py_file)
        assert filter.is_ignored(pyc_file)

    def test_no_gitignore_flag(self, tmp_path: Path):
        """Test that --no-gitignore disables filtering."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n")

        pyc_file = tmp_path / "test.pyc"
        pyc_file.write_text("bytecode")

        filter = GitignoreFilter(tmp_path, respect_gitignore=False)

        assert not filter.is_ignored(pyc_file)

    def test_filter_paths(self, tmp_path: Path):
        """Test filtering a list of paths."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n*.log\n")

        py_file = tmp_path / "test.py"
        py_file.write_text("")
        pyc_file = tmp_path / "test.pyc"
        pyc_file.write_text("")
        log_file = tmp_path / "debug.log"
        log_file.write_text("")

        filter = GitignoreFilter(tmp_path, respect_gitignore=True)
        paths = [py_file, pyc_file, log_file]

        result = filter.filter_paths(paths)
        assert py_file in result
        assert pyc_file not in result
        assert log_file not in result

    def test_nested_gitignore(self, tmp_path: Path):
        """Test that nested .gitignore files are respected."""
        # Root ignores *.log
        root_gitignore = tmp_path / ".gitignore"
        root_gitignore.write_text("*.log\n")

        # Subdir ignores local.txt
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        sub_gitignore = subdir / ".gitignore"
        sub_gitignore.write_text("local.txt\n")

        # Create files
        root_log = tmp_path / "root.log"
        root_log.write_text("")
        sub_log = subdir / "sub.log"
        sub_log.write_text("")
        sub_local = subdir / "local.txt"
        sub_local.write_text("")
        sub_other = subdir / "other.txt"
        sub_other.write_text("")

        filter = GitignoreFilter(tmp_path, respect_gitignore=True)

        assert filter.is_ignored(root_log)
        assert filter.is_ignored(sub_log)
        assert filter.is_ignored(sub_local)
        assert not filter.is_ignored(sub_other)

    def test_directory_patterns(self, tmp_path: Path):
        """Test matching directory patterns."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("build/\n")

        build_dir = tmp_path / "build"
        build_dir.mkdir()
        build_file = build_dir / "output.txt"
        build_file.write_text("")

        filter = GitignoreFilter(tmp_path, respect_gitignore=True)

        # The file inside build/ should be ignored
        assert filter.is_ignored(build_file)
