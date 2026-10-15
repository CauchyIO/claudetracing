"""CLI entry point for Claude Code, Codex, Copilot, and Antigravity (agy) MLflow tracing."""

from datetime import datetime
from pathlib import Path
from typing import cast

import typer

from claudetracing import __version__

app = typer.Typer(
    help="Standardized MLflow tracing setup and CLI for Claude Code, Codex, GitHub Copilot, and Antigravity (agy)"
)
codex_app = typer.Typer(help="Configure Codex CLI tracing (@mlflow/codex conventions)")
app.add_typer(codex_app, name="codex")
copilot_app = typer.Typer(help="Configure GitHub Copilot (CLI / VS Code) tracing")
app.add_typer(copilot_app, name="copilot")
agy_app = typer.Typer(help="Configure Google Antigravity (agy) tracing")
app.add_typer(agy_app, name="agy")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"claudetracing {__version__}")
        raise typer.Exit()


@app.callback()
def _main_callback(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the claudetracing version and exit.",
    ),
) -> None:
    """Standardized MLflow tracing setup and CLI for coding agents."""


@app.command("version")
def version_cmd() -> None:
    """Show the claudetracing version."""
    typer.echo(f"claudetracing {__version__}")


@app.command()
def init(
    agent: str | None = typer.Option(
        None,
        "--agent",
        "-a",
        help="Agent(s) to configure: 'all', 'both', 'claude', 'codex', 'copilot', or 'agy' (prompted if omitted).",
    ),
    tracking_uri: str | None = typer.Option(
        None,
        "--tracking-uri",
        "-u",
        help="MLflow tracking URI (e.g., 'databricks', 'http://localhost:5000', 'https://mlflow.example.com').",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        "-p",
        help="Databricks CLI/OAuth profile from ~/.databrickscfg.",
    ),
    spn: bool = typer.Option(
        False,
        "--spn",
        help="Configure headless service-principal auth (credentials come from DATABRICKS_HOST/CLIENT_ID/CLIENT_SECRET).",
    ),
    experiment: str | None = typer.Option(
        None,
        "--experiment",
        "-e",
        help="MLflow experiment name or Databricks workspace path.",
    ),
    experiment_id: str | None = typer.Option(
        None,
        "--experiment-id",
        help="Explicit MLflow experiment ID.",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        help="Bearer token (MLFLOW_TRACKING_TOKEN) for a self-hosted MLflow server.",
    ),
    trace_location: str | None = typer.Option(
        None,
        "--trace-location",
        help="Optional Unity Catalog trace location in 'catalog.schema.table_prefix' format.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip interactive prompts and use supplied flags or defaults.",
    ),
):
    """Initialize MLflow tracing for coding agents in the current project."""
    from claudetracing.setup import VALID_AGENTS, AgentChoice, run_setup

    normalized_agent = agent
    if normalized_agent == "ghcp":
        normalized_agent = "copilot"
    elif normalized_agent == "antigravity":
        normalized_agent = "agy"

    if normalized_agent is not None and normalized_agent not in VALID_AGENTS:
        raise typer.BadParameter(
            f"Invalid --agent value. Choose from: {', '.join(VALID_AGENTS)}"
        )

    raise SystemExit(
        run_setup(
            spn=spn,
            agent=cast(AgentChoice | None, normalized_agent),
            tracking_uri=tracking_uri,
            profile=profile,
            experiment=experiment,
            experiment_id=experiment_id,
            tracking_token=token,
            trace_location=trace_location,
            yes=yes,
        )
    )


def _single_agent_init(
    target_agent: str,
    label: str,
    target_dir_desc: str,
    experiment: str | None,
    experiment_id: str | None,
    tracking_uri: str | None,
    profile: str | None,
    trace_location: str | None,
    yes: bool,
    *,
    token: str | None = None,
    spn: bool = False,
) -> None:
    from claudetracing.setup import LOCAL_DEFAULT_URI, AgentChoice, run_setup

    if profile and tracking_uri:
        raise typer.BadParameter("Use --profile or --tracking-uri, not both")

    uri = None if profile else (tracking_uri or LOCAL_DEFAULT_URI)
    exp = experiment or Path.cwd().resolve().name
    if not yes:
        target_uri = f"databricks://{profile}" if profile else uri
        typer.echo(
            f"Project: {Path.cwd().resolve()}\nExperiment: {exp}\nTracking URI: {target_uri}"
        )
        typer.confirm(f"Configure {label} tracing in {target_dir_desc}?", abort=True)

    raise SystemExit(
        run_setup(
            spn=spn,
            agent=cast(AgentChoice, target_agent),
            tracking_uri=uri,
            profile=profile,
            experiment=exp,
            experiment_id=experiment_id,
            tracking_token=token,
            trace_location=trace_location,
            yes=yes,
        )
    )


@codex_app.command("init")
def codex_init(
    experiment: str | None = typer.Option(
        None, "--experiment", "-e", help="MLflow experiment name/path"
    ),
    experiment_id: str | None = typer.Option(
        None, "--experiment-id", help="Explicit MLflow experiment ID"
    ),
    tracking_uri: str | None = typer.Option(
        None,
        "--tracking-uri",
        "-u",
        help="MLflow tracking URI (defaults to http://localhost:5000)",
    ),
    profile: str | None = typer.Option(
        None, "--profile", "-p", help="Databricks OAuth/CLI profile"
    ),
    trace_location: str | None = typer.Option(
        None,
        "--trace-location",
        help="Unity Catalog trace location (catalog.schema.table_prefix)",
    ),
    token: str | None = typer.Option(
        None, "--token", help="Bearer token (MLFLOW_TRACKING_TOKEN)"
    ),
    spn: bool = typer.Option(
        False, "--spn", help="Configure headless service-principal auth"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip interactive confirmation"
    ),
):
    """Configure Codex CLI tracing (.codex/config.toml and .codex/mlflow-tracing.json)."""
    _single_agent_init(
        "codex",
        "Codex",
        "./.codex/",
        experiment,
        experiment_id,
        tracking_uri,
        profile,
        trace_location,
        yes,
        token=token,
        spn=spn,
    )


@copilot_app.command("init")
def copilot_init(
    experiment: str | None = typer.Option(
        None, "--experiment", "-e", help="MLflow experiment name/path"
    ),
    experiment_id: str | None = typer.Option(
        None, "--experiment-id", help="Explicit MLflow experiment ID"
    ),
    tracking_uri: str | None = typer.Option(
        None,
        "--tracking-uri",
        "-u",
        help="MLflow tracking URI (defaults to http://localhost:5000)",
    ),
    profile: str | None = typer.Option(
        None, "--profile", "-p", help="Databricks OAuth/CLI profile"
    ),
    token: str | None = typer.Option(
        None, "--token", help="Bearer token (MLFLOW_TRACKING_TOKEN)"
    ),
    spn: bool = typer.Option(
        False, "--spn", help="Configure headless service-principal auth"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip interactive confirmation"
    ),
):
    """Configure GitHub Copilot tracing (.github/hooks/mlflow-tracing.json)."""
    _single_agent_init(
        "copilot",
        "GitHub Copilot",
        "./.github/hooks/",
        experiment,
        experiment_id,
        tracking_uri,
        profile,
        None,
        yes,
        token=token,
        spn=spn,
    )


@agy_app.command("init")
def agy_init(
    experiment: str | None = typer.Option(
        None, "--experiment", "-e", help="MLflow experiment name/path"
    ),
    experiment_id: str | None = typer.Option(
        None, "--experiment-id", help="Explicit MLflow experiment ID"
    ),
    tracking_uri: str | None = typer.Option(
        None,
        "--tracking-uri",
        "-u",
        help="MLflow tracking URI (defaults to http://localhost:5000)",
    ),
    profile: str | None = typer.Option(
        None, "--profile", "-p", help="Databricks OAuth/CLI profile"
    ),
    token: str | None = typer.Option(
        None, "--token", help="Bearer token (MLFLOW_TRACKING_TOKEN)"
    ),
    spn: bool = typer.Option(
        False, "--spn", help="Configure headless service-principal auth"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip interactive confirmation"
    ),
):
    """Configure Google Antigravity (agy) tracing (.agents/hooks.json and .agents/mlflow-tracing.json)."""
    _single_agent_init(
        "agy",
        "Antigravity (agy)",
        "./.agents/",
        experiment,
        experiment_id,
        tracking_uri,
        profile,
        None,
        yes,
        token=token,
        spn=spn,
    )


@app.command("copilot-hook", hidden=True)
def copilot_hook_cmd(
    event: str = typer.Argument("stop", help="Hook event: 'stop' or 'session-start'"),
):
    """Internal hook handler invoked by GitHub Copilot (.github/hooks/mlflow-tracing.json)."""
    from claudetracing.copilot import run_copilot_session_start, run_copilot_stop

    if event == "session-start":
        run_copilot_session_start()
    else:
        run_copilot_stop()


@app.command("agy-hook", hidden=True)
def agy_hook_cmd():
    """Internal hook handler invoked by Google Antigravity (.agents/hooks.json)."""
    from claudetracing.agy import run_agy_stop

    run_agy_stop()


@app.command()
def status():
    """Show current MLflow tracing status for Claude Code, Codex, Copilot, and Antigravity (agy)."""
    from claudetracing.setup import get_all_agent_statuses

    root = Path.cwd().resolve()
    claude_st, codex_st, copilot_st, agy_st = get_all_agent_statuses(root)

    typer.echo(f"Project: {root}\n")

    if claude_st["enabled"]:
        typer.echo("Claude Code: enabled")
        typer.echo(f"  Tracking URI: {claude_st['tracking_uri']}")
        if claude_st["profile"]:
            typer.echo(f"  Databricks profile: {claude_st['profile']} (via .local)")
        if claude_st["experiment_name"]:
            typer.echo(f"  Experiment name: {claude_st['experiment_name']}")
        if claude_st["experiment_id"]:
            typer.echo(f"  Experiment ID: {claude_st['experiment_id']}")
        if claude_st["trace_location"]:
            typer.echo(f"  Trace location: {claude_st['trace_location']}")
    else:
        typer.echo("Claude Code: not configured")

    typer.echo("")
    if codex_st.enabled:
        typer.echo(f"Codex: enabled ({codex_st.scope} scope)")
        typer.echo(f"  Tracking URI: {codex_st.tracking_uri}")
        typer.echo(f"  Experiment ID: {codex_st.experiment_id}")
        if codex_st.trace_location:
            typer.echo(f"  Trace location: {codex_st.trace_location}")
        if not codex_st.binary_installed:
            typer.echo(
                "  Warning: `mlflow-codex` not found on PATH (run `npm install -g @mlflow/codex`)"
            )
    else:
        typer.echo("Codex: not configured")

    typer.echo("")
    if copilot_st.enabled:
        typer.echo("GitHub Copilot: enabled")
        typer.echo(f"  Tracking URI: {copilot_st.tracking_uri}")
        if copilot_st.experiment_name:
            typer.echo(f"  Experiment name: {copilot_st.experiment_name}")
        if copilot_st.experiment_id:
            typer.echo(f"  Experiment ID: {copilot_st.experiment_id}")
    else:
        typer.echo("GitHub Copilot: not configured")

    typer.echo("")
    if agy_st.enabled:
        typer.echo("Antigravity (agy): enabled")
        typer.echo(f"  Tracking URI: {agy_st.tracking_uri}")
        if agy_st.experiment_name:
            typer.echo(f"  Experiment name: {agy_st.experiment_name}")
        if agy_st.experiment_id:
            typer.echo(f"  Experiment ID: {agy_st.experiment_id}")
    else:
        typer.echo("Antigravity (agy): not configured")


@app.command()
def disable():
    """Disable MLflow tracing for all coding agents in the current project."""
    from claudetracing.setup import disable_all_project_tracing

    removed = disable_all_project_tracing(Path.cwd().resolve())
    if not any(removed.values()):
        typer.echo("No tracing configuration found in this project.")
        return

    if removed["claude"]:
        typer.echo("Disabled Claude Code tracing.")
    if removed["codex"]:
        typer.echo("Disabled Codex tracing.")
    if removed["copilot"]:
        typer.echo("Disabled GitHub Copilot tracing.")
    if removed["agy"]:
        typer.echo("Disabled Antigravity (agy) tracing.")


@app.command()
def search(
    experiment: str | None = typer.Option(
        None, "-e", "--experiment", help="Experiment name"
    ),
    experiment_id: str | None = typer.Option(
        None, "--experiment-id", help="Experiment ID"
    ),
    limit: int = typer.Option(10, "-l", "--limit", help="Max traces to return"),
    hours: int | None = typer.Option(None, help="Search last N hours"),
    since: str | None = typer.Option(None, help="Search since datetime (ISO format)"),
    format: str = typer.Option(
        "summary", "-f", "--format", help="Output: summary|json|context|tools"
    ),
    trace_id: str | None = typer.Option(
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
    from claudetracing.setup import load_tracing_env

    formatters = {
        "summary": format_traces_summary,
        "json": format_traces_json,
        "context": format_for_context,
        "tools": format_tool_usage,
    }
    if format not in formatters:
        raise typer.BadParameter(
            f"Invalid format '{format}'. Choose from: summary, json, context, tools."
        )

    load_tracing_env()
    client = TracingClient()

    if trace_id:
        trace = client.get_trace(trace_id)
        if not trace:
            typer.echo(f"Trace not found: {trace_id}", err=True)
            raise typer.Exit(1)
        traces = [trace]
    elif hours or since:
        normalized_since = (
            since[:-1] + "+00:00" if since and since.endswith("Z") else since
        )
        since_dt = (
            datetime.fromisoformat(normalized_since) if normalized_since else None
        )
        traces = client.search_traces_by_time(
            experiment_name=experiment,
            experiment_id=experiment_id,
            hours=hours,
            since=since_dt,
            max_results=limit,
        )
    else:
        traces = client.search_traces(
            experiment_name=experiment,
            experiment_id=experiment_id,
            max_results=limit,
        )

    output = formatters[format](traces)

    typer.echo(output)


@app.command("list")
def list_experiments():
    """List available experiments."""
    from claudetracing.client import TracingClient
    from claudetracing.setup import load_tracing_env

    load_tracing_env()
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
