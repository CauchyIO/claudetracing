"""Claude Code Tracing - MLflow tracing for Claude Code sessions."""

from .client import TracingClient
from .formatters import (
    format_for_context,
    format_tool_usage,
    format_traces_json,
    format_traces_summary,
    to_json,
    to_summary,
)
from .models import SpanInfo, TraceData, TraceInfo, TraceSummary
from .setup import load_settings

__all__ = [
    "TracingClient",
    "load_settings",
    "TraceData",
    "TraceInfo",
    "TraceSummary",
    "SpanInfo",
    "to_summary",
    "to_json",
    "format_traces_summary",
    "format_traces_json",
    "format_for_context",
    "format_tool_usage",
]

__version__ = "0.1.0"
