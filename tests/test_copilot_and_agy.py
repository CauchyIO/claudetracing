"""Tests for GitHub Copilot and Google Antigravity (AGY) MLflow tracing integrations."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from mlflow import MlflowClient
from typer.testing import CliRunner

from claudetracing.agy import (
    AGY_HOOK_CMD_STOP,
    AGY_HOOK_NAME,
    configure_agy,
    convert_agy_transcript,
    disable_agy,
    get_agy_status,
)
from claudetracing.cli import app
from claudetracing.copilot import (
    configure_copilot,
    convert_copilot_transcript,
    disable_copilot,
    get_copilot_status,
)

runner = CliRunner()


def test_configure_status_and_disable_copilot(tmp_path: Path):
    hook_path = configure_copilot(
        project_root=tmp_path,
        tracking_uri="databricks",
        experiment_name="/Workspace/Shared/copilot-exp",
        experiment_id="55",
        profile="my-dbx",
    )
    assert hook_path == tmp_path / ".github" / "hooks" / "mlflow-tracing.json"
    local_path = tmp_path / ".github" / "hooks" / "mlflow-tracing.local.json"
    assert local_path.exists()

    hook_data = json.loads(hook_path.read_text(encoding="utf-8"))
    assert "SessionStart" in hook_data["hooks"]
    assert "Stop" in hook_data["hooks"]
    stop_env = hook_data["hooks"]["Stop"][0]["env"]
    assert stop_env["MLFLOW_TRACKING_URI"] == "databricks"
    assert stop_env["MLFLOW_EXPERIMENT_ID"] == "55"
    assert "DATABRICKS_CONFIG_PROFILE" not in stop_env

    local_data = json.loads(local_path.read_text(encoding="utf-8"))
    assert local_data["env"]["MLFLOW_TRACKING_URI"] == "databricks://my-dbx"
    assert local_data["env"]["DATABRICKS_CONFIG_PROFILE"] == "my-dbx"

    st = get_copilot_status(tmp_path)
    assert st.enabled is True
    assert st.tracking_uri == "databricks://my-dbx"
    assert st.experiment_name == "/Workspace/Shared/copilot-exp"
    assert st.experiment_id == "55"

    assert disable_copilot(tmp_path) is True
    assert not hook_path.exists()
    assert not local_path.exists()
    assert get_copilot_status(tmp_path).enabled is False


def test_convert_copilot_transcript_and_cli_hook_creates_mlflow_trace(
    tmp_path: Path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    for key in list(os.environ):
        if key.startswith(("MLFLOW_", "DATABRICKS_", "COPILOT_")):
            monkeypatch.delenv(key, raising=False)

    uri = f"sqlite:///{tmp_path / 'copilot_mlflow.db'}"
    client = MlflowClient(tracking_uri=uri)
    exp_id = client.create_experiment("copilot-test")

    configure_copilot(
        project_root=tmp_path,
        tracking_uri=uri,
        experiment_name="copilot-test",
        experiment_id=exp_id,
        async_mode=False,
    )

    events = [
        {
            "type": "user.message",
            "id": "u-1",
            "timestamp": "2026-10-15T12:00:00Z",
            "parentId": None,
            "data": {"content": "Check git status in this repo"},
        },
        {
            "type": "assistant.message",
            "id": "a-1",
            "timestamp": "2026-10-15T12:00:01Z",
            "parentId": "u-1",
            "data": {
                "messageId": "m-1",
                "content": "",
                "reasoningText": "Running git status.",
                "toolRequests": [
                    {
                        "toolCallId": "tc-1",
                        "name": "run_in_terminal",
                        "arguments": {"command": "git status"},
                    }
                ],
            },
        },
        {
            "type": "tool.execution_complete",
            "id": "t-1",
            "timestamp": "2026-10-15T12:00:02Z",
            "parentId": "a-1",
            "data": {
                "toolCallId": "tc-1",
                "result": {"content": "On branch main\nnothing to commit"},
            },
        },
        {
            "type": "assistant.message",
            "id": "a-2",
            "timestamp": "2026-10-15T12:00:03Z",
            "parentId": "t-1",
            "data": {
                "messageId": "m-2",
                "content": "The working tree is clean on branch main.",
                "toolRequests": [],
            },
        },
    ]
    transcript_path = tmp_path / "copilot_events.jsonl"
    transcript_path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )

    converted_file = Path(convert_copilot_transcript(transcript_path))
    try:
        lines = [
            json.loads(line)
            for line in converted_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(lines) == 5
        assert lines[1]["message"]["content"] == [
            {
                "type": "thinking",
                "thinking": "Running git status.",
            }
        ]
        assert lines[2]["message"]["content"][0]["type"] == "tool_use"
        assert lines[2]["message"]["content"][0]["input"] == {"command": "git status"}
    finally:
        converted_file.unlink(missing_ok=True)

    # Test session-start and synchronous stop hook via CLI
    res_start = runner.invoke(
        app,
        ["copilot-hook", "session-start"],
        input=json.dumps({"session_id": "cp-sess-1"}),
    )
    assert res_start.exit_code == 0
    assert "Copilot session ID: cp-sess-1" in res_start.stdout

    res_stop = runner.invoke(
        app,
        ["copilot-hook", "stop"],
        input=json.dumps(
            {
                "session_id": "cp-sess-1",
                "transcript_path": str(transcript_path),
            }
        ),
    )
    assert res_stop.exit_code == 0
    assert json.loads(res_stop.stdout.strip()) == {"continue": True}

    traces = client.search_traces(locations=[exp_id])
    assert len(traces) == 1
    span_names = [s.name for s in traces[0].data.spans]
    assert "tool_run_in_terminal" in span_names


def test_configure_status_and_disable_agy_preserves_other_hooks(tmp_path: Path):
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    hooks_path = agents_dir / "hooks.json"
    hooks_path.write_text(
        json.dumps(
            {
                "other-hook": {
                    "enabled": True,
                    "Stop": [{"type": "command", "command": "echo hi"}],
                }
            }
        ),
        encoding="utf-8",
    )

    configure_agy(
        project_root=tmp_path,
        tracking_uri="https://mlflow.example.com",
        experiment_name="agy-exp",
        experiment_id="88",
        tracking_token="secret-tok",
    )

    hooks_data = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert "other-hook" in hooks_data
    assert AGY_HOOK_NAME in hooks_data
    stop_cmd = hooks_data[AGY_HOOK_NAME]["Stop"][0]["command"]
    assert stop_cmd == AGY_HOOK_CMD_STOP

    st = get_agy_status(tmp_path)
    assert st.enabled is True
    assert st.tracking_uri == "https://mlflow.example.com"
    assert st.experiment_name == "agy-exp"
    assert st.experiment_id == "88"

    assert disable_agy(tmp_path) is True
    assert not (agents_dir / "mlflow-tracing.json").exists()
    hooks_after = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert "other-hook" in hooks_after
    assert AGY_HOOK_NAME not in hooks_after
    assert get_agy_status(tmp_path).enabled is False


def test_convert_agy_transcript_and_stop_hook_creates_mlflow_trace(
    tmp_path: Path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    for key in list(os.environ):
        if key.startswith(("MLFLOW_", "DATABRICKS_")):
            monkeypatch.delenv(key, raising=False)

    uri = f"sqlite:///{tmp_path / 'agy_mlflow.db'}"
    client = MlflowClient(tracking_uri=uri)
    exp_id = client.create_experiment("agy-test")

    configure_agy(
        project_root=tmp_path,
        tracking_uri=uri,
        experiment_name="agy-test",
        experiment_id=exp_id,
    )

    steps = [
        {
            "step_index": 0,
            "type": "USER_INPUT",
            "status": "DONE",
            "created_at": "2026-10-15T12:10:00Z",
            "content": "<USER_REQUEST>List the files in this directory.</USER_REQUEST>",
        },
        {
            "step_index": 1,
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "created_at": "2026-10-15T12:10:01Z",
            "thinking": "I will run ls.",
            "content": "",
            "model": "claude-opus-4-6",
            "usage": {"input_tokens": 120, "output_tokens": 35},
            "tool_calls": [
                {
                    "id": "agy-tc-1",
                    "name": "run_command",
                    "arguments": {"CommandLine": "ls -la"},
                }
            ],
        },
        {
            "step_index": 2,
            "type": "GENERIC",
            "status": "DONE",
            "created_at": "2026-10-15T12:10:02Z",
            "content": "README.md\npyproject.toml",
        },
        {
            "step_index": 3,
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "created_at": "2026-10-15T12:10:03Z",
            "content": "The directory contains README.md and pyproject.toml.",
            "model": "claude-opus-4-6",
            "usage": {"input_tokens": 150, "output_tokens": 20},
        },
    ]
    transcript_path = tmp_path / "transcript.jsonl"
    transcript_path.write_text(
        "\n".join(json.dumps(s) for s in steps) + "\n", encoding="utf-8"
    )

    converted_file = Path(
        convert_agy_transcript(transcript_path, model_name="claude-opus-4-6")
    )
    try:
        lines = [
            json.loads(line)
            for line in converted_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(lines) == 5
        planner_msg = lines[1]["message"]
        assert planner_msg["usage"] == {"input_tokens": 120, "output_tokens": 35}
        assert planner_msg["content"] == [
            {
                "type": "thinking",
                "thinking": "I will run ls.",
            }
        ]
        assert lines[2]["message"]["content"] == [
            {
                "type": "tool_use",
                "id": "agy-tc-1",
                "name": "run_command",
                "input": {"CommandLine": "ls -la"},
            }
        ]
    finally:
        converted_file.unlink(missing_ok=True)

    res_agy = runner.invoke(
        app,
        ["agy-hook"],
        input=json.dumps(
            {
                "conversationId": "agy-conv-1",
                "transcriptPath": str(transcript_path),
                "workspacePaths": [str(tmp_path)],
                "modelName": "claude-opus-4-6",
                "eventType": "Stop",
            }
        ),
    )
    assert res_agy.exit_code == 0
    assert json.loads(res_agy.stdout.strip()) == {"decision": "stop"}

    traces = client.search_traces(locations=[exp_id])
    assert len(traces) == 1
    span_names = [s.name for s in traces[0].data.spans]
    assert "tool_run_command" in span_names


def test_copilot_async_debounce_and_worker_lifecycle(tmp_path: Path, monkeypatch):
    """Async mode spawns Popen once; a second call within debounce writes hook file but skips Popen.
    Worker mode (_COPILOT_HOOK_FILE) calls process_transcript and cleans up the hook file.
    """
    from claudetracing.copilot import run_copilot_stop

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COPILOT_TRACE_ASYNC", "1")
    monkeypatch.delenv("_COPILOT_HOOK_FILE", raising=False)

    configure_copilot(
        project_root=tmp_path,
        tracking_uri=f"sqlite:///{tmp_path / 'mlflow.db'}",
        experiment_name="async-test",
        experiment_id="0",
        async_mode=True,
    )

    events = [
        {
            "type": "user.message",
            "id": "u-1",
            "timestamp": "2026-10-15T12:00:00Z",
            "parentId": None,
            "data": {"content": "hello"},
        },
    ]
    transcript_path = tmp_path / "transcript.jsonl"
    transcript_path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )

    hook_data = json.dumps(
        {
            "session_id": "sess-async",
            "transcript_path": str(transcript_path),
            "cwd": str(tmp_path),
        }
    )

    mock_popen = MagicMock()
    with (
        patch("claudetracing.copilot.subprocess.Popen", mock_popen),
        patch("sys.stdin") as mock_stdin,
    ):
        mock_stdin.read.return_value = hook_data
        run_copilot_stop(project_root=tmp_path)

    assert mock_popen.call_count == 1

    hook_file = Path(tempfile.gettempdir()) / "copilot-traces" / "sess-async_hook.json"
    assert hook_file.exists()

    with (
        patch("claudetracing.copilot.subprocess.Popen", mock_popen),
        patch("sys.stdin") as mock_stdin,
    ):
        mock_stdin.read.return_value = hook_data
        run_copilot_stop(project_root=tmp_path)

    assert mock_popen.call_count == 1

    monkeypatch.setenv("COPILOT_TRACE_ASYNC", "0")
    monkeypatch.setenv("_COPILOT_HOOK_FILE", str(hook_file))
    mock_process = MagicMock()
    with (
        patch("mlflow.claude_code.tracing.process_transcript", mock_process),
        patch("mlflow.claude_code.tracing.setup_mlflow"),
    ):
        run_copilot_stop(project_root=tmp_path)

    assert mock_process.call_count == 1
    assert not hook_file.exists()
