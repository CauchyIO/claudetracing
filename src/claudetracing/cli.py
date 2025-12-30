"""CLI entry point for trace retrieval."""

from datetime import datetime
from typing import Optional

import typer

from .client import TracingClient
from .formatters import (
    format_for_context,
    format_tool_usage,
    format_traces_json,
    format_traces_summary,
)
from .setup import load_settings

app = typer.Typer(help="Claude Code MLflow tracing CLI")


@app.command()
def init():
    """Initialize Claude Code tracing in the current project."""
    from .setup import run_setup

    raise SystemExit(run_setup())


@app.command()
def search(
    experiment: Optional[str] = typer.Option(
        None, "-e", "--experiment", help="Experiment name"
    ),
    limit: int = typer.Option(10, "-l", "--limit", help="Max traces to return"),
    hours: Optional[int] = typer.Option(None, help="Search last N hours"),
    since: Optional[str] = typer.Option(
        None, help="Search since datetime (ISO format)"
    ),
    format: str = typer.Option(
        "summary", "-f", "--format", help="Output: summary|json|context|tools"
    ),
    trace_id: Optional[str] = typer.Option(
        None, "--trace-id", help="Get specific trace by ID"
    ),
):
    """Search and retrieve traces."""
    load_settings()  # Load .claude/settings.json env vars
    client = TracingClient()

    if trace_id:
        trace = client.get_trace(trace_id)
        if not trace:
            typer.echo(f"Trace not found: {trace_id}", err=True)
            raise typer.Exit(1)
        traces = [trace]
    elif hours or since:
        since_dt = datetime.fromisoformat(since) if since else None
        traces = client.search_traces_by_time(
            experiment_name=experiment, hours=hours, since=since_dt, max_results=limit
        )
    else:
        traces = client.search_traces(experiment_name=experiment, max_results=limit)

    output = {
        "json": format_traces_json,
        "context": format_for_context,
        "tools": format_tool_usage,
    }.get(format, format_traces_summary)(traces)

    typer.echo(output)


@app.command("list")
def list_experiments():
    """List available experiments."""
    load_settings()  # Load .claude/settings.json env vars
    client = TracingClient()
    experiments = client.list_experiments()

    if not experiments:
        typer.echo("No experiments found.")
        return

    typer.echo("Available experiments:")
    for exp in experiments:
        typer.echo(f"  [{exp['id']}] {exp['name']}")


def main():
    app()


if __name__ == "__main__":
    main()
