"""Tests for the release tooling, against real git repositories.

tools/check_version_bump.py and tools/release_notes.py are what let the merge
be the release, so they are exercised the way CI runs them: as subprocesses
over a throwaway git repository with real commits, branches and tags.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
GIT_IDENTITY = [
    "-c",
    "user.name=test",
    "-c",
    "user.email=test@example.com",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "tag.gpgsign=false",
]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *GIT_IDENTITY, *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def pyproject(version: str) -> str:
    return f'[project]\nname = "pkg"\nversion = "{version}"\n'


def changelog(*versions: str) -> str:
    sections = "".join(f"## v{v}\n\n- Something changed in {v}.\n\n" for v in versions)
    return "# Changelog\n\n" + sections


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo on master at version 0.1.0, tagged v0.1.0, with a feature branch."""
    git(tmp_path, "init", "-q", "-b", "master")
    write(tmp_path, "pyproject.toml", pyproject("0.1.0"))
    write(tmp_path, "CHANGELOG.md", changelog("0.1.0"))
    write(tmp_path, "src/pkg/__init__.py", "VERSION = '0.1.0'\n")
    write(tmp_path, "README.md", "# pkg\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "Initial")
    git(tmp_path, "tag", "v0.1.0")
    git(tmp_path, "checkout", "-q", "-b", "feature")
    return tmp_path


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def run_check(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(TOOLS / "check_version_bump.py"),
            "--base",
            "master",
            "--repo",
            str(repo),
        ],
        capture_output=True,
        text=True,
    )


def test_package_change_without_bump_fails(repo: Path) -> None:
    write(repo, "src/pkg/__init__.py", "VERSION = '0.1.0'\nNEW = True\n")
    commit_all(repo, "Change the package")

    result = run_check(repo)

    assert result.returncode == 1
    assert "bump it" in result.stdout
    assert "src/pkg/__init__.py" in result.stdout


def test_docs_only_change_needs_no_bump(repo: Path) -> None:
    write(repo, "README.md", "# pkg\n\nMore docs.\n")
    commit_all(repo, "Docs")

    result = run_check(repo)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok: version 0.1.0" in result.stdout


def test_bump_with_changelog_section_passes(repo: Path) -> None:
    write(repo, "src/pkg/__init__.py", "VERSION = '0.1.1'\n")
    write(repo, "pyproject.toml", pyproject("0.1.1"))
    write(repo, "CHANGELOG.md", changelog("0.1.1", "0.1.0"))
    commit_all(repo, "Bump to 0.1.1")

    result = run_check(repo)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok: version 0.1.1" in result.stdout


def test_bump_without_changelog_section_fails(repo: Path) -> None:
    write(repo, "pyproject.toml", pyproject("0.1.1"))
    commit_all(repo, "Bump without notes")

    result = run_check(repo)

    assert result.returncode == 1
    assert "CHANGELOG.md has no `## v0.1.1` section" in result.stdout


def test_bump_not_above_highest_tag_fails(repo: Path) -> None:
    # Someone shipped 0.2.0 by hand: the tag exists, master's pyproject does not know.
    git(repo, "tag", "v0.2.0")
    write(repo, "pyproject.toml", pyproject("0.1.5"))
    write(repo, "CHANGELOG.md", changelog("0.1.5", "0.1.0"))
    commit_all(repo, "Bump to 0.1.5")

    result = run_check(repo)

    assert result.returncode == 1
    assert "not greater than the highest tag v0.2.0" in result.stdout


def test_bump_below_base_version_fails(repo: Path) -> None:
    write(repo, "pyproject.toml", pyproject("0.0.9"))
    write(repo, "CHANGELOG.md", changelog("0.0.9", "0.1.0"))
    commit_all(repo, "Go backwards")

    result = run_check(repo)

    assert result.returncode == 1
    assert "not greater than master's 0.1.0" in result.stdout


def run_notes(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOLS / "release_notes.py"), *args],
        capture_output=True,
        text=True,
    )


def test_release_notes_extracts_exactly_one_section(tmp_path: Path) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(changelog("0.2.0", "0.1.0"))
    out = tmp_path / "RELEASE_NOTES.md"

    result = run_notes(
        "--version", "v0.2.0", "--extract-from", str(path), "--out", str(out)
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert out.read_text() == "- Something changed in 0.2.0.\n"


def test_release_notes_accepts_version_without_v(tmp_path: Path) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(changelog("0.2.0"))

    result = run_notes("--version", "0.2.0", "--extract-from", str(path))

    assert result.returncode == 0
    assert result.stdout == "- Something changed in 0.2.0.\n"


def test_release_notes_missing_section_fails(tmp_path: Path) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(changelog("0.1.0"))

    result = run_notes("--version", "v9.9.9", "--extract-from", str(path))

    assert result.returncode != 0
    assert "no `## v9.9.9` section" in result.stderr


def test_release_notes_empty_section_fails(tmp_path: Path) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text("# Changelog\n\n## v0.3.0\n\n## v0.2.0\n\n- Real notes.\n")

    result = run_notes("--version", "v0.3.0", "--extract-from", str(path))

    assert result.returncode != 0
    assert "section is empty" in result.stderr
