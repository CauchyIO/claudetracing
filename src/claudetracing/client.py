"""MLFlow tracing client wrapper."""

from datetime import datetime, timedelta

import mlflow
from mlflow import MlflowClient
from mlflow.entities import Trace

from claudetracing.models import SpanInfo, TraceData, TraceInfo


class TracingClient:
    """Client for retrieving MLFlow traces from Claude Code sessions."""

    def __init__(self, tracking_uri: str | None = None):
        """Initialize the tracing client.

        Args:
            tracking_uri: MLFlow tracking URI. If None, uses MLFLOW_TRACKING_URI env var.
        """
        if tracking_uri:
            mlflow.set_tracking_uri(tracking_uri)
        self._client = MlflowClient()

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
            filter_string: MLFlow filter string for traces.
            max_results: Maximum number of traces to return.
            order_by: List of fields to order by (e.g., ["timestamp DESC"]).

        Returns:
            List of TraceData objects.
        """
        if experiment_name and not experiment_id:
            experiment_id = self.get_experiment_id(experiment_name)
            if not experiment_id:
                return []

        locations = [experiment_id] if experiment_id else None

        traces = mlflow.search_traces(
            locations=locations,
            filter_string=filter_string,
            max_results=max_results,
            order_by=order_by or ["timestamp DESC"],
            return_type="list",
        )

        return [self._convert_trace(t) for t in traces]

    def search_traces_by_time(
        self,
        experiment_name: str | None = None,
        hours: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        max_results: int = 100,
    ) -> list[TraceData]:
        """Search for traces within a time range.

        Args:
            experiment_name: Name of the experiment.
            hours: Number of hours back from now to search.
            since: Start datetime for the search range.
            until: End datetime for the search range.
            max_results: Maximum number of traces to return.

        Returns:
            List of TraceData objects within the time range.
        """
        if hours:
            since = datetime.now() - timedelta(hours=hours)

        filter_parts = []
        if since:
            # MLFlow uses milliseconds for timestamp filters
            since_ms = int(since.timestamp() * 1000)
            filter_parts.append(f"timestamp >= {since_ms}")
        if until:
            until_ms = int(until.timestamp() * 1000)
            filter_parts.append(f"timestamp <= {until_ms}")

        filter_string = " AND ".join(filter_parts) if filter_parts else None

        return self.search_traces(
            experiment_name=experiment_name,
            filter_string=filter_string,
            max_results=max_results,
        )

    def get_trace(self, trace_id: str) -> TraceData | None:
        """Get a single trace by ID.

        Args:
            trace_id: The trace ID to retrieve.

        Returns:
            TraceData object or None if not found.
        """
        trace = self._client.get_trace(trace_id)
        return self._convert_trace(trace) if trace else None

    def _convert_trace(self, trace: Trace) -> TraceData:
        """Convert MLFlow Trace to TraceData model.

        Args:
            trace: MLFlow Trace entity.

        Returns:
            TraceData model instance.
        """
        info = TraceInfo(
            trace_id=trace.info.request_id,
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
                spans.append(
                    SpanInfo(
                        span_id=span.span_id,
                        name=span.name,
                        parent_id=span.parent_id,
                        start_time=datetime.fromtimestamp(span.start_time_ns / 1e9)
                        if span.start_time_ns
                        else None,
                        end_time=datetime.fromtimestamp(span.end_time_ns / 1e9)
                        if span.end_time_ns
                        else None,
                        status=str(span.status) if span.status else None,
                        inputs=dict(span.inputs) if span.inputs else {},
                        outputs=dict(span.outputs) if span.outputs else {},
                        attributes=dict(span.attributes) if span.attributes else {},
                    )
                )

        return TraceData(info=info, spans=spans)
