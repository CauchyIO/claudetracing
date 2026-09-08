"""Parse persisted Codex rollout records without discarding custom tool payloads."""

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from mlflow import MlflowClient


class Record(BaseModel):
    timestamp: datetime
    type: str
    payload: dict[str, Any]

    @property
    def ns(self) -> int:
        return int(self.timestamp.timestamp() * 1_000_000_000)


@dataclass
class Turn:
    id: str
    records: list[Record]
    model: str
    tokens: dict[str, int]


def completed_turns(snapshot: bytes) -> tuple[list[Record], list[Turn]]:
    records = [
        Record.model_validate_json(line)
        for line in snapshot.splitlines()
        if line.strip()
    ]
    turns: list[Turn] = []
    active: list[Record] = []
    model = "unknown"
    total: dict[str, int] = {}
    before: dict[str, int] = {}
    for record in records:
        payload = record.payload
        if record.type == "turn_context" and payload.get("model"):
            model = payload["model"]
        if record.type == "event_msg" and payload.get("type") == "task_started":
            active = []
            before = total.copy()
        if record.type == "event_msg" and payload.get("type") == "token_count":
            usage = (payload.get("info") or {}).get("total_token_usage")
            if usage is not None:
                total = {
                    key: int(usage.get(key, 0))
                    for key in ("input_tokens", "output_tokens", "total_tokens")
                }
        active.append(record)
        if record.type == "event_msg" and payload.get("type") == "task_complete":
            start = next(
                (r for r in active if r.payload.get("type") == "task_started"), None
            )
            if start is None:
                raise ValueError("Completed Codex turn has no task_started record")
            if start.payload.get("turn_id") != payload.get("turn_id"):
                raise ValueError("Codex turn start/completion IDs do not match")
            turn_id = str(payload.get("turn_id") or start.timestamp.isoformat())
            tokens = {
                key: value - before.get(key, 0)
                if value >= before.get(key, 0)
                else value
                for key, value in total.items()
            }
            turns.append(Turn(turn_id, active, model, tokens))
            active = []
    return records, turns


def text(payload: dict[str, Any]) -> str:
    content = payload.get("content", [])
    if isinstance(content, str):
        return content
    return "\n".join(
        block.get("text", "")
        for block in content
        if block.get("type") in ("input_text", "output_text")
    )


def emit_turn(
    client: "MlflowClient", experiment_id: str, session: str, turn: Turn
) -> str:
    # The imperative API preserves recorded timings; no invented LLM request boundaries.
    from mlflow.tracing.trace_manager import InMemoryTraceManager

    messages = [
        r
        for r in turn.records
        if r.type == "response_item" and r.payload.get("type") == "message"
    ]
    prompts = [text(r.payload) for r in messages if r.payload.get("role") == "user"]
    responses = [
        text(r.payload) for r in messages if r.payload.get("role") == "assistant"
    ]
    root = client.start_trace(
        "codex_conversation",
        span_type="AGENT",
        inputs={"messages": prompts},
        experiment_id=experiment_id,
        tags={
            "codex.session_id": session,
            "codex.turn_id": turn.id,
            "model": turn.model,
        },
        start_time_ns=turn.records[0].ns,
    )
    with InMemoryTraceManager.get_instance().get_trace(root.trace_id) as trace:
        if trace is None:
            raise RuntimeError("MLflow did not create the Codex trace")
        trace.info.trace_metadata["mlflow.trace.session"] = session
    results = {
        r.payload.get("call_id"): r
        for r in turn.records
        if r.type == "response_item"
        and r.payload.get("type") in ("function_call_output", "custom_tool_call_output")
    }
    failures = {
        r.payload.get("call_id")
        for r in turn.records
        if r.type == "event_msg"
        and r.payload.get("type") == "exec_command_end"
        and (r.payload.get("status") == "failed" or r.payload.get("exit_code", 0))
    }
    failed = False
    for record in turn.records:
        payload = record.payload
        if record.type != "response_item" or payload.get("type") not in (
            "function_call",
            "custom_tool_call",
        ):
            continue
        call_id = payload["call_id"]
        result = results.get(call_id)
        inputs = (
            json.loads(payload.get("arguments", "{}"))
            if payload["type"] == "function_call"
            else {"input": payload.get("input", "")}
        )
        span = client.start_span(
            f"tool_{payload.get('name', 'unknown')}",
            root.trace_id,
            root.span_id,
            span_type="TOOL",
            inputs=inputs,
            start_time_ns=record.ns,
            attributes={"tool.call_id": call_id},
        )
        error = call_id in failures or result is None
        failed |= error
        client.end_span(
            root.trace_id,
            span.span_id,
            outputs={"result": result.payload.get("output") if result else None},
            status="ERROR" if error else "OK",
            end_time_ns=result.ns if result else turn.records[-1].ns,
        )
    client.end_trace(
        root.trace_id,
        outputs={"messages": responses},
        attributes={"mlflow.chat.tokenUsage": turn.tokens, "model": turn.model},
        status="ERROR" if failed else "OK",
        end_time_ns=turn.records[-1].ns,
    )
    # Read-back establishes successful persistence before advancing the local checkpoint.
    client.get_trace(root.trace_id)
    return root.trace_id
