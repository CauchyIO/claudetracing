"""Pydantic models for MLFlow trace data."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SpanInfo(BaseModel):
    """Information about a single span within a trace."""

    span_id: str
    name: str
    parent_id: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    status: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @property
    def duration_ms(self) -> float | None:
        """Calculate span duration in milliseconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds() * 1000
        return None


class TraceInfo(BaseModel):
    """Metadata about a trace."""

    trace_id: str
    request_id: str | None = None
    experiment_id: str | None = None
    timestamp: datetime | None = None
    execution_time_ms: float | None = None
    status: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class TraceSummary(BaseModel):
    """Condensed summary of a trace for quick overview."""

    trace_id: str
    timestamp: datetime | None = None
    status: str | None = None
    total_spans: int = 0
    duration_ms: float | None = None
    root_span_name: str | None = None
    tool_calls: list[str] = Field(default_factory=list)
    error_message: str | None = None


class TraceData(BaseModel):
    """Complete trace data including info and spans."""

    info: TraceInfo
    spans: list[SpanInfo] = Field(default_factory=list)

    def get_root_span(self) -> SpanInfo | None:
        """Get the root span (span with no parent)."""
        for span in self.spans:
            if span.parent_id is None:
                return span
        return None

    def get_tool_calls(self) -> list[str]:
        """Extract names of tool call spans."""
        return [
            span.name
            for span in self.spans
            if "tool" in span.name.lower() or span.attributes.get("span_type") == "tool"
        ]

    def to_summary(self) -> TraceSummary:
        """Convert to a condensed summary."""
        root = self.get_root_span()
        return TraceSummary(
            trace_id=self.info.trace_id,
            timestamp=self.info.timestamp,
            status=self.info.status,
            total_spans=len(self.spans),
            duration_ms=self.info.execution_time_ms,
            root_span_name=root.name if root else None,
            tool_calls=self.get_tool_calls(),
        )
