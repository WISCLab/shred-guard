"""Git utility functions for shredguard audit."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(Exception):
    """Raised when a git operation fails."""


def _run(
    *args: str,
    cwd: Path | None = None,
    check: bool = True,
) -> str:
    """Run a git command and return stdout as text."""
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if check and result.returncode != 0:
        raise GitError(result.stderr.strip() or f"git {args[0]} failed")
    return result.stdout.strip()


def _run_bytes(*args: str) -> bytes | None:
    """Run a git command and return raw bytes, or None on failure."""
    result = subprocess.run(["git", *args], capture_output=True)
    if result.returncode != 0:
        return None
    return result.stdout


def get_repo_root() -> Path:
    """Get the root directory of the current git repository."""
    try:
        return Path(_run("rev-parse", "--show-toplevel"))
    except GitError as e:
        raise GitError(f"Not inside a git repository: {e}") from e


def get_head_sha() -> str:
    """Get the full SHA of HEAD."""
    return _run("rev-parse", "HEAD")


def get_current_branch() -> str | None:
    """Get the current branch name, or None if in detached HEAD state."""
    result = subprocess.run(
        ["git", "symbolic-ref", "--short", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def is_path_in_repo(path: Path, repo_root: Path) -> bool:
    """Check whether a path lives inside the repository root."""
    try:
        path.resolve().relative_to(repo_root.resolve())
        return True
    except ValueError:
        return False


def get_dirty_relevant_files(config_path: Path, repo_root: Path) -> list[Path]:
    """Return config / .gitignore files that have any uncommitted changes.

    Catches staged changes, unstaged modifications, untracked new files,
    deletions, and renames — for the config file and any .gitignore file.
    """
    config_resolved = config_path.resolve()
    dirty: list[Path] = []

    def _check(output: str) -> None:
        for rel in output.splitlines():
            rel = rel.strip().strip('"')
            if not rel:
                continue
            abs_path = (repo_root / rel).resolve()
            if abs_path not in dirty and (
                abs_path == config_resolved or abs_path.name == ".gitignore"
            ):
                dirty.append(abs_path)

    # Staged changes (index vs HEAD) — reliable even immediately after a commit.
    _check(_run("diff", "--cached", "--name-only", cwd=repo_root))

    # Unstaged changes (working tree vs HEAD) — `git diff HEAD` bypasses the
    # index mtime cache, so it correctly catches modifications made in the same
    # clock-second as the preceding commit ("racy git" scenario).
    # Silently ignore failures on repos with no commits yet.
    result = subprocess.run(
        ["git", "diff", "HEAD", "--name-only"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        _check(result.stdout)

    # Untracked new files (not yet added to the index).
    _check(_run("ls-files", "--others", "--exclude-standard", cwd=repo_root))

    return dirty


def get_local_branches() -> list[str]:
    """Return all local branch names."""
    output = _run("branch", "--format=%(refname:short)")
    return [b.strip() for b in output.splitlines() if b.strip()]


def get_remote_branches() -> list[str]:
    """Return all remote-tracking branch names, excluding HEAD pointers."""
    output = _run("branch", "-r", "--format=%(refname:short)")
    return [
        b.strip()
        for b in output.splitlines()
        if b.strip() and "HEAD" not in b
    ]


def get_commits_for_branch(branch: str) -> list[tuple[str, str]]:
    """Return all commits reachable from *branch* as (full_sha, subject) pairs.

    Ordered newest-first (same as ``git log`` default).
    """
    sep = "\x1f"
    output = _run("log", branch, f"--format=%H{sep}%s")
    commits: list[tuple[str, str]] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(sep, 1)
        commits.append((parts[0], parts[1] if len(parts) > 1 else ""))
    return commits


def get_tracked_files(sha: str) -> list[str]:
    """Return all file paths tracked in the tree of *sha*."""
    output = _run("ls-tree", "-r", "--name-only", sha)
    return [f for f in output.splitlines() if f.strip()]


def get_file_content(sha: str, file_path: str) -> bytes | None:
    """Return raw bytes for *file_path* at commit *sha*, or None on failure."""
    return _run_bytes("show", f"{sha}:{file_path}")
