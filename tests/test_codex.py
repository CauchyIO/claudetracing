"""Tests for Codex CLI configuration following @mlflow/codex conventions."""

import json
from pathlib import Path

import pytest
import tomlkit

from claudetracing.codex import (
    MLFLOW_CODEX_NOTIFY,
    configure_codex,
    disable_codex,
    get_codex_status,
)


def test_configure_codex_creates_project_files(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex_home"))
    project = tmp_path / "project"
    project.mkdir()

    config_path, tracing_path = configure_codex(
        project,
        tracking_uri="http://localhost:5000",
        experiment_id="12",
        trace_location="main.genai.traces",
    )

    assert config_path == project / ".codex" / "config.toml"
    assert tracing_path == project / ".codex" / "mlflow-tracing.json"

    doc = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    assert doc["notify"] == MLFLOW_CODEX_NOTIFY

    tracing_data = json.loads(tracing_path.read_text(encoding="utf-8"))
    assert tracing_data == {
        "trackingUri": "http://localhost:5000",
        "experimentId": "12",
        "traceLocation": "main.genai.traces",
    }

    status = get_codex_status(project)
    assert status.enabled is True
    assert status.scope == "project"
    assert status.tracking_uri == "http://localhost:5000"
    assert status.experiment_id == "12"
    assert status.trace_location == "main.genai.traces"


def test_configure_codex_preserves_existing_toml_comments_and_tables(tmp_path: Path):
    project = tmp_path / "project"
    codex_dir = project / ".codex"
    codex_dir.mkdir(parents=True)
    config_path = codex_dir / "config.toml"
    config_path.write_text(
        '# Keep this comment\n[mcp_servers.linear]\nurl = "https://mcp.linear.app/mcp"\n',
        encoding="utf-8",
    )

    configure_codex(
        project, tracking_uri="https://mlflow.example.com", experiment_id="3"
    )

    raw = config_path.read_text(encoding="utf-8")
    assert "# Keep this comment" in raw
    parsed = tomlkit.parse(raw)
    assert parsed["notify"] == MLFLOW_CODEX_NOTIFY
    assert parsed["mcp_servers"]["linear"]["url"] == "https://mcp.linear.app/mcp"


def test_configure_codex_upgrades_legacy_claudetracing_hook(tmp_path: Path):
    project = tmp_path / "project"
    codex_dir = project / ".codex"
    codex_dir.mkdir(parents=True)
    config_path = codex_dir / "config.toml"
    config_path.write_text(
        'notify = ["/usr/bin/python3", "-m", "claudetracing.codex", "notify"]\n',
        encoding="utf-8",
    )

    configure_codex(project, tracking_uri="databricks://work", experiment_id="5")
    parsed = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    assert parsed["notify"] == MLFLOW_CODEX_NOTIFY


def test_configure_codex_refuses_to_clobber_custom_notify(tmp_path: Path):
    project = tmp_path / "project"
    codex_dir = project / ".codex"
    codex_dir.mkdir(parents=True)
    config_path = codex_dir / "config.toml"
    config_path.write_text(
        'notify = ["my-custom-notifier", "--flag"]\n', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="already has a custom `notify` entry"):
        configure_codex(
            project, tracking_uri="http://localhost:5000", experiment_id="0"
        )


def test_disable_codex_preserves_other_settings(tmp_path: Path):
    project = tmp_path / "project"
    codex_dir = project / ".codex"
    codex_dir.mkdir(parents=True)
    (codex_dir / "config.toml").write_text(
        "[features]\nexample = true\n",
        encoding="utf-8",
    )
    configure_codex(project, tracking_uri="http://localhost:5000", experiment_id="1")

    assert disable_codex(project) is True
    assert not (codex_dir / "mlflow-tracing.json").exists()
    parsed = tomlkit.parse((codex_dir / "config.toml").read_text(encoding="utf-8"))
    assert "notify" not in parsed
    assert parsed["features"]["example"] is True


def test_configure_codex_syncs_codex_home_and_chains_sky_client(
    tmp_path: Path, monkeypatch
):
    import sys

    codex_home = tmp_path / "codex_home"
    codex_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    global_cfg = codex_home / "config.toml"
    global_cfg.write_text(
        'notify = ["/Applications/Codex.app/SkyComputerUseClient", "turn-ended"]\n',
        encoding="utf-8",
    )

    project = tmp_path / "project"
    project.mkdir()
    configure_codex(project, tracking_uri="http://localhost:5000", experiment_id="1")

    global_doc = tomlkit.parse(global_cfg.read_text(encoding="utf-8"))
    expected_shim = json.dumps(
        [sys.executable, "-m", "claudetracing.codex", "notify-hook"]
    )
    assert list(global_doc["notify"]) == [
        "/Applications/Codex.app/SkyComputerUseClient",
        "turn-ended",
        "--previous-notify",
        expected_shim,
    ]

    # Re-configuring should be idempotent and never clobber SkyComputerUseClient
    configure_codex(project, tracking_uri="http://localhost:5000", experiment_id="2")
    global_doc_again = tomlkit.parse(global_cfg.read_text(encoding="utf-8"))
    assert list(global_doc_again["notify"]) == [
        "/Applications/Codex.app/SkyComputerUseClient",
        "turn-ended",
        "--previous-notify",
        expected_shim,
    ]

    assert disable_codex(project) is True
    assert not (project / ".codex" / "mlflow-tracing.json").exists()
    assert get_codex_status(project).enabled is False

    assert disable_codex(project_local=False) is True
    global_doc_after = tomlkit.parse(global_cfg.read_text(encoding="utf-8"))
    assert list(global_doc_after["notify"]) == [
        "/Applications/Codex.app/SkyComputerUseClient",
        "turn-ended",
    ]
