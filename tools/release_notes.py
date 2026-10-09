#!/usr/bin/env python3
"""Extract one version's section from CHANGELOG.md, the GitHub release body.

The record lives in git: the pull request that bumps the version adds its
``## v<version>`` section to CHANGELOG.md and reviewers trim it there. When the
bump lands on master, the release job extracts that section as the body of the
GitHub release, so the notes a reader sees are the notes that were reviewed.
Nothing is generated at release time. Pure stdlib.

Usage:
    python3 tools/release_notes.py --version v0.5.0 --extract-from CHANGELOG.md --out RELEASE_NOTES.md
    python3 tools/release_notes.py --version v0.5.0 --extract-from CHANGELOG.md   # to stdout
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def extract_section(changelog: Path, version: str) -> str:
    """Return the body under ``## <version>``; raise if absent or empty."""
    version = version if version.startswith("v") else f"v{version}"
    lines = changelog.read_text().splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.strip() == f"## {version}"), None
    )
    if start is None:
        raise SystemExit(f"{changelog}: no `## {version}` section")
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        body.append(line)
    text = "\n".join(body).strip()
    if not text:
        raise SystemExit(f"{changelog}: the `## {version}` section is empty")
    return text + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version", required=True, help="e.g. v0.5.0 (the v is optional)"
    )
    parser.add_argument("--extract-from", type=Path, required=True, metavar="CHANGELOG")
    parser.add_argument("--out", type=Path, help="write here instead of stdout")
    args = parser.parse_args()

    section = extract_section(args.extract_from, args.version)
    if args.out:
        args.out.write_text(section)
        print(f"wrote {args.out} ({len(section.splitlines())} lines)")
    else:
        sys.stdout.write(section)
    return 0


if __name__ == "__main__":
    sys.exit(main())
