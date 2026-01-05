"""Output formatters for trace data."""

import json
from typing import Any

from claudetracing.models import TraceData


def to_summary(trace: TraceData) -> str:
    """Format a trace as a human-readable summary string.

    Args:
        trace: TraceData object to format.

    Returns:
        Formatted summary string.
    """
    summary = trace.to_summary()
    lines = [
        f"Trace: {summary.trace_id}",
        f"  Time: {summary.timestamp.isoformat() if summary.timestamp else 'N/A'}",
        f"  Status: {summary.status or 'N/A'}",
        f"  Duration: {summary.duration_ms:.0f}ms"
        if summary.duration_ms
        else "  Duration: N/A",
        f"  Spans: {summary.total_spans}",
    ]

    if summary.root_span_name:
        lines.append(f"  Root: {summary.root_span_name}")

    if summary.tool_calls:
        lines.append(f"  Tools: {', '.join(summary.tool_calls)}")

    if summary.error_message:
        lines.append(f"  Error: {summary.error_message}")

    return "\n".join(lines)


def to_json(trace: TraceData) -> dict[str, Any]:
    """Convert trace to full JSON-serializable dict.

    Args:
        trace: TraceData object to convert.

    Returns:
        Dictionary representation of the trace.
    """
    return trace.model_dump(mode="json")


def format_traces_summary(traces: list[TraceData]) -> str:
    """Format multiple traces as summaries.

    Args:
        traces: List of TraceData objects.

    Returns:
        Formatted string with all trace summaries.
    """
    if not traces:
        return "No traces found."

    parts = [f"Found {len(traces)} trace(s):\n"]
    for i, trace in enumerate(traces, 1):
        parts.append(f"\n--- Trace {i} ---")
        parts.append(to_summary(trace))

    return "\n".join(parts)


def format_traces_json(traces: list[TraceData]) -> str:
    """Format multiple traces as JSON.

    Args:
        traces: List of TraceData objects.

    Returns:
        JSON string of all traces.
    """
    return json.dumps([to_json(t) for t in traces], indent=2, default=str)


def format_for_context(traces: list[TraceData], max_chars: int = 50000) -> str:
    """Format traces optimized for Claude's context window.

    Provides a condensed format that maximizes information density
    while staying within token limits.

    Args:
        traces: List of TraceData objects.
        max_chars: Maximum characters to output (rough token proxy).

    Returns:
        Formatted string optimized for LLM context.
    """
    if not traces:
        return "No traces found."

    output_parts = [f"# Previous Session Traces ({len(traces)} total)\n"]
    current_length = len(output_parts[0])

    for trace in traces:
        summary = trace.to_summary()

        # Build compact trace entry
        entry_lines = [
            f"\n## {summary.timestamp.strftime('%Y-%m-%d %H:%M') if summary.timestamp else 'Unknown time'}",
            f"ID: {summary.trace_id[:12]}...",
            f"Status: {summary.status or 'N/A'} | Duration: {summary.duration_ms:.0f}ms"
            if summary.duration_ms
            else f"Status: {summary.status or 'N/A'}",
        ]

        if summary.tool_calls:
            entry_lines.append(f"Tools: {', '.join(summary.tool_calls[:10])}")
            if len(summary.tool_calls) > 10:
                entry_lines[-1] += f" (+{len(summary.tool_calls) - 10} more)"

        # Add root span inputs/outputs if available
        root = trace.get_root_span()
        if root and root.inputs:
            # Truncate inputs for context
            inputs_str = str(root.inputs)[:500]
            if len(str(root.inputs)) > 500:
                inputs_str += "..."
            entry_lines.append(f"Input: {inputs_str}")

        entry = "\n".join(entry_lines)

        # Check if we'd exceed max chars
        if current_length + len(entry) > max_chars:
            output_parts.append(
                f"\n... ({len(traces) - len(output_parts) + 1} more traces truncated)"
            )
            break

        output_parts.append(entry)
        current_length += len(entry)

    return "\n".join(output_parts)


def format_tool_usage(traces: list[TraceData]) -> str:
    """Format a summary of tool usage across traces.

    Args:
        traces: List of TraceData objects.

    Returns:
        Formatted string showing tool usage statistics.
    """
    tool_counts: dict[str, int] = {}

    for trace in traces:
        for tool in trace.get_tool_calls():
            tool_counts[tool] = tool_counts.get(tool, 0) + 1

    if not tool_counts:
        return "No tool usage found in traces."

    lines = ["Tool Usage Summary:", "-" * 30]
    for tool, count in sorted(tool_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  {tool}: {count}")

    return "\n".join(lines)
