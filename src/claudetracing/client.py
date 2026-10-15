"""MLflow tracing client wrapper."""

from datetime import datetime, timedelta
import os

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import mlflow  # noqa: E402
from mlflow import MlflowClient  # noqa: E402
from mlflow.entities import Trace  # noqa: E402

from claudetracing.models import SpanInfo, TraceData, TraceInfo  # noqa: E402


class TracingClient:
    """Client for retrieving MLflow traces from Claude Code and Codex sessions."""

    def __init__(self, tracking_uri: str | None = None):
        """Initialize the tracing client.

        Args:
            tracking_uri: MLflow tracking URI. If None, uses MLFLOW_TRACKING_URI env var.
        """
        uri = tracking_uri or os.environ.get("MLFLOW_TRACKING_URI")
        if uri:
            mlflow.set_tracking_uri(uri)
        self._client = MlflowClient(tracking_uri=uri)

    def list_experiments(self) -> list[dict]:
        """List all available experiments.

        Returns:
            List of experiment info dicts with id, name, and artifact_location.
        """
        experiments = self._client.search_experiments()
        return [
            {
                "id": exp.experiment_id,
                "name": exp.name,
                "artifact_location": exp.artifact_location,
            }
            for exp in experiments
        ]

    def get_experiment_id(self, experiment_name: str) -> str | None:
        """Get experiment ID by name.

        Args:
            experiment_name: Name of the experiment.

        Returns:
            Experiment ID or None if not found.
        """
        exp = self._client.get_experiment_by_name(experiment_name)
        return exp.experiment_id if exp else None

    def resolve_locations(
        self,
        experiment_name: str | None = None,
        experiment_id: str | None = None,
    ) -> list[str] | None:
        """Resolve experiment locations from arguments or environment defaults."""
        exp_id = experiment_id
        exp_name = experiment_name

        if not exp_id and not exp_name:
            exp_id = os.environ.get("MLFLOW_EXPERIMENT_ID")
            exp_name = os.environ.get("MLFLOW_EXPERIMENT_NAME")

        if exp_name and not exp_id:
            exp_id = self.get_experiment_id(exp_name)
            if not exp_id:
                return []

        return [exp_id] if exp_id else None

    def search_traces(
        self,
        experiment_name: str | None = None,
        experiment_id: str | None = None,
        filter_string: str | None = None,
        max_results: int = 100,
        order_by: list[str] | None = None,
    ) -> list[TraceData]:
        """Search for traces in an experiment.

        Args:
            experiment_name: Name of the experiment to search.
            experiment_id: ID of the experiment (alternative to name).
            filter_string: MLflow filter string for traces.
            max_results: Maximum number of traces to return.
            order_by: List of fields to order by (e.g., ["timestamp DESC"]).

        Returns:
            List of TraceData objects.
        """
        locations = self.resolve_locations(
            experiment_name=experiment_name, experiment_id=experiment_id
        )
        if locations == []:
            return []

        traces = self._client.search_traces(
            locations=locations,
            filter_string=filter_string,
            max_results=max_results,
            order_by=order_by or ["timestamp DESC"],
        )

        return [self._convert_trace(t) for t in traces]

    def search_traces_by_time(
        self,
        experiment_name: str | None = None,
        experiment_id: str | None = None,
        hours: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        max_results: int = 100,
    ) -> list[TraceData]:
        """Search for traces within a time range."""
        if hours:
            since = datetime.now() - timedelta(hours=hours)

        filter_parts = []
        if since:
            since_ms = int(since.timestamp() * 1000)
            filter_parts.append(f"timestamp >= {since_ms}")
        if until:
            until_ms = int(until.timestamp() * 1000)
            filter_parts.append(f"timestamp <= {until_ms}")

        filter_string = " AND ".join(filter_parts) if filter_parts else None

        return self.search_traces(
            experiment_name=experiment_name,
            experiment_id=experiment_id,
            filter_string=filter_string,
            max_results=max_results,
        )

    def get_trace(self, trace_id: str) -> TraceData | None:
        """Get a single trace by ID."""
        trace = self._client.get_trace(trace_id)
        return self._convert_trace(trace) if trace else None

    def _convert_trace(self, trace: Trace) -> TraceData:
        """Convert MLflow Trace entity to TraceData model."""
        trace_id = getattr(trace.info, "trace_id", None) or trace.info.request_id or ""
        info = TraceInfo(
            trace_id=trace_id,
            request_id=trace.info.request_id,
            experiment_id=trace.info.experiment_id,
            timestamp=datetime.fromtimestamp(trace.info.timestamp_ms / 1000)
            if trace.info.timestamp_ms
            else None,
            execution_time_ms=trace.info.execution_time_ms,
            status=str(trace.info.status) if trace.info.status else None,
            tags=dict(trace.info.tags) if trace.info.tags else {},
        )

        spans = []
        if trace.data and trace.data.spans:
            for span in trace.data.spans:
                raw_inputs = span.inputs
                inputs = (
                    dict(raw_inputs)
                    if isinstance(raw_inputs, dict)
                    else (str(raw_inputs) if raw_inputs is not None else {})
                )
                raw_outputs = span.outputs
                outputs = (
                    dict(raw_outputs)
                    if isinstance(raw_outputs, dict)
                    else (str(raw_outputs) if raw_outputs is not None else {})
                )
                spans.append(
                    SpanInfo(
                        span_id=span.span_id,
                        name=span.name,
                        span_type=str(span.span_type)
                        if getattr(span, "span_type", None)
                        else None,
                        parent_id=span.parent_id,
                        start_time=datetime.fromtimestamp(span.start_time_ns / 1e9)
                        if span.start_time_ns
                        else None,
                        end_time=datetime.fromtimestamp(span.end_time_ns / 1e9)
                        if span.end_time_ns
                        else None,
                        status=str(span.status.status_code.name)
                        if getattr(span.status, "status_code", None)
                        else (str(span.status) if span.status else None),
                        inputs=inputs,
                        outputs=outputs,
                        attributes=dict(span.attributes) if span.attributes else {},
                    )
                )

        return TraceData(info=info, spans=spans)
