"""
VS Code Copilot → MLflow trace adapter.

Thin wrapper around ``mlflow.claude_code`` tracing. The only thing this
script does is convert the VS Code transcript JSONL format into the
Claude Code transcript format that ``mlflow.claude_code.tracing.process_transcript``
expects, write it to a temp file, then hand off to the MLflow library.

Called by the ``Stop`` hook defined in ``.github/hooks/mlflow-tracing.json``.
"""

import json
import os
import sys
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# VS Code transcript → Claude Code transcript conversion
# ---------------------------------------------------------------------------


def convert_vscode_transcript(vscode_path: str) -> tuple[str, int]:
    """Read a VS Code Copilot transcript and write a Claude-format temp file.

    VS Code transcript entry types:
        user.message             → data.content (string), data.attachments
        assistant.message        → data.messageId, data.content, data.toolRequests, data.reasoningText
        tool.execution_start     → data.toolCallId, data.toolName, data.arguments
        tool.execution_complete  → data.toolCallId, data.success
        assistant.turn_start/end → metadata (skipped)
        session.start            → metadata (skipped)

    Claude Code transcript entry types:
        type: "user"      → message: {role: "user",      content: "…" | [{type: "tool_result", …}]}
        type: "assistant"  → message: {role: "assistant", content: [{type: "text", …}, {type: "tool_use", …}]}

    Returns (path to the converted temp file, number of entries).
    """
    with open(vscode_path, encoding="utf-8") as f:
        raw_lines = [json.loads(line) for line in f if line.strip()]

    claude_entries: list[dict] = []

    # Build lookup of tool completion results by toolCallId
    tool_completions: dict[str, dict] = {}
    for entry in raw_lines:
        if entry.get("type") == "tool.execution_complete":
            data = entry.get("data", {})
            tool_completions[data.get("toolCallId", "")] = entry

    for entry in raw_lines:
        entry_type = entry.get("type", "")
        data = entry.get("data", {})
        timestamp = entry.get("timestamp")

        # --- User message ---
        if entry_type == "user.message":
            content = data.get("content", "")
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

        # --- Assistant message ---
        elif entry_type == "assistant.message":
            text = data.get("content", "")
            tool_requests = data.get("toolRequests", [])

            content_parts: list[dict] = []

            # Add text part if present
            if text and text.strip():
                content_parts.append({"type": "text", "text": text})

            # Add tool_use parts from toolRequests
            for tr in tool_requests:
                tool_call_id = tr.get("toolCallId", "")
                args = tr.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}

                content_parts.append(
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
                        "content": content_parts if content_parts else text,
                    },
                }
            )

            # For each tool request, emit a corresponding tool_result user
            # message — mirrors how Claude Code interleaves tool results.
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
                                    "content": json.dumps(completion.get("data", {}))
                                    if completion
                                    else "no result",
                                }
                            ],
                        },
                    }
                )

    # Write converted transcript to temp file
    tmp_path = (
        Path(tempfile.gettempdir()) / "copilot-traces" / "converted_transcript.jsonl"
    )
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        for ce in claude_entries:
            f.write(json.dumps(ce) + "\n")

    return str(tmp_path), len(claude_entries)


# ---------------------------------------------------------------------------
# Main — wraps mlflow.claude_code stop_hook_handler with format conversion
# ---------------------------------------------------------------------------


def main() -> None:
    if os.environ.get("MLFLOW_CLAUDE_TRACING_ENABLED", "").lower() != "true":
        return

    try:
        from mlflow.claude_code.tracing import (
            get_hook_response,
            get_logger,
            is_tracing_enabled,
            process_transcript,
            read_hook_input,
            setup_mlflow,
        )
    except ImportError as e:
        print(json.dumps({"error": f"Missing dependency: {e}"}))
        sys.exit(1)

    if not is_tracing_enabled():
        print(json.dumps(get_hook_response()))
        return

    try:
        # Background respawn: read saved hook data from file instead of stdin
        hook_file_path = os.environ.get("_COPILOT_HOOK_FILE")
        if hook_file_path and Path(hook_file_path).exists():
            hook_data = json.loads(Path(hook_file_path).read_text(encoding="utf-8"))
            Path(hook_file_path).unlink(missing_ok=True)
        else:
            hook_data = read_hook_input()

        session_id = hook_data.get("session_id")
        transcript_path = hook_data.get("transcript_path")

        if not transcript_path or not Path(transcript_path).exists():
            get_logger().warning(
                "No transcript_path or file missing: %s", transcript_path
            )
            print(json.dumps(get_hook_response()))
            return

        # Because the Stop hook does not only seem to trigger at the end of each session,
        # but seemingly also after each message, we use async processing to avoid
        # MLFlow tracing loading after each message.
        # Async mode: save hook data, spawn background worker, return fast
        if os.environ.get("COPILOT_TRACE_ASYNC") == "1":
            import subprocess

            hook_file = (
                Path(tempfile.gettempdir())
                / "copilot-traces"
                / f"{session_id or 'unknown'}_hook.json"
            )
            hook_file.parent.mkdir(parents=True, exist_ok=True)
            hook_file.write_text(json.dumps(hook_data), encoding="utf-8")

            env = {
                **os.environ,
                "COPILOT_TRACE_ASYNC": "0",
                "_COPILOT_HOOK_FILE": str(hook_file),
            }
            module = __spec__.name if __spec__ else __name__
            subprocess.Popen(
                [sys.executable, "-m", module],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                cwd=hook_data.get("cwd", os.getcwd()),
                creationflags=subprocess.CREATE_NO_WINDOW
                if sys.platform == "win32"
                else 0,
            )
            print(json.dumps({"continue": True}))
            return

        # Convert VS Code transcript → Claude Code format
        converted_path, entry_count = convert_vscode_transcript(transcript_path)
        get_logger().info(
            "Converted VS Code transcript → %s (%d entries)",
            converted_path,
            entry_count,
        )

        # Hand off to MLflow library
        setup_mlflow()
        trace = process_transcript(converted_path, session_id)

        if trace is not None:
            print(json.dumps(get_hook_response()))
        else:
            print(
                json.dumps(
                    get_hook_response(
                        error="Failed to process converted transcript — check .claude/mlflow/claude_tracing.log"
                    )
                )
            )

    except Exception as exc:
        get_logger().error("copilot_trace.py error: %s", exc, exc_info=True)
        print(json.dumps(get_hook_response(error=str(exc))))


if __name__ == "__main__":
    main()
