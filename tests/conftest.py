"""Shared pytest fixtures for claudetracing tests."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_codex_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tests never read or modify the user's real ~/.codex directory."""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex_home"))
