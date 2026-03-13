"""Tests for shredguard.git module."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from shredguard.git import (
    get_commits_for_branch,
    get_dirty_relevant_files,
    get_file_content,
    get_local_branches,
    get_tracked_files,
    is_path_in_repo,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _current_branch(repo: Path) -> str:
    """Return the current branch name regardless of git version."""
    name = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo)
    return name or "main"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Minimal git repo with one committed file."""
    _git("init", cwd=tmp_path)
    _git("config", "user.email", "test@test.com", cwd=tmp_path)
    _git("config", "user.name", "Test", cwd=tmp_path)
    (tmp_path / "file.txt").write_text("hello\n")
    _git("add", ".", cwd=tmp_path)
    _git("commit", "-m", "Initial commit", cwd=tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# is_path_in_repo
# ---------------------------------------------------------------------------


class TestIsPathInRepo:
    def test_nested_path_inside_repo(self, tmp_path: Path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        nested = repo_root / "src" / "foo.py"
        assert is_path_in_repo(nested, repo_root)

    def test_path_outside_repo(self, tmp_path: Path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        outside = tmp_path / "other" / "file.py"
        assert not is_path_in_repo(outside, repo_root)

    def test_repo_root_itself_is_inside(self, tmp_path: Path):
        assert is_path_in_repo(tmp_path, tmp_path)

    def test_sibling_directory_is_outside(self, tmp_path: Path):
        repo_root = tmp_path / "my-repo"
        repo_root.mkdir()
        sibling = tmp_path / "my-repo-extra" / "file.py"
        assert not is_path_in_repo(sibling, repo_root)


# ---------------------------------------------------------------------------
# get_dirty_relevant_files
# ---------------------------------------------------------------------------


class TestGetDirtyRelevantFiles:
    def test_clean_repo_returns_empty(self, repo: Path):
        config = repo / "pyproject.toml"
        config.write_text("[tool.shredguard]\n")
        _git("add", "pyproject.toml", cwd=repo)
        _git("commit", "-m", "Add config", cwd=repo)

        assert get_dirty_relevant_files(config, repo) == []

    def test_detects_unstaged_config_modification(self, repo: Path):
        config = repo / "pyproject.toml"
        config.write_text("[tool.shredguard]\n")
        _git("add", "pyproject.toml", cwd=repo)
        _git("commit", "-m", "Add config", cwd=repo)

        config.write_text("[tool.shredguard]\n# modified\n")

        dirty = get_dirty_relevant_files(config, repo)
        assert any(p.name == "pyproject.toml" for p in dirty)

    def test_detects_staged_config_modification(self, repo: Path):
        config = repo / "pyproject.toml"
        config.write_text("[tool.shredguard]\n")
        _git("add", "pyproject.toml", cwd=repo)
        _git("commit", "-m", "Add config", cwd=repo)

        config.write_text("[tool.shredguard]\n# staged\n")
        _git("add", "pyproject.toml", cwd=repo)

        dirty = get_dirty_relevant_files(config, repo)
        assert any(p.name == "pyproject.toml" for p in dirty)

    def test_detects_new_untracked_config(self, repo: Path):
        config = repo / "pyproject.toml"
        config.write_text("[tool.shredguard]\n")
        # NOT committed — untracked

        dirty = get_dirty_relevant_files(config, repo)
        assert any(p.name == "pyproject.toml" for p in dirty)

    def test_detects_unstaged_gitignore_modification(self, repo: Path):
        gitignore = repo / ".gitignore"
        gitignore.write_text("*.pyc\n")
        _git("add", ".gitignore", cwd=repo)
        _git("commit", "-m", "Add gitignore", cwd=repo)

        gitignore.write_text("*.pyc\n*.log\n")

        config = repo / "pyproject.toml"
        dirty = get_dirty_relevant_files(config, repo)
        assert any(p.name == ".gitignore" for p in dirty)

    def test_detects_new_untracked_gitignore(self, repo: Path):
        (repo / ".gitignore").write_text("*.pyc\n")
        config = repo / "pyproject.toml"

        dirty = get_dirty_relevant_files(config, repo)
        assert any(p.name == ".gitignore" for p in dirty)

    def test_ignores_other_modified_files(self, repo: Path):
        config = repo / "pyproject.toml"
        config.write_text("[tool.shredguard]\n")
        _git("add", "pyproject.toml", cwd=repo)
        _git("commit", "-m", "Add config", cwd=repo)

        # Modify a non-config, non-gitignore file
        (repo / "file.txt").write_text("changed\n")

        assert get_dirty_relevant_files(config, repo) == []


# ---------------------------------------------------------------------------
# get_local_branches
# ---------------------------------------------------------------------------


class TestGetLocalBranches:
    def test_returns_at_least_one_branch(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.chdir(repo)
        branches = get_local_branches()
        assert len(branches) >= 1

    def test_returns_all_local_branches(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.chdir(repo)
        _git("branch", "feature", cwd=repo)
        _git("branch", "hotfix", cwd=repo)

        branches = get_local_branches()
        assert any("feature" in b for b in branches)
        assert any("hotfix" in b for b in branches)

    def test_does_not_include_remote_branches(
        self, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Create a second repo to act as a remote, then fetch so remote-tracking
        # refs (origin/main) actually exist in the local repo's .git/refs/remotes.
        remote = tmp_path / "remote"
        remote.mkdir()
        _git("init", "--bare", cwd=remote)
        _git("remote", "add", "origin", str(remote), cwd=repo)
        _git("push", "origin", "HEAD", cwd=repo)
        _git("fetch", "origin", cwd=repo)

        monkeypatch.chdir(repo)
        branches = get_local_branches()
        assert not any(b.startswith("origin/") for b in branches)


# ---------------------------------------------------------------------------
# get_commits_for_branch
# ---------------------------------------------------------------------------


class TestGetCommitsForBranch:
    def test_returns_commit_sha_and_subject(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.chdir(repo)
        branch = _current_branch(repo)
        commits = get_commits_for_branch(branch)

        assert len(commits) >= 1
        sha, subject = commits[-1]  # oldest (initial) commit
        assert len(sha) == 40
        assert subject == "Initial commit"

    def test_ordered_newest_first(self, repo: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(repo)
        (repo / "new.txt").write_text("new\n")
        _git("add", "new.txt", cwd=repo)
        _git("commit", "-m", "Second commit", cwd=repo)

        branch = _current_branch(repo)
        commits = get_commits_for_branch(branch)

        assert commits[0][1] == "Second commit"
        assert commits[1][1] == "Initial commit"

    def test_sha_matches_git_log(self, repo: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(repo)
        head_sha = _git("rev-parse", "HEAD", cwd=repo)
        branch = _current_branch(repo)
        commits = get_commits_for_branch(branch)

        assert commits[0][0] == head_sha


# ---------------------------------------------------------------------------
# get_tracked_files
# ---------------------------------------------------------------------------


class TestGetTrackedFiles:
    def test_returns_committed_files(self, repo: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(repo)
        sha = _git("rev-parse", "HEAD", cwd=repo)

        files = get_tracked_files(sha)
        assert "file.txt" in files

    def test_does_not_return_untracked_files(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.chdir(repo)
        (repo / "untracked.txt").write_text("not committed\n")
        sha = _git("rev-parse", "HEAD", cwd=repo)

        files = get_tracked_files(sha)
        assert "untracked.txt" not in files

    def test_reflects_files_at_that_commit(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A file added after a commit is not in that commit's tree."""
        monkeypatch.chdir(repo)
        old_sha = _git("rev-parse", "HEAD", cwd=repo)

        (repo / "later.txt").write_text("added later\n")
        _git("add", "later.txt", cwd=repo)
        _git("commit", "-m", "Add later", cwd=repo)

        old_files = get_tracked_files(old_sha)
        assert "later.txt" not in old_files


# ---------------------------------------------------------------------------
# get_file_content
# ---------------------------------------------------------------------------


class TestGetFileContent:
    def test_returns_file_bytes(self, repo: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(repo)
        sha = _git("rev-parse", "HEAD", cwd=repo)

        content = get_file_content(sha, "file.txt")
        assert content is not None
        assert b"hello" in content

    def test_returns_none_for_nonexistent_path(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.chdir(repo)
        sha = _git("rev-parse", "HEAD", cwd=repo)

        assert get_file_content(sha, "does-not-exist.txt") is None

    def test_returns_correct_historical_content(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Content from an old commit differs from the current version."""
        monkeypatch.chdir(repo)
        old_sha = _git("rev-parse", "HEAD", cwd=repo)

        (repo / "file.txt").write_text("updated content\n")
        _git("add", "file.txt", cwd=repo)
        _git("commit", "-m", "Update file", cwd=repo)

        old_content = get_file_content(old_sha, "file.txt")
        assert old_content is not None
        assert b"hello" in old_content
        assert b"updated" not in old_content
