"""Git metadata enrichment for Claude Code traces."""

import os
import subprocess
from pathlib import Path


def _git_cmd(args: list[str], cwd: str | None = None) -> str | None:
    """Run a git command and return the output, or None on failure."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd or os.getcwd(),
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def is_git_repo(cwd: str | None = None) -> bool:
    """Check if the current directory is inside a git repository."""
    return _git_cmd(["rev-parse", "--git-dir"], cwd) is not None


def get_git_metadata(cwd: str | None = None) -> dict[str, str]:
    """Capture git metadata from the current working directory.

    Returns a dict with git information that can be added as trace tags.
    Keys are prefixed with 'git.' for namespacing in MLflow.
    """
    if not is_git_repo(cwd):
        return {}

    metadata = {
        "git.commit_id": _git_cmd(["rev-parse", "HEAD"], cwd),
        "git.branch": _git_cmd(["rev-parse", "--abbrev-ref", "HEAD"], cwd),
        "git.remote_url": _git_cmd(["remote", "get-url", "origin"], cwd),
    }

    # Get repo root for deriving repo name if no remote
    repo_root = _git_cmd(["rev-parse", "--show-toplevel"], cwd)

    # Get repo name from remote URL or directory name
    if metadata["git.remote_url"]:
        remote = metadata["git.remote_url"]
        # Handle both HTTPS and SSH URLs
        # https://github.com/org/repo.git -> org/repo
        # git@github.com:org/repo.git -> org/repo
        if remote.endswith(".git"):
            remote = remote[:-4]
        if ":" in remote and "@" in remote:
            # SSH format: git@github.com:org/repo
            metadata["git.repo_name"] = remote.split(":")[-1]
        elif "/" in remote:
            # HTTPS format: https://github.com/org/repo
            parts = remote.rstrip("/").split("/")
            if len(parts) >= 2:
                metadata["git.repo_name"] = f"{parts[-2]}/{parts[-1]}"
    elif repo_root:
        metadata["git.repo_name"] = Path(repo_root).name

    # Filter out None values
    return {k: v for k, v in metadata.items() if v is not None}


def get_recent_commits(n: int = 5, cwd: str | None = None) -> list[dict[str, str]]:
    """Get the last n commits with their metadata.

    Useful for understanding recent project context.
    """
    if not is_git_repo(cwd):
        return []

    # Format: hash|short_hash|author|date|subject
    log_format = "%H|%h|%an|%aI|%s"
    output = _git_cmd(["log", f"-{n}", f"--format={log_format}"], cwd)

    if not output:
        return []

    commits = []
    for line in output.split("\n"):
        if not line:
            continue
        parts = line.split("|", 4)
        if len(parts) == 5:
            commits.append(
                {
                    "hash": parts[0],
                    "short_hash": parts[1],
                    "author": parts[2],
                    "date": parts[3],
                    "subject": parts[4],
                }
            )
    return commits
