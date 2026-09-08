"""Real MLflow witnesses for transcript fidelity, retry safety, and hook coexistence."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
import tomlkit

from claudetracing.codex import export_session, configure, Notification

SESSION = "11111111-1111-4111-8111-111111111111"


def record(kind, payload, second):
    return {
        "timestamp": f"2026-01-01T00:00:{second:02d}Z",
        "type": kind,
        "payload": payload,
    }


def rollout(project):
    return [
        record("session_meta", {"id": SESSION, "cwd": str(project)}, 0),
        record("turn_context", {"model": "codex-test"}, 0),
        record("event_msg", {"type": "task_started", "turn_id": "first"}, 1),
        record(
            "response_item",
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Inspect the project"}],
            },
            2,
        ),
        record(
            "response_item",
            {
                "type": "function_call",
                "name": "exec_command",
                "call_id": "shell",
                "arguments": '{"cmd":"pwd"}',
            },
            3,
        ),
        record(
            "response_item",
            {
                "type": "function_call_output",
                "call_id": "shell",
                "output": "/example/project",
            },
            4,
        ),
        record(
            "event_msg",
            {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 100,
                        "output_tokens": 10,
                        "total_tokens": 110,
                    }
                },
            },
            5,
        ),
        record(
            "response_item",
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Inspected."}],
            },
            6,
        ),
        record("event_msg", {"type": "task_complete", "turn_id": "first"}, 7),
        record("event_msg", {"type": "task_started", "turn_id": "second"}, 8),
        record(
            "response_item",
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Apply the change"}],
            },
            9,
        ),
        record(
            "response_item",
            {
                "type": "custom_tool_call",
                "name": "apply_patch",
                "call_id": "patch",
                "input": "*** Begin Patch\n*** End Patch",
            },
            10,
        ),
        record(
            "response_item",
            {
                "type": "custom_tool_call_output",
                "call_id": "patch",
                "output": {"success": False},
            },
            11,
        ),
        record(
            "event_msg",
            {
                "type": "exec_command_end",
                "call_id": "patch",
                "exit_code": 1,
                "status": "failed",
            },
            11,
        ),
        record(
            "event_msg",
            {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 150,
                        "output_tokens": 17,
                        "total_tokens": 167,
                    }
                },
            },
            12,
        ),
        record(
            "response_item",
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Patch failed."}],
            },
            13,
        ),
        record("event_msg", {"type": "task_complete", "turn_id": "second"}, 14),
        record("event_msg", {"type": "task_started", "turn_id": "unfinished"}, 15),
    ]


@pytest.fixture
def environment(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith(("MLFLOW_", "DATABRICKS_")):
            monkeypatch.delenv(key)
    home = tmp_path / "codex home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.chdir(project)
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    configure(project, uri, "codex-tests")
    path = home / "sessions" / "2026" / "01" / "01" / f"rollout-{SESSION}.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("\n".join(json.dumps(r) for r in rollout(project)) + "\n")
    return home, project, uri, path


def notification(project):
    return Notification.model_validate(
        {"type": "agent-turn-complete", "thread-id": SESSION, "cwd": str(project)}
    )


def test_complete_conversation_roundtrip_and_retry(environment):
    home, project, uri, path = environment
    from mlflow import MlflowClient

    export_session(notification(project))
    client = MlflowClient(tracking_uri=uri)
    experiment = client.get_experiment_by_name("codex-tests")
    traces = client.search_traces(experiment_ids=[experiment.experiment_id])
    assert (
        len(traces) == 2
    )  # Backfills both completed turns, never the unfinished turn.
    turns = {t.info.tags["codex.turn_id"]: t for t in traces}
    first, second = turns["first"], turns["second"]
    assert first.info.trace_metadata["mlflow.trace.session"] == SESSION
    assert first.data.spans[0].inputs == {"messages": ["Inspect the project"]}
    assert second.data.spans[0].outputs == {"messages": ["Patch failed."]}
    tools = [s for s in second.data.spans if s.span_type == "TOOL"]
    assert len(tools) == 1
    assert tools[0].inputs == {"input": "*** Begin Patch\n*** End Patch"}
    assert tools[0].outputs == {"result": {"success": False}}
    assert tools[0].status.status_code.name == "ERROR"
    assert tools[0].end_time_ns - tools[0].start_time_ns == 1_000_000_000
    assert second.data.spans[0].attributes["mlflow.chat.tokenUsage"] == {
        "input_tokens": 50,
        "output_tokens": 7,
        "total_tokens": 57,
    }
    runs = client.search_runs([experiment.experiment_id])
    assert len(runs) == 1
    destination = home / "download"
    destination.mkdir()
    downloaded = Path(
        client.download_artifacts(
            runs[0].info.run_id, "conversation/rollout.jsonl", str(destination)
        )
    )
    assert downloaded.read_bytes() == path.read_bytes()
    assert not any(p.is_file() for p in (project / "mlruns").rglob("*"))
    assert (
        runs[0].data.tags["codex.rollout_sha256"]
        == hashlib.sha256(path.read_bytes()).hexdigest()
    )
    export_session(notification(project))
    assert len(client.search_traces(experiment_ids=[experiment.experiment_id])) == 2


def test_setup_preserves_toml_and_runs_existing_notifier(environment):
    home, project, uri, path = environment
    marker = home / "notification.json"
    original = [
        sys.executable,
        "-c",
        f"import pathlib,sys; pathlib.Path({str(marker)!r}).write_text(sys.argv[1])",
    ]
    config = home / "config.toml"
    config.write_text(
        "# keep this comment\nnotify = "
        + json.dumps(original)
        + "\n[features]\nexample = true\n"
    )
    # A user replaced our hook; the new command becomes the one we preserve.
    subprocess.run(
        [
            sys.executable,
            "-m",
            "claudetracing.cli",
            "codex",
            "init",
            "--tracking-uri",
            uri,
            "--experiment",
            "codex-tests",
            "--yes",
        ],
        check=True,
        timeout=10,
    )
    configure(project, uri, "codex-tests")
    parsed = tomlkit.parse(config.read_text())
    assert "# keep this comment" in config.read_text()
    assert parsed["features"]["example"] is True
    payload = notification(project).model_dump_json(by_alias=True)
    subprocess.run([*parsed["notify"], payload], check=True, timeout=10)
    from mlflow import MlflowClient

    client = MlflowClient(tracking_uri=uri)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        experiment = client.get_experiment_by_name("codex-tests")
        runs = client.search_runs([experiment.experiment_id]) if experiment else []
        if (
            marker.exists()
            and runs
            and client.list_artifacts(runs[0].info.run_id, "conversation")
        ):
            break
        time.sleep(0.2)
    else:
        pytest.fail((home / "claudetracing" / "notify.log").read_text())
    assert json.loads(marker.read_text())["thread-id"] == SESSION
    assert len(client.search_traces(experiment_ids=[experiment.experiment_id])) == 2
    # User-wide hook does not trace an unconfigured sibling directory.
    other = project.parent / "other"
    other.mkdir()
    subprocess.run(
        [*parsed["notify"], notification(other).model_dump_json(by_alias=True)],
        check=True,
        timeout=10,
    )
    assert len(client.search_runs([experiment.experiment_id])) == 1


@pytest.mark.parametrize(
    "damage", ["wrong-session", "malformed-record", "missing-transcript"]
)
def test_bad_transcript_fails_loudly(environment, damage):
    _, project, _, path = environment
    if damage == "wrong-session":
        path.write_text(
            path.read_text().replace(SESSION, "22222222-2222-4222-8222-222222222222")
        )
    elif damage == "malformed-record":
        path.write_text(path.read_text() + "{broken}\n")
    else:
        path.unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        export_session(notification(project))
