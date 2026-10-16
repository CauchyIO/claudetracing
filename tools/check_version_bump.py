#!/usr/bin/env python3
"""Fail a pull request that changes the package without bumping its version.

Cutting a release is the merge that bumps the version (see the release job in
.github/workflows/ci.yml). That only works if every change that ships in the
wheel arrives with a bump, so this check runs on each pull request:

- a change under src/ or to pyproject.toml must come with a new version;
- a new version must be strictly greater than the base branch's version and
  than the highest v* tag, so a bump can never collide with something shipped;
- CHANGELOG.md must carry a ``## v<version>`` section with a body, because the
  release job publishes that section as the GitHub release body.

Docs-, test- and workflow-only changes need no bump. Pure stdlib.

Usage:
    python3 tools/check_version_bump.py --base origin/master
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

PACKAGE_PATHS = ("src/", "pyproject.toml")
SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def semver(version: str) -> tuple[int, int, int]:
    match = SEMVER.match(version)
    if not match:
        raise SystemExit(
            f"version {version!r} is not MAJOR.MINOR.PATCH; this check only "
            "understands plain semantic versions"
        )
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


VERSION_LINE = re.compile(r'^version\s*=\s*"([^"]+)"\s*$')


def project_version(pyproject_text: str) -> str:
    """The ``version`` of the ``[project]`` table (tomllib needs 3.11; we support 3.10)."""
    in_project = False
    for line in pyproject_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_project = stripped == "[project]"
            continue
        if in_project and (match := VERSION_LINE.match(stripped)):
            return match.group(1)
    raise SystemExit('pyproject.toml has no `version = "..."` under [project]')


def highest_tag(repo: Path) -> str | None:
    tags = [t for t in git("tag", "--list", "v*", cwd=repo).split() if SEMVER.match(t)]
    return max(tags, key=semver) if tags else None


def changelog_has_section(changelog: Path, version: str) -> bool:
    if not changelog.exists():
        return False
    text = changelog.read_text()
    heading = f"## v{version}"
    for i, line in enumerate(text.splitlines()):
        if line.strip() == heading:
            body = []
            for following in text.splitlines()[i + 1 :]:
                if following.startswith("## "):
                    break
                body.append(following.strip())
            return any(body)
    return False


def check(repo: Path, base: str) -> list[str]:
    """Return the list of violations (empty when the pull request is fine)."""
    head_version = project_version((repo / "pyproject.toml").read_text())
    base_version = project_version(git("show", f"{base}:pyproject.toml", cwd=repo))
    changed = git("diff", "--name-only", f"{base}...HEAD", cwd=repo).split()
    package_changed = [p for p in changed if p.startswith(PACKAGE_PATHS)]

    problems: list[str] = []
    if head_version == base_version:
        if package_changed:
            problems.append(
                f"version is still {head_version} but the package changed "
                f"({', '.join(package_changed)}); bump it with "
                "`uv version --bump patch|minor|major` and add a CHANGELOG.md section"
            )
        return problems

    if semver(head_version) <= semver(base_version):
        problems.append(
            f"version {head_version} is not greater than {base}'s {base_version}"
        )
    tag = highest_tag(repo)
    if tag is not None and semver(head_version) <= semver(tag):
        problems.append(
            f"version {head_version} is not greater than the highest tag {tag}; "
            "that version is already shipped"
        )
    if not changelog_has_section(repo / "CHANGELOG.md", head_version):
        problems.append(
            f"CHANGELOG.md has no `## v{head_version}` section with a body; the "
            "release job publishes that section as the GitHub release notes"
        )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="base ref, e.g. origin/master")
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()

    problems = check(args.repo, args.base)
    for problem in problems:
        print(f"::error::{problem}")
    if not problems:
        version = project_version((args.repo / "pyproject.toml").read_text())
        print(f"ok: version {version}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
