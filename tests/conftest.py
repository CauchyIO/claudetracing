"""Shared pytest fixtures for claudetracing tests."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_test_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Ensure tests never leak env vars, touch ~/.codex, or shell out to claude plugins."""
    snapshot = dict(os.environ)
    for key in list(os.environ):
        if key.startswith(("MLFLOW_", "DATABRICKS_", "COPILOT_", "CT_TEST_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex_home"))
    monkeypatch.setattr(
        "claudetracing.setup.ensure_claude_plugin", lambda *args, **kwargs: True
    )
    try:
        yield
    finally:
        for key in list(os.environ):
            if key not in snapshot:
                os.environ.pop(key, None)
        for key, val in snapshot.items():
            os.environ[key] = val
