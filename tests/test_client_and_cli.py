"""End-to-end tests for TracingClient, formatters, models, and CLI commands."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import mlflow
from mlflow import MlflowClient
from typer.testing import CliRunner

from claudetracing import __version__
from claudetracing.cli import app
from claudetracing.client import TracingClient
from claudetracing.formatters import (
    format_for_context,
    format_tool_usage,
    format_traces_json,
    format_traces_summary,
)

runner = CliRunner()


def _seed_trace(tracking_uri: str, experiment_name: str) -> tuple[str, str]:
    """Create an experiment and a sample AGENT + TOOL trace in SQLite."""
    mlflow.set_tracking_uri(tracking_uri)
    client = MlflowClient(tracking_uri=tracking_uri)
    exp = client.get_experiment_by_name(experiment_name)
    exp_id = exp.experiment_id if exp else client.create_experiment(experiment_name)

    root = client.start_trace(
        "claude_code_conversation",
        span_type="AGENT",
        inputs={"prompt": "Fix the bug in setup.py"},
        experiment_id=exp_id,
        tags={"mlflow.source.git.branch": "main"},
        start_time_ns=1_700_000_000_000_000_000,
    )
    tool_span = client.start_span(
        "tool_Edit",
        root.trace_id,
        root.span_id,
        span_type="TOOL",
        inputs={"file_path": "setup.py"},
        start_time_ns=1_700_000_000_100_000_000,
    )
    client.end_span(
        root.trace_id,
        tool_span.span_id,
        outputs={"result": "Updated file"},
        status="OK",
        end_time_ns=1_700_000_000_500_000_000,
    )
    client.end_trace(
        root.trace_id,
        outputs={"response": "Fixed setup.py", "status": "completed"},
        status="OK",
        end_time_ns=1_700_000_001_000_000_000,
    )
    mlflow.flush_trace_async_logging()
    return exp_id, root.trace_id


def test_tracing_client_and_formatters_roundtrip(tmp_path: Path, monkeypatch):
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    for key in list(os.environ):
        if key.startswith(("MLFLOW_", "DATABRICKS_")):
            monkeypatch.delenv(key, raising=False)

    exp_id, trace_id = _seed_trace(uri, "client-test-exp")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    monkeypatch.setenv("MLFLOW_EXPERIMENT_NAME", "client-test-exp")

    tc = TracingClient()
    exps = tc.list_experiments()
    assert any(e["name"] == "client-test-exp" and e["id"] == exp_id for e in exps)

    traces = tc.search_traces()
    assert len(traces) == 1
    trace = traces[0]
    assert trace.info.trace_id == trace_id
    assert trace.get_tool_calls() == ["tool_Edit"]

    fetched = tc.get_trace(trace_id)
    assert fetched is not None
    assert fetched.info.trace_id == trace_id

    summary_out = format_traces_summary(traces)
    assert trace_id in summary_out
    assert "tool_Edit" in summary_out

    json_out = json.loads(format_traces_json(traces))
    assert json_out[0]["info"]["trace_id"] == trace_id

    context_out = format_for_context(traces)
    assert "Previous Session Traces (1 total)" in context_out
    assert "tool_Edit" in context_out

    tools_out = format_tool_usage(traces)
    assert "tool_Edit: 1" in tools_out


def test_cli_init_status_list_search_and_disable(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex_home"))
    for key in list(os.environ):
        if key.startswith(("MLFLOW_", "DATABRICKS_")):
            monkeypatch.delenv(key, raising=False)

    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    exp_id, trace_id = _seed_trace(uri, "cli-exp")

    with patch("claudetracing.setup.resolve_experiment", return_value=(True, exp_id)):
        res_init = runner.invoke(
            app,
            [
                "init",
                "--agent",
                "all",
                "--tracking-uri",
                "http://localhost:5000",
                "--experiment",
                "cli-exp",
                "--yes",
            ],
        )
    assert res_init.exit_code == 0

    res_status = runner.invoke(app, ["status"])
    assert res_status.exit_code == 0
    assert "Claude Code: enabled" in res_status.stdout
    assert "Codex: enabled" in res_status.stdout
    assert "GitHub Copilot: enabled" in res_status.stdout
    assert "Antigravity (agy): enabled" in res_status.stdout

    # Point env at the seeded SQLite DB to test CLI list and search
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)

    res_list = runner.invoke(app, ["list"])
    assert res_list.exit_code == 0
    assert "cli-exp" in res_list.stdout

    res_search = runner.invoke(app, ["search", "-f", "summary"])
    assert res_search.exit_code == 0
    assert trace_id in res_search.stdout

    res_search_id = runner.invoke(
        app, ["search", "--trace-id", trace_id, "-f", "tools"]
    )
    assert res_search_id.exit_code == 0
    assert "tool_Edit: 1" in res_search_id.stdout

    res_disable = runner.invoke(app, ["disable"])
    assert res_disable.exit_code == 0
    assert "Disabled Claude Code tracing." in res_disable.stdout
    assert "Disabled Codex tracing." in res_disable.stdout
    assert "Disabled GitHub Copilot tracing." in res_disable.stdout
    assert "Disabled Antigravity (agy) tracing." in res_disable.stdout

    expected_version = f"claudetracing {__version__}"

    res_ver_flag = runner.invoke(app, ["--version"])
    assert res_ver_flag.exit_code == 0
    assert expected_version in res_ver_flag.stdout

    res_ver_cmd = runner.invoke(app, ["version"])
    assert res_ver_cmd.exit_code == 0
    assert expected_version in res_ver_cmd.stdout


def test_search_invalid_format_exits_nonzero(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)

    res = runner.invoke(app, ["search", "-f", "invalid_fmt"])
    assert res.exit_code != 0


def test_search_since_trailing_z(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    _seed_trace(uri, "z-test-exp")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    monkeypatch.setenv("MLFLOW_EXPERIMENT_NAME", "z-test-exp")

    res = runner.invoke(
        app,
        ["search", "--since", "2026-10-15T00:00:00Z", "-e", "z-test-exp"],
    )
    assert res.exit_code == 0
