"""Tests for the shredguard audit command."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _run_audit(
    *args: str, cwd: Path, stdin: str | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "shredguard", "audit", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        input=stdin,
    )


_CONFIG = (
    "[tool.shredguard]\n"
    "[[tool.shredguard.patterns]]\n"
    'regex = "SUB-\\\\d{4,6}"\n'
    'description = "Subject ID"\n'
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """
    Minimal git repo at tmp_path/repo with one clean committed file.
    tmp_path itself is available for external files (e.g. configs outside the repo).
    """
    r = tmp_path / "repo"
    r.mkdir()
    _git("init", cwd=r)
    _git("config", "user.email", "test@test.com", cwd=r)
    _git("config", "user.name", "Test", cwd=r)
    (r / "pyproject.toml").write_text(_CONFIG)
    (r / "clean.txt").write_text("no PHI here\n")
    _git("add", ".", cwd=r)
    _git("commit", "-m", "Initial commit", cwd=r)
    return r


# ---------------------------------------------------------------------------
# Dirty-state pre-flight check
# ---------------------------------------------------------------------------


class TestAuditDirtyCheck:
    """Audit must be rejected whenever config or .gitignore have uncommitted changes."""

    def test_modified_config_is_blocked(self, repo: Path, tmp_path: Path):
        """
        GIVEN pyproject.toml has an unstaged modification
        WHEN running audit
        THEN it exits 1 and reports the dirty file without writing JSON
        """
        (repo / "pyproject.toml").write_text(_CONFIG + "\n# dirty\n")
        output = tmp_path / "audit.json"

        result = _run_audit("--output", str(output), cwd=repo)

        assert result.returncode == 1
        combined = result.stdout + result.stderr
        assert "Uncommitted changes" in combined
        assert "pyproject.toml" in combined
        assert not output.exists()

    def test_staged_config_modification_is_blocked(self, repo: Path, tmp_path: Path):
        """
        GIVEN pyproject.toml has a staged (not yet committed) modification
        WHEN running audit
        THEN it is still blocked
        """
        (repo / "pyproject.toml").write_text(_CONFIG + "\n# staged\n")
        _git("add", "pyproject.toml", cwd=repo)
        output = tmp_path / "audit.json"

        result = _run_audit("--output", str(output), cwd=repo)

        assert result.returncode == 1
        assert "Uncommitted changes" in result.stdout + result.stderr

    def test_new_untracked_config_is_blocked(self, repo: Path, tmp_path: Path):
        """
        GIVEN the config file exists on disk but has never been committed
        WHEN running audit
        THEN it is blocked (untracked = dirty for audit purposes)
        """
        # Remove config from git history, leave it untracked
        _git("rm", "pyproject.toml", cwd=repo)
        _git("commit", "-m", "Remove config", cwd=repo)
        (repo / "pyproject.toml").write_text(_CONFIG)  # untracked
        output = tmp_path / "audit.json"

        result = _run_audit("--output", str(output), cwd=repo)

        assert result.returncode == 1
        assert "Uncommitted changes" in result.stdout + result.stderr

    def test_modified_gitignore_is_blocked(self, repo: Path, tmp_path: Path):
        """
        GIVEN .gitignore has an unstaged modification
        WHEN running audit
        THEN it is blocked and .gitignore is named in the error
        """
        gitignore = repo / ".gitignore"
        gitignore.write_text("*.pyc\n")
        _git("add", ".gitignore", cwd=repo)
        _git("commit", "-m", "Add gitignore", cwd=repo)

        gitignore.write_text("*.pyc\n*.log\n")
        output = tmp_path / "audit.json"

        result = _run_audit("--output", str(output), cwd=repo)

        assert result.returncode == 1
        combined = result.stdout + result.stderr
        assert "Uncommitted changes" in combined
        assert ".gitignore" in combined

    def test_new_untracked_gitignore_is_blocked(self, repo: Path, tmp_path: Path):
        """
        GIVEN a .gitignore file exists on disk but has not been committed
        WHEN running audit
        THEN it is blocked
        """
        (repo / ".gitignore").write_text("*.pyc\n")
        output = tmp_path / "audit.json"

        result = _run_audit("--output", str(output), cwd=repo)

        assert result.returncode == 1
        assert "Uncommitted changes" in result.stdout + result.stderr

    def test_other_modified_files_do_not_block(self, repo: Path, tmp_path: Path):
        """
        GIVEN a non-config, non-gitignore file has uncommitted changes
        WHEN running audit
        THEN the audit proceeds normally
        """
        (repo / "clean.txt").write_text("changed but irrelevant\n")
        output = tmp_path / "audit.json"

        result = _run_audit("--output", str(output), cwd=repo)

        assert result.returncode == 0
        assert "Uncommitted changes" not in result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Config outside the repository
# ---------------------------------------------------------------------------


class TestAuditConfigOutsideRepo:
    """When --config points outside the repo the user must confirm and the JSON notes it."""

    @pytest.fixture
    def external_config(self, tmp_path: Path) -> Path:
        cfg = tmp_path / "external.toml"
        cfg.write_text(_CONFIG)
        return cfg

    def test_warns_user_about_untracked_config(
        self, repo: Path, external_config: Path, tmp_path: Path
    ):
        """
        GIVEN --config points outside the repository
        WHEN the user answers 'y'
        THEN a warning is shown before proceeding
        """
        output = tmp_path / "audit.json"
        result = _run_audit(
            "--config",
            str(external_config),
            "--output",
            str(output),
            cwd=repo,
            stdin="y\n",
        )

        combined = result.stdout + result.stderr
        assert "outside the repository" in combined or "not tracked" in combined.lower()

    def test_proceeds_and_marks_config_untracked_in_json(
        self, repo: Path, external_config: Path, tmp_path: Path
    ):
        """
        GIVEN --config is outside the repo and user confirms
        WHEN audit completes
        THEN JSON records config.tracked = false
        """
        output = tmp_path / "audit.json"
        _run_audit(
            "--config",
            str(external_config),
            "--output",
            str(output),
            cwd=repo,
            stdin="y\n",
        )

        assert output.exists()
        data = json.loads(output.read_text())
        assert data["config"]["tracked"] is False

    def test_cancels_on_no_and_writes_no_json(
        self, repo: Path, external_config: Path, tmp_path: Path
    ):
        """
        GIVEN --config is outside the repo and user answers 'n'
        WHEN audit is cancelled
        THEN exit code is 0, JSON is not written, and output says cancelled
        """
        output = tmp_path / "audit.json"
        result = _run_audit(
            "--config",
            str(external_config),
            "--output",
            str(output),
            cwd=repo,
            stdin="n\n",
        )

        assert result.returncode == 0
        assert not output.exists()
        assert "cancelled" in (result.stdout + result.stderr).lower()


# ---------------------------------------------------------------------------
# Progress output format
# ---------------------------------------------------------------------------


class TestAuditProgress:
    """Audit prints numbered progress for every commit."""

    def test_numbered_counter_format(self, repo: Path, tmp_path: Path):
        """
        GIVEN a repo with one commit
        WHEN running audit
        THEN output contains [1/1] counter
        """
        result = _run_audit("--output", str(tmp_path / "a.json"), cwd=repo)
        assert "[1/1]" in result.stdout

    def test_commit_subject_appears_in_progress(self, repo: Path, tmp_path: Path):
        result = _run_audit("--output", str(tmp_path / "a.json"), cwd=repo)
        assert "Initial commit" in result.stdout

    def test_clean_commit_shows_check_mark(self, repo: Path, tmp_path: Path):
        result = _run_audit("--output", str(tmp_path / "a.json"), cwd=repo)
        assert result.returncode == 0
        # Either Unicode ✓ or ASCII [OK]
        assert "\u2713" in result.stdout or "[OK]" in result.stdout

    def test_commit_with_phi_shows_x_and_match_details(
        self, repo: Path, tmp_path: Path
    ):
        """
        GIVEN a commit containing PHI
        WHEN running audit
        THEN that commit line shows ✗/[X] and match details are indented below it
        """
        (repo / "phi.txt").write_text("Patient SUB-1234 enrolled\n")
        _git("add", "phi.txt", cwd=repo)
        _git("commit", "-m", "Add PHI file", cwd=repo)

        result = _run_audit("--output", str(tmp_path / "a.json"), cwd=repo)

        assert result.returncode == 1
        assert "\u2717" in result.stdout or "[X]" in result.stdout
        assert "SUB-1234" in result.stdout
        assert "SG001" in result.stdout

    def test_multiple_commits_numbered_sequentially(self, repo: Path, tmp_path: Path):
        (repo / "second.txt").write_text("second\n")
        _git("add", "second.txt", cwd=repo)
        _git("commit", "-m", "Second commit", cwd=repo)

        result = _run_audit("--output", str(tmp_path / "a.json"), cwd=repo)

        assert "[1/2]" in result.stdout
        assert "[2/2]" in result.stdout

    def test_summary_section_is_shown(self, repo: Path, tmp_path: Path):
        result = _run_audit("--output", str(tmp_path / "a.json"), cwd=repo)
        assert "Audit Summary" in result.stdout
        assert "Anchor commit" in result.stdout
        assert "Commits" in result.stdout


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


class TestAuditJsonOutput:
    """The JSON file is the authoritative, reproducible audit record."""

    def test_json_always_written_on_success(self, repo: Path, tmp_path: Path):
        output = tmp_path / "audit.json"
        result = _run_audit("--output", str(output), cwd=repo)
        assert result.returncode == 0
        assert output.exists()

    def test_json_always_written_when_matches_found(self, repo: Path, tmp_path: Path):
        (repo / "phi.txt").write_text("SUB-1234\n")
        _git("add", "phi.txt", cwd=repo)
        _git("commit", "-m", "PHI commit", cwd=repo)

        output = tmp_path / "audit.json"
        result = _run_audit("--output", str(output), cwd=repo)
        assert result.returncode == 1
        assert output.exists()

    def test_anchor_commit_matches_head(self, repo: Path, tmp_path: Path):
        head_sha = _git("rev-parse", "HEAD", cwd=repo)
        output = tmp_path / "audit.json"
        _run_audit("--output", str(output), cwd=repo)

        data = json.loads(output.read_text())
        assert data["meta"]["anchor_commit"] == head_sha

    def test_command_recorded_in_meta(self, repo: Path, tmp_path: Path):
        output = tmp_path / "audit.json"
        _run_audit("--output", str(output), cwd=repo)

        data = json.loads(output.read_text())
        assert "audit" in data["meta"]["command"]

    def test_config_patterns_recorded(self, repo: Path, tmp_path: Path):
        output = tmp_path / "audit.json"
        _run_audit("--output", str(output), cwd=repo)

        data = json.loads(output.read_text())
        assert len(data["config"]["patterns"]) == 1
        p = data["config"]["patterns"][0]
        assert p["code"] == "SG001"
        assert p["description"] == "Subject ID"
        assert "SUB" in p["regex"]

    def test_match_details_in_results(self, repo: Path, tmp_path: Path):
        """
        GIVEN a commit with PHI on a known line and column
        WHEN running audit
        THEN the JSON result contains exact file, line, column, and matched_text
        """
        (repo / "phi.txt").write_text("Patient SUB-1234 enrolled\n")
        _git("add", "phi.txt", cwd=repo)
        _git("commit", "-m", "PHI commit", cwd=repo)

        output = tmp_path / "audit.json"
        _run_audit("--output", str(output), cwd=repo)

        data = json.loads(output.read_text())
        phi_result = next(r for r in data["results"] if r["message"] == "PHI commit")
        assert len(phi_result["matches"]) == 1
        m = phi_result["matches"][0]
        assert m["file"] == "phi.txt"
        assert m["line"] == 1
        assert m["column"] == 9
        assert m["matched_text"] == "SUB-1234"
        assert m["pattern_code"] == "SG001"

    def test_summary_counts_are_correct(self, repo: Path, tmp_path: Path):
        (repo / "phi.txt").write_text("SUB-1234\n")
        _git("add", "phi.txt", cwd=repo)
        _git("commit", "-m", "Dirty commit", cwd=repo)

        output = tmp_path / "audit.json"
        _run_audit("--output", str(output), cwd=repo)

        data = json.loads(output.read_text())
        assert data["summary"]["commits_checked"] == 2
        assert data["summary"]["commits_with_matches"] == 1
        assert data["summary"]["total_matches"] == 1

    def test_options_recorded_in_json(self, repo: Path, tmp_path: Path):
        output = tmp_path / "audit.json"
        _run_audit("--no-gitignore", "--output", str(output), cwd=repo)

        data = json.loads(output.read_text())
        assert data["options"]["no_gitignore"] is True
        assert data["options"]["include_remotes"] is False

    def test_custom_output_path_used(self, repo: Path, tmp_path: Path):
        custom = tmp_path / "nested" / "my-audit.json"
        custom.parent.mkdir()
        _run_audit("--output", str(custom), cwd=repo)

        assert custom.exists()
        # No default timestamped file created inside the repo
        assert list(repo.glob("shredguard-audit-*.json")) == []


# ---------------------------------------------------------------------------
# Commit deduplication
# ---------------------------------------------------------------------------


class TestAuditCommitDeduplication:
    """Commits reachable from multiple branches are scanned only once."""

    def test_shared_commit_counted_once(self, repo: Path, tmp_path: Path):
        """
        GIVEN main and feature both point to the exact same commit
        WHEN running audit
        THEN commits_checked == 1 (not 2)
        """
        _git("branch", "feature", cwd=repo)
        output = tmp_path / "audit.json"
        _run_audit("--output", str(output), cwd=repo)

        data = json.loads(output.read_text())
        assert data["summary"]["commits_checked"] == 1
        assert len(data["branches_scanned"]) == 2

    def test_shared_commit_lists_both_branches_in_results(self, tmp_path: Path):
        """
        GIVEN a commit with PHI reachable from two branches
        WHEN running audit
        THEN that commit's result lists both branch names
        """
        repo = tmp_path / "repo"
        repo.mkdir()
        _git("init", cwd=repo)
        _git("config", "user.email", "test@test.com", cwd=repo)
        _git("config", "user.name", "Test", cwd=repo)
        (repo / "pyproject.toml").write_text(_CONFIG)
        (repo / "phi.txt").write_text("SUB-1234\n")
        _git("add", ".", cwd=repo)
        _git("commit", "-m", "Shared PHI commit", cwd=repo)

        initial_sha = _git("rev-parse", "HEAD", cwd=repo)
        _git("branch", "feature", cwd=repo)

        output = tmp_path / "audit.json"
        _run_audit("--output", str(output), cwd=repo)

        data = json.loads(output.read_text())
        assert data["summary"]["commits_checked"] == 1
        result = data["results"][0]
        assert result["sha"] == initial_sha
        assert len(result["branches"]) == 2

    def test_unique_commits_on_diverged_branches(self, repo: Path, tmp_path: Path):
        """
        GIVEN main has 2 commits and feature branches from the first
        WHEN running audit
        THEN commits_checked == 2 (the shared base + the main-only commit)
        """
        _ = _git("rev-parse", "HEAD", cwd=repo)
        _git("branch", "feature", cwd=repo)

        (repo / "main_only.txt").write_text("only on main\n")
        _git("add", "main_only.txt", cwd=repo)
        _git("commit", "-m", "Main-only commit", cwd=repo)

        output = tmp_path / "audit.json"
        _run_audit("--output", str(output), cwd=repo)

        data = json.loads(output.read_text())
        assert data["summary"]["commits_checked"] == 2


# ---------------------------------------------------------------------------
# Flags and edge cases
# ---------------------------------------------------------------------------


class TestAuditFlags:
    def test_not_a_git_repo_exits_with_error(self, tmp_path: Path):
        """
        GIVEN a directory that is not a git repository
        WHEN running audit
        THEN it exits 1 with an error mentioning git or repository
        """
        (tmp_path / "pyproject.toml").write_text(_CONFIG)
        result = _run_audit(cwd=tmp_path)

        assert result.returncode == 1
        combined = result.stdout + result.stderr
        assert "git" in combined.lower() or "repository" in combined.lower()

    def test_include_remotes_flag_recorded_in_json(self, repo: Path, tmp_path: Path):
        """
        GIVEN a repo with no remotes
        WHEN running audit --include-remotes
        THEN it succeeds and JSON records include_remotes: true
        """
        output = tmp_path / "audit.json"
        _ = _run_audit("--include-remotes", "--output", str(output), cwd=repo)

        assert output.exists()
        data = json.loads(output.read_text())
        assert data["options"]["include_remotes"] is True

    def test_gitignore_filters_committed_files_by_default(
        self, repo: Path, tmp_path: Path
    ):
        """
        GIVEN secrets/phi.txt was committed before .gitignore excluded it
        WHEN running audit without --no-gitignore
        THEN secrets/phi.txt is not scanned (total_matches == 0) — the audit
             respects the current .gitignore even for historical git objects
        """
        (repo / "secrets").mkdir()
        (repo / "secrets" / "phi.txt").write_text("SUB-1234\n")
        _git("add", "secrets/phi.txt", cwd=repo)
        _git("commit", "-m", "Add secrets before gitignore", cwd=repo)

        (repo / ".gitignore").write_text("secrets/\n")
        _git("add", ".gitignore", cwd=repo)
        _git("commit", "-m", "Exclude secrets via gitignore", cwd=repo)

        output = tmp_path / "audit.json"
        _run_audit("--output", str(output), cwd=repo)

        data = json.loads(output.read_text())
        assert data["summary"]["total_matches"] == 0

    def test_no_gitignore_scans_gitignored_files(self, repo: Path, tmp_path: Path):
        """
        GIVEN secrets/phi.txt was committed before .gitignore excluded it
        WHEN running audit with --no-gitignore
        THEN secrets/phi.txt IS scanned and PHI is found
        """
        (repo / "secrets").mkdir()
        (repo / "secrets" / "phi.txt").write_text("SUB-1234\n")
        _git("add", "secrets/phi.txt", cwd=repo)
        _git("commit", "-m", "Add secrets before gitignore", cwd=repo)

        (repo / ".gitignore").write_text("secrets/\n")
        _git("add", ".gitignore", cwd=repo)
        _git("commit", "-m", "Exclude secrets via gitignore", cwd=repo)

        output = tmp_path / "audit.json"
        _run_audit("--no-gitignore", "--output", str(output), cwd=repo)

        data = json.loads(output.read_text())
        assert data["summary"]["total_matches"] >= 1


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


class TestAuditExitCodes:
    def test_exits_0_when_all_commits_are_clean(self, repo: Path, tmp_path: Path):
        result = _run_audit("--output", str(tmp_path / "a.json"), cwd=repo)
        assert result.returncode == 0

    def test_exits_1_when_any_commit_has_matches(self, repo: Path, tmp_path: Path):
        (repo / "phi.txt").write_text("SUB-1234\n")
        _git("add", "phi.txt", cwd=repo)
        _git("commit", "-m", "PHI commit", cwd=repo)

        result = _run_audit("--output", str(tmp_path / "a.json"), cwd=repo)
        assert result.returncode == 1

    def test_exits_1_on_dirty_config(self, repo: Path, tmp_path: Path):
        (repo / "pyproject.toml").write_text(_CONFIG + "\n# dirty\n")
        result = _run_audit("--output", str(tmp_path / "a.json"), cwd=repo)
        assert result.returncode == 1
