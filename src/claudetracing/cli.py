"""CLI entry point for trace retrieval."""

from datetime import datetime
from typing import Optional

import typer

app = typer.Typer(help="Claude Code MLflow tracing CLI")
enrichment_app = typer.Typer(help="Manage trace enrichments")
app.add_typer(enrichment_app, name="enrichment")


@app.command()
def init():
    """Initialize Claude Code tracing in the current project."""
    from claudetracing.setup import run_setup

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
    from claudetracing.client import TracingClient
    from claudetracing.formatters import (
        format_for_context,
        format_tool_usage,
        format_traces_json,
        format_traces_summary,
    )
    from claudetracing.setup import load_settings

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
    from claudetracing.client import TracingClient
    from claudetracing.setup import load_settings

    load_settings()  # Load .claude/settings.json env vars
    client = TracingClient()
    experiments = client.list_experiments()

    if not experiments:
        typer.echo("No experiments found.")
        return

    typer.echo("Available experiments:")
    for exp in experiments:
        typer.echo(f"  [{exp['id']}] {exp['name']}")


@enrichment_app.command("list")
def enrichment_list():
    """List available trace enrichments."""
    from claudetracing.enrichments import (
        get_active_enrichments,
        list_enrichments,
        load_settings,
    )

    enrichments = list_enrichments()
    settings = load_settings()
    active = get_active_enrichments(settings)

    typer.echo("Available enrichments:\n")
    for e in enrichments:
        status = "[active]" if e.name in active else ""
        typer.echo(f"  {e.name} {status}")
        typer.echo(f"    {e.description}\n")

    if not settings:
        typer.echo("Run 'traces init' first to enable enrichments.")


@enrichment_app.command("info")
def enrichment_info(
    name: str = typer.Argument(..., help="Enrichment name to inspect"),
):
    """Show detailed information about an enrichment."""
    from claudetracing.enrichments import (
        get_active_enrichments,
        get_enrichment,
        load_settings,
    )

    enrichment = get_enrichment(name)
    if not enrichment:
        from claudetracing.enrichments import ENRICHMENTS

        available = ", ".join(ENRICHMENTS.keys())
        typer.echo(f"Unknown enrichment '{name}'. Available: {available}", err=True)
        raise typer.Exit(1)

    settings = load_settings()
    active = get_active_enrichments(settings)
    status = "active" if name in active else "inactive"

    typer.echo(f"\n{enrichment.name} [{status}]")
    typer.echo(f"  {enrichment.description}\n")
    typer.echo("Tags added to traces:")
    for tag in enrichment.tags:
        typer.echo(f"  - {tag}")
    typer.echo()


@enrichment_app.command("add")
def enrichment_add(
    names: list[str] = typer.Argument(..., help="Enrichment name(s) to add"),
):
    """Add enrichments to the current project.

    Examples:
        traces enrichment add git
        traces enrichment add git files tokens
    """
    from claudetracing.enrichments import add_enrichments

    success, message = add_enrichments(names)
    if success:
        typer.echo(message)
    else:
        typer.echo(f"Error: {message}", err=True)
        raise typer.Exit(1)


@enrichment_app.command("remove")
def enrichment_remove(
    names: list[str] = typer.Argument(..., help="Enrichment name(s) to remove"),
):
    """Remove enrichments from the current project.

    Examples:
        traces enrichment remove git
        traces enrichment remove git files
    """
    from claudetracing.enrichments import remove_enrichments

    success, message = remove_enrichments(names)
    if success:
        typer.echo(message)
    else:
        typer.echo(f"Error: {message}", err=True)
        raise typer.Exit(1)


def main():
    app()


if __name__ == "__main__":
    main()
