"""GitHub Copilot (CLI & VS Code) hook setup and transcript conversion for MLflow tracing."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from pydantic import BaseModel

COPILOT_HOOK_CMD_STOP = "traces copilot-hook stop || uv run traces copilot-hook stop"
COPILOT_HOOK_CMD_START = (
    "traces copilot-hook session-start || uv run traces copilot-hook session-start"
)
DEBOUNCE_SECONDS = 30


class CopilotTracingStatus(BaseModel):
    """Status of GitHub Copilot MLflow tracing in a project."""

    enabled: bool
    config_path: str
    tracking_uri: str | None = None
    experiment_id: str | None = None
    experiment_name: str | None = None


def copilot_config_path(project_root: Path | None = None) -> Path:
    root = (project_root or Path.cwd()).resolve()
    return root / ".github" / "hooks" / "mlflow-tracing.json"


def copilot_local_config_path(project_root: Path | None = None) -> Path:
    root = (project_root or Path.cwd()).resolve()
    return root / ".github" / "hooks" / "mlflow-tracing.local.json"


def configure_copilot(
    project_root: Path | None = None,
    *,
    tracking_uri: str,
    experiment_id: str | None = None,
    experiment_name: str | None = None,
    profile: str | None = None,
    tracking_token: str | None = None,
    async_mode: bool = True,
) -> Path:
    """Write .github/hooks/mlflow-tracing.json (and .local.json for machine-local secrets)."""
    root = (project_root or Path.cwd()).resolve()
    cfg_path = copilot_config_path(root)
    local_path = copilot_local_config_path(root)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    shared_uri = (
        "databricks" if tracking_uri.startswith("databricks://") else tracking_uri
    )
    env: dict[str, str] = {
        "MLFLOW_CLAUDE_TRACING_ENABLED": "true",
        "MLFLOW_TRACKING_URI": shared_uri,
        "COPILOT_TRACE_ASYNC": "1" if async_mode else "0",
    }
    if experiment_id:
        env["MLFLOW_EXPERIMENT_ID"] = str(experiment_id)
    if experiment_name:
        env["MLFLOW_EXPERIMENT_NAME"] = experiment_name

    config = {
        "hooks": {
            "SessionStart": [
                {
                    "type": "command",
                    "command": COPILOT_HOOK_CMD_START,
                    "timeout": 5,
                }
            ],
            "Stop": [
                {
                    "type": "command",
                    "command": COPILOT_HOOK_CMD_STOP,
                    "env": env,
                    "timeout": 15,
                }
            ],
        }
    }
    cfg_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    local_env: dict[str, str] = {}
    if profile:
        local_env["MLFLOW_TRACKING_URI"] = f"databricks://{profile}"
        local_env["DATABRICKS_CONFIG_PROFILE"] = profile
    elif tracking_uri.startswith("databricks://"):
        extracted = tracking_uri.removeprefix("databricks://").strip("/")
        if extracted:
            local_env["MLFLOW_TRACKING_URI"] = f"databricks://{extracted}"
            local_env["DATABRICKS_CONFIG_PROFILE"] = extracted
    if tracking_token:
        local_env["MLFLOW_TRACKING_TOKEN"] = tracking_token

    if local_env:
        local_path.write_text(
            json.dumps({"env": local_env}, indent=2) + "\n", encoding="utf-8"
        )
    elif local_path.exists():
        local_path.unlink()

    return cfg_path


def get_copilot_status(project_root: Path | None = None) -> CopilotTracingStatus:
    """Inspect .github/hooks/mlflow-tracing.json for status reporting."""
    root = (project_root or Path.cwd()).resolve()
    cfg_path = copilot_config_path(root)
    local_path = copilot_local_config_path(root)

    if not cfg_path.exists():
        return CopilotTracingStatus(enabled=False, config_path=str(cfg_path))

    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        stop_hooks = data.get("hooks", {}).get("Stop", [])
        env: dict[str, str] = {}
        has_hook = False
        for h in stop_hooks:
            if isinstance(h, dict) and (
                "copilot-hook" in h.get("command", "")
                or "copilot_trace.py" in h.get("command", "")
            ):
                has_hook = True
                if isinstance(h.get("env"), dict):
                    env.update({k: str(v) for k, v in h["env"].items()})
        if local_path.exists():
            local_data = json.loads(local_path.read_text(encoding="utf-8"))
            if isinstance(local_data.get("env"), dict):
                env.update({k: str(v) for k, v in local_data["env"].items()})

        enabled = has_hook and env.get("MLFLOW_CLAUDE_TRACING_ENABLED", "").lower() in (
            "true",
            "1",
            "yes",
        )
        return CopilotTracingStatus(
            enabled=enabled,
            config_path=str(cfg_path),
            tracking_uri=env.get("MLFLOW_TRACKING_URI"),
            experiment_id=env.get("MLFLOW_EXPERIMENT_ID"),
            experiment_name=env.get("MLFLOW_EXPERIMENT_NAME"),
        )
    except Exception:
        return CopilotTracingStatus(enabled=False, config_path=str(cfg_path))


def disable_copilot(project_root: Path | None = None) -> bool:
    """Remove .github/hooks/mlflow-tracing.json and .local.json."""
    root = (project_root or Path.cwd()).resolve()
    cfg_path = copilot_config_path(root)
    local_path = copilot_local_config_path(root)
    changed = False
    if cfg_path.exists():
        cfg_path.unlink()
        changed = True
    if local_path.exists():
        local_path.unlink()
        changed = True
    return changed


def convert_copilot_transcript(transcript_path: str | Path) -> str:
    """Convert a GitHub Copilot JSONL transcript to Claude Code JSONL format."""
    entries: list[dict] = []
    with open(transcript_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    tool_completions: dict[str, dict] = {}
    for entry in entries:
        if entry.get("type") == "tool.execution_complete":
            data = entry.get("data", {})
            tool_call_id = data.get("toolCallId", "")
            if tool_call_id:
                tool_completions[tool_call_id] = {
                    "data": data,
                    "timestamp": entry.get("timestamp"),
                }

    claude_entries: list[dict] = []
    for entry in entries:
        etype = entry.get("type", "")
        timestamp = entry.get("timestamp")
        data = entry.get("data", {})

        if etype == "user.message":
            content = data.get("content", "")
            if content:
                claude_entries.append(
                    {
                        "type": "user",
                        "timestamp": timestamp,
                        "message": {
                            "role": "user",
                            "content": content,
                        },
                    }
                )
        elif etype == "assistant.message":
            text = data.get("content", "")
            reasoning = data.get("reasoningText", "")
            tool_requests = data.get("toolRequests", [])
            model = data.get("model") or entry.get("model") or "copilot"

            # Emit thinking / text blocks first so chronological order before tool results is preserved
            text_parts: list[dict] = []
            if reasoning and str(reasoning).strip():
                text_parts.append({"type": "thinking", "thinking": str(reasoning)})
            if text and str(text).strip():
                text_parts.append({"type": "text", "text": str(text)})
            if text_parts:
                claude_entries.append(
                    {
                        "type": "assistant",
                        "timestamp": timestamp,
                        "message": {
                            "role": "assistant",
                            "model": model,
                            "content": text_parts,
                        },
                    }
                )

            # Emit tool_use blocks paired with their tool_result entries
            if tool_requests:
                tool_parts: list[dict] = []
                for tr in tool_requests:
                    tool_call_id = tr.get("toolCallId", "")
                    args = tr.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {"raw": args}
                    tool_parts.append(
                        {
                            "type": "tool_use",
                            "id": tool_call_id,
                            "name": tr.get("name", "unknown"),
                            "input": args,
                        }
                    )
                claude_entries.append(
                    {
                        "type": "assistant",
                        "timestamp": timestamp,
                        "message": {
                            "role": "assistant",
                            "model": model,
                            "content": tool_parts,
                        },
                    }
                )
                for tr in tool_requests:
                    tool_call_id = tr.get("toolCallId", "")
                    completion = tool_completions.get(tool_call_id)
                    result_ts = completion.get("timestamp") if completion else timestamp
                    claude_entries.append(
                        {
                            "type": "user",
                            "timestamp": result_ts,
                            "message": {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "tool_result",
                                        "tool_use_id": tool_call_id,
                                        "content": json.dumps(
                                            completion.get("data", {})
                                        )
                                        if completion
                                        else "no result",
                                    }
                                ],
                            },
                        }
                    )

    tmp_dir = Path(tempfile.gettempdir()) / "copilot-traces"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=tmp_dir,
        prefix="converted_copilot_",
        suffix=".jsonl",
        delete=False,
    ) as f:
        for ce in claude_entries:
            f.write(json.dumps(ce) + "\n")
        return f.name


def run_copilot_session_start() -> None:
    """Handle Copilot SessionStart hook input on stdin."""
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"continue": True}))
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"continue": True}))
        return

    session_id = data.get("session_id", "unknown")
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": f"Copilot session ID: {session_id}.",
                }
            }
        )
    )


def run_copilot_stop(project_root: Path | None = None) -> None:
    """Handle Copilot Stop hook input on stdin and export trace to MLflow."""
    from claudetracing.setup import load_tracing_env

    root = (project_root or Path.cwd()).resolve()
    load_tracing_env(root)

    if os.environ.get("COPILOT_TRACE_DISABLED") == "1":
        print(json.dumps({"continue": True}))
        return

    try:
        from mlflow.claude_code.tracing import (
            get_hook_response,
            get_logger,
            is_tracing_enabled,
            process_transcript,
            setup_mlflow,
        )
    except ImportError:
        print(json.dumps({"continue": True}))
        return

    if not is_tracing_enabled():
        print(json.dumps(get_hook_response()))
        return

    try:
        hook_file_path = os.environ.get("_COPILOT_HOOK_FILE")
        if hook_file_path and Path(hook_file_path).exists():
            hf = Path(hook_file_path)
            try:
                setup_mlflow()
                while hf.exists():
                    read_mtime = hf.stat().st_mtime
                    hook_data = json.loads(hf.read_text(encoding="utf-8"))
                    session_id = hook_data.get("session_id")
                    transcript_path = hook_data.get("transcript_path")
                    if transcript_path and Path(transcript_path).exists():
                        converted_path = convert_copilot_transcript(transcript_path)
                        try:
                            process_transcript(converted_path, session_id)
                        finally:
                            Path(converted_path).unlink(missing_ok=True)
                    if not hf.exists() or hf.stat().st_mtime <= read_mtime:
                        break
            finally:
                hf.unlink(missing_ok=True)
            print(json.dumps(get_hook_response()))
            return

        raw = sys.stdin.read().strip()
        hook_data = json.loads(raw) if raw else {}

        session_id = hook_data.get("session_id")
        transcript_path = hook_data.get("transcript_path")

        if not transcript_path or not Path(transcript_path).exists():
            get_logger().warning(
                "No transcript_path or file missing: %s", transcript_path
            )
            print(json.dumps(get_hook_response()))
            return

        if os.environ.get("COPILOT_TRACE_ASYNC") == "1":
            hook_file = (
                Path(tempfile.gettempdir())
                / "copilot-traces"
                / f"{session_id or 'unknown'}_hook.json"
            )
            hook_file.parent.mkdir(parents=True, exist_ok=True)
            recently_spawned = (
                hook_file.exists()
                and (time.time() - hook_file.stat().st_mtime) < DEBOUNCE_SECONDS
            )
            hook_file.write_text(json.dumps(hook_data), encoding="utf-8")

            if recently_spawned:
                print(json.dumps({"continue": True}))
                return

            env = {
                **os.environ,
                "COPILOT_TRACE_ASYNC": "0",
                "_COPILOT_HOOK_FILE": str(hook_file),
            }
            subprocess.Popen(
                [sys.executable, "-m", "claudetracing.copilot", "stop"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                cwd=hook_data.get("cwd", str(root)),
                creationflags=subprocess.CREATE_NO_WINDOW
                if sys.platform == "win32"
                else 0,
            )
            print(json.dumps({"continue": True}))
            return

        converted_path = convert_copilot_transcript(transcript_path)
        try:
            setup_mlflow()
            process_transcript(converted_path, session_id)
        finally:
            Path(converted_path).unlink(missing_ok=True)

        print(json.dumps(get_hook_response()))
    except Exception as exc:
        get_logger().error("copilot stop hook error: %s", exc, exc_info=True)
        print(json.dumps({"continue": True}))


def main() -> None:
    event = sys.argv[1] if len(sys.argv) > 1 else "stop"
    if event == "session-start":
        run_copilot_session_start()
    else:
        run_copilot_stop()


if __name__ == "__main__":
    main()
