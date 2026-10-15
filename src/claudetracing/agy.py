"""Google Antigravity (agy) hook setup and transcript conversion for MLflow tracing."""

import json
from pathlib import Path
import re
import sys
import tempfile

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

AGY_HOOK_NAME = "mlflow-tracing"
AGY_HOOK_CMD_STOP = "cd .. && (traces agy-hook || uv run traces agy-hook)"
_USER_REQUEST_RE = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.DOTALL)


class AgyTracingConfig(BaseModel):
    """Configuration stored in .agents/mlflow-tracing.json."""

    model_config = ConfigDict(populate_by_name=True)

    tracking_uri: str = Field(
        validation_alias=AliasChoices("trackingUri", "tracking_uri"),
        serialization_alias="trackingUri",
    )
    experiment_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("experimentId", "experiment_id"),
        serialization_alias="experimentId",
    )
    experiment_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("experimentName", "experiment_name"),
        serialization_alias="experimentName",
    )
    tracking_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("trackingToken", "tracking_token"),
        serialization_alias="trackingToken",
    )


class AgyTracingStatus(BaseModel):
    """Status of Antigravity (agy) MLflow tracing in a project."""

    enabled: bool
    hooks_path: str
    tracing_config_path: str
    tracking_uri: str | None = None
    experiment_id: str | None = None
    experiment_name: str | None = None


def agy_dir(project_root: Path | None = None) -> Path:
    root = (project_root or Path.cwd()).resolve()
    return root / ".agents"


def agy_hooks_path(project_root: Path | None = None) -> Path:
    return agy_dir(project_root) / "hooks.json"


def agy_tracing_config_path(project_root: Path | None = None) -> Path:
    return agy_dir(project_root) / "mlflow-tracing.json"


def configure_agy(
    project_root: Path | None = None,
    *,
    tracking_uri: str,
    experiment_id: str | None = None,
    experiment_name: str | None = None,
    tracking_token: str | None = None,
) -> tuple[Path, Path]:
    """Configure Antigravity (.agents/hooks.json and .agents/mlflow-tracing.json)."""
    root = (project_root or Path.cwd()).resolve()
    hooks_file = agy_hooks_path(root)
    tracing_file = agy_tracing_config_path(root)
    hooks_file.parent.mkdir(parents=True, exist_ok=True)

    hooks_doc: dict = {}
    if hooks_file.exists():
        try:
            loaded = json.loads(hooks_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                hooks_doc = loaded
        except json.JSONDecodeError:
            hooks_doc = {}

    hooks_doc[AGY_HOOK_NAME] = {
        "enabled": True,
        "Stop": [
            {
                "type": "command",
                "command": AGY_HOOK_CMD_STOP,
                "timeout": 30,
            }
        ],
    }
    hooks_file.write_text(json.dumps(hooks_doc, indent=2) + "\n", encoding="utf-8")

    cfg = AgyTracingConfig(
        tracking_uri=tracking_uri,
        experiment_id=str(experiment_id) if experiment_id else None,
        experiment_name=experiment_name,
        tracking_token=tracking_token,
    )
    tracing_file.write_text(
        json.dumps(cfg.model_dump(by_alias=True, exclude_none=True), indent=2) + "\n",
        encoding="utf-8",
    )

    return hooks_file, tracing_file


def get_agy_status(project_root: Path | None = None) -> AgyTracingStatus:
    """Inspect .agents/hooks.json and .agents/mlflow-tracing.json for status reporting."""
    root = (project_root or Path.cwd()).resolve()
    hooks_file = agy_hooks_path(root)
    tracing_file = agy_tracing_config_path(root)

    hook_enabled = False
    if hooks_file.exists():
        try:
            doc = json.loads(hooks_file.read_text(encoding="utf-8"))
            entry = doc.get(AGY_HOOK_NAME, {}) if isinstance(doc, dict) else {}
            if isinstance(entry, dict) and entry.get("enabled", True) is not False:
                stop_list = entry.get("Stop", [])
                if any(
                    isinstance(h, dict) and "agy-hook" in h.get("command", "")
                    for h in stop_list
                ):
                    hook_enabled = True
        except Exception:
            hook_enabled = False

    tracking_uri: str | None = None
    experiment_id: str | None = None
    experiment_name: str | None = None
    if tracing_file.exists():
        try:
            raw = json.loads(tracing_file.read_text(encoding="utf-8"))
            tracking_uri = raw.get("trackingUri")
            experiment_id = raw.get("experimentId")
            experiment_name = raw.get("experimentName")
        except Exception:
            pass

    return AgyTracingStatus(
        enabled=bool(hook_enabled and tracking_uri),
        hooks_path=str(hooks_file),
        tracing_config_path=str(tracing_file),
        tracking_uri=tracking_uri,
        experiment_id=experiment_id,
        experiment_name=experiment_name,
    )


def disable_agy(project_root: Path | None = None) -> bool:
    """Remove mlflow-tracing from .agents/hooks.json and delete .agents/mlflow-tracing.json."""
    root = (project_root or Path.cwd()).resolve()
    hooks_file = agy_hooks_path(root)
    tracing_file = agy_tracing_config_path(root)
    changed = False

    if hooks_file.exists():
        try:
            doc = json.loads(hooks_file.read_text(encoding="utf-8"))
            if isinstance(doc, dict) and AGY_HOOK_NAME in doc:
                del doc[AGY_HOOK_NAME]
                changed = True
                if doc:
                    hooks_file.write_text(
                        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
                    )
                else:
                    hooks_file.unlink()
        except Exception:
            pass

    if tracing_file.exists():
        tracing_file.unlink()
        changed = True

    return changed


def _extract_user_prompt(raw_content: str) -> str:
    """Extract clean user prompt text from Antigravity USER_INPUT step content."""
    if not raw_content:
        return ""
    match = _USER_REQUEST_RE.search(raw_content)
    if match:
        return match.group(1).strip()
    return raw_content.strip()


def convert_agy_transcript(
    transcript_path: str | Path, model_name: str | None = None
) -> str:
    """Convert an Antigravity (agy) transcript.jsonl to Claude Code JSONL format."""
    t_path = Path(transcript_path)
    full_path = t_path.with_name("transcript_full.jsonl")
    source_path = full_path if full_path.exists() else t_path

    steps: list[dict] = []
    with open(source_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                steps.append(json.loads(line))

    model = model_name or "antigravity"
    claude_entries: list[dict] = []

    i = 0
    n = len(steps)
    while i < n:
        step = steps[i]
        stype = step.get("type", "")
        timestamp = step.get("created_at")

        if stype == "USER_INPUT":
            prompt = _extract_user_prompt(str(step.get("content", "")))
            if prompt:
                claude_entries.append(
                    {
                        "type": "user",
                        "timestamp": timestamp,
                        "message": {
                            "role": "user",
                            "content": prompt,
                        },
                    }
                )
            i += 1
            continue

        if stype == "PLANNER_RESPONSE":
            usage: dict[str, int] = {}
            if step.get("input_tokens") is not None:
                usage["input_tokens"] = int(step["input_tokens"])
            if step.get("output_tokens") is not None:
                usage["output_tokens"] = int(step["output_tokens"])
            if step.get("cache_read_tokens") is not None:
                usage["cache_read_input_tokens"] = int(step["cache_read_tokens"])

            tool_calls = step.get("tool_calls") or []
            text = str(step.get("content") or "")

            # Collect subsequent GENERIC steps that hold tool call outputs
            generic_outputs: list[dict] = []
            j = i + 1
            while j < n and steps[j].get("type") == "GENERIC":
                generic_outputs.append(steps[j])
                j += 1

            if tool_calls:
                tool_parts: list[dict] = []
                for idx, tc in enumerate(tool_calls):
                    call_id = f"agy_tc_{step.get('step_index', i)}_{idx}"
                    args = tc.get("args", {})
                    if not isinstance(args, dict):
                        args = {"raw": str(args)}
                    tool_parts.append(
                        {
                            "type": "tool_use",
                            "id": call_id,
                            "name": tc.get("name", "unknown"),
                            "input": args,
                        }
                    )

                msg_obj: dict = {
                    "role": "assistant",
                    "model": model,
                    "content": tool_parts,
                }
                if usage and not text.strip():
                    msg_obj["usage"] = usage

                claude_entries.append(
                    {
                        "type": "assistant",
                        "timestamp": timestamp,
                        "message": msg_obj,
                    }
                )

                for idx, _tc in enumerate(tool_calls):
                    call_id = f"agy_tc_{step.get('step_index', i)}_{idx}"
                    gen = generic_outputs[idx] if idx < len(generic_outputs) else None
                    res_ts = gen.get("created_at") if gen else timestamp
                    res_content = str(gen.get("content", "")) if gen else "completed"
                    claude_entries.append(
                        {
                            "type": "user",
                            "timestamp": res_ts,
                            "message": {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "tool_result",
                                        "tool_use_id": call_id,
                                        "content": res_content,
                                    }
                                ],
                            },
                        }
                    )

            if text.strip():
                text_msg: dict = {
                    "role": "assistant",
                    "model": model,
                    "content": [{"type": "text", "text": text}],
                }
                if usage:
                    text_msg["usage"] = usage
                claude_entries.append(
                    {
                        "type": "assistant",
                        "timestamp": timestamp,
                        "message": text_msg,
                    }
                )

            i = j
            continue

        i += 1

    tmp_dir = Path(tempfile.gettempdir()) / "agy-traces"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=tmp_dir,
        prefix="converted_agy_",
        suffix=".jsonl",
        delete=False,
    ) as f:
        for ce in claude_entries:
            f.write(json.dumps(ce) + "\n")
        return f.name


def run_agy_stop(project_root: Path | None = None) -> None:
    """Handle Antigravity Stop hook input on stdin and export trace to MLflow."""
    from claudetracing.setup import load_tracing_env

    raw = sys.stdin.read().strip()
    hook_data: dict = {}
    if raw:
        try:
            hook_data = json.loads(raw)
        except json.JSONDecodeError:
            hook_data = {}

    if project_root is not None:
        root = project_root.resolve()
    else:
        workspaces = hook_data.get("workspacePaths") or []
        if workspaces and isinstance(workspaces, list):
            root = Path(workspaces[0]).resolve()
        elif Path.cwd().name == ".agents":
            root = Path.cwd().parent.resolve()
        else:
            root = Path.cwd().resolve()

    load_tracing_env(root)

    try:
        from mlflow.claude_code.tracing import (
            get_logger,
            is_tracing_enabled,
            process_transcript,
            setup_mlflow,
        )
    except ImportError:
        print(json.dumps({"decision": "stop"}))
        return

    if not is_tracing_enabled():
        print(json.dumps({"decision": "stop"}))
        return

    try:
        conversation_id = hook_data.get("conversationId") or hook_data.get("session_id")
        transcript_path = hook_data.get("transcriptPath") or hook_data.get(
            "transcript_path"
        )
        model_name = hook_data.get("modelName")

        if not transcript_path or not Path(transcript_path).exists():
            print(json.dumps({"decision": "stop"}))
            return

        converted_path = convert_agy_transcript(transcript_path, model_name=model_name)
        try:
            setup_mlflow()
            process_transcript(converted_path, conversation_id)
        finally:
            Path(converted_path).unlink(missing_ok=True)
    except Exception as exc:
        try:
            get_logger().error("agy stop hook error: %s", exc, exc_info=True)
        except Exception:
            pass

    print(json.dumps({"decision": "stop"}))


def main() -> None:
    run_agy_stop()


if __name__ == "__main__":
    main()
