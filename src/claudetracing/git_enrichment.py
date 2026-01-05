"""Git metadata enrichment for Claude Code traces."""

import subprocess


def get_git_metadata(cwd: str | None = None) -> dict[str, str]:
    """Capture git metadata from the current working directory.

    Raises:
        FileNotFoundError: If git is not installed
        subprocess.TimeoutExpired: If git command takes too long
    """
    metadata = {}

    commands = {
        "git.commit_id": ["git", "rev-parse", "HEAD"],
        "git.branch": ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        "git.remote_url": ["git", "remote", "get-url", "origin"],
    }

    for key, cmd in commands.items():
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            metadata[key] = result.stdout.strip()

    return metadata
