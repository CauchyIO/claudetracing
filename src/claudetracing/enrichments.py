"""Enrichment registry for Claude Code traces.

Enrichments add additional metadata to traces. Multiple enrichments can be
active simultaneously. They are stored in .claude/settings.json and applied
via a composite hook handler.
"""

import json
from pathlib import Path

from pydantic import BaseModel, Field

# Key in settings.json environment to store active enrichments
ENRICHMENTS_ENV_KEY = "CLAUDETRACING_ENRICHMENTS"


class Enrichment(BaseModel):
    """Definition of a trace enrichment."""

    name: str
    description: str
    tags: list[str] = Field(default_factory=list)


# Registry of available enrichments
ENRICHMENTS: dict[str, Enrichment] = {
    "git": Enrichment(
        name="git",
        description="Adds git repository context to traces",
        tags=[
            "git.commit_id - Full commit SHA at session start",
            "git.branch - Current branch name",
            "git.remote_url - Origin remote URL",
        ],
    ),
    "files": Enrichment(
        name="files",
        description="Adds list of files modified during the session",
        tags=[
            "files.modified - JSON array of filenames written or edited (truncated to fit)",
            "files.count - Total number of unique files modified",
        ],
    ),
    "tokens": Enrichment(
        name="tokens",
        description="Adds token usage statistics including cache metrics",
        tags=[
            "tokens.input - Total input tokens",
            "tokens.output - Total output tokens",
            "tokens.cache_read - Tokens read from cache",
            "tokens.cache_creation - Tokens written to cache",
            "tokens.total - Total tokens (input + output)",
        ],
    ),
}

# The default MLflow hook command (no enrichment)
DEFAULT_HOOK_COMMAND = 'uv run python -c "from mlflow.claude_code.hooks import stop_hook_handler; stop_hook_handler()"'

# Enriched hook command (handles all active enrichments)
ENRICHED_HOOK_COMMAND = 'uv run python -c "from claudetracing.hooks import enriched_stop_hook_handler; enriched_stop_hook_handler()"'


def list_enrichments() -> list[Enrichment]:
    """Return all available enrichments."""
    return list(ENRICHMENTS.values())


def get_enrichment(name: str) -> Enrichment | None:
    """Get an enrichment by name."""
    return ENRICHMENTS.get(name)


def get_settings_path(project_root: Path | None = None) -> Path:
    """Get the path to .claude/settings.json."""
    root = project_root or Path.cwd()
    return root / ".claude" / "settings.json"


def load_settings(project_root: Path | None = None) -> dict | None:
    """Load settings from .claude/settings.json."""
    settings_path = get_settings_path(project_root)
    if not settings_path.exists():
        return None
    return json.loads(settings_path.read_text())


def save_settings(settings: dict, project_root: Path | None = None) -> Path:
    """Save settings to .claude/settings.json."""
    settings_path = get_settings_path(project_root)
    settings_path.parent.mkdir(exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2))
    return settings_path


def get_active_enrichments(settings: dict | None) -> list[str]:
    """Get list of currently active enrichment names from settings."""
    if not settings:
        return []
    env = settings.get("environment", {})
    enrichments_str = env.get(ENRICHMENTS_ENV_KEY, "")
    if not enrichments_str:
        return []
    return [e.strip() for e in enrichments_str.split(",") if e.strip()]


def _set_active_enrichments(settings: dict, enrichments: list[str]) -> dict:
    """Set the active enrichments in settings."""
    if "environment" not in settings:
        settings["environment"] = {}

    if enrichments:
        settings["environment"][ENRICHMENTS_ENV_KEY] = ",".join(enrichments)
    elif ENRICHMENTS_ENV_KEY in settings["environment"]:
        del settings["environment"][ENRICHMENTS_ENV_KEY]

    return settings


def _update_hook_command(settings: dict, use_enriched: bool) -> dict:
    """Update the hook command based on whether enrichments are active."""
    target_command = ENRICHED_HOOK_COMMAND if use_enriched else DEFAULT_HOOK_COMMAND

    hooks = settings.get("hooks", {}).get("Stop", [])
    for hook_block in hooks:
        if "hooks" in hook_block:
            for hook in hook_block["hooks"]:
                cmd = hook.get("command", "")
                if "mlflow" in cmd or "claudetracing" in cmd:
                    hook["command"] = target_command
                    return settings
        cmd = hook_block.get("command", "")
        if "mlflow" in cmd or "claudetracing" in cmd:
            hook_block["command"] = target_command
            return settings

    return settings


def add_enrichments(
    names: list[str], project_root: Path | None = None
) -> tuple[bool, str]:
    """Add one or more enrichments to the current project.

    Returns:
        Tuple of (success, message)
    """
    # Validate all names first
    invalid = [n for n in names if n not in ENRICHMENTS]
    if invalid:
        available = ", ".join(ENRICHMENTS.keys())
        return (
            False,
            f"Unknown enrichment(s): {', '.join(invalid)}. Available: {available}",
        )

    settings = load_settings(project_root)
    if not settings:
        return False, "No .claude/settings.json found. Run 'traces init' first."

    # Get current and merge
    current = set(get_active_enrichments(settings))
    already_active = [n for n in names if n in current]
    to_add = [n for n in names if n not in current]

    if not to_add:
        return False, f"Already active: {', '.join(already_active)}"

    # Update settings
    new_enrichments = sorted(current | set(to_add))
    settings = _set_active_enrichments(settings, new_enrichments)
    settings = _update_hook_command(settings, use_enriched=True)
    save_settings(settings, project_root)

    msg = f"Added: {', '.join(to_add)}"
    if already_active:
        msg += f" (already active: {', '.join(already_active)})"
    msg += ". Restart Claude Code to apply."
    return True, msg


def remove_enrichments(
    names: list[str], project_root: Path | None = None
) -> tuple[bool, str]:
    """Remove one or more enrichments from the current project.

    Returns:
        Tuple of (success, message)
    """
    # Validate all names first
    invalid = [n for n in names if n not in ENRICHMENTS]
    if invalid:
        available = ", ".join(ENRICHMENTS.keys())
        return (
            False,
            f"Unknown enrichment(s): {', '.join(invalid)}. Available: {available}",
        )

    settings = load_settings(project_root)
    if not settings:
        return False, "No .claude/settings.json found. Run 'traces init' first."

    # Get current and remove
    current = set(get_active_enrichments(settings))
    not_active = [n for n in names if n not in current]
    to_remove = [n for n in names if n in current]

    if not to_remove:
        return False, f"Not currently active: {', '.join(not_active)}"

    # Update settings
    new_enrichments = sorted(current - set(to_remove))
    settings = _set_active_enrichments(settings, new_enrichments)
    settings = _update_hook_command(settings, use_enriched=bool(new_enrichments))
    save_settings(settings, project_root)

    msg = f"Removed: {', '.join(to_remove)}"
    if not_active:
        msg += f" (not active: {', '.join(not_active)})"
    msg += ". Restart Claude Code to apply."
    return True, msg


def detect_enrichments_from_traces(
    experiment_name: str, profile: str | None = None, max_traces: int = 5
) -> set[str] | None:
    """Detect which enrichments are in use by analyzing existing traces.

    Args:
        experiment_name: MLflow experiment name/path
        profile: Databricks profile (None for local)
        max_traces: Number of recent traces to sample

    Returns:
        Set of detected enrichment names, or None if experiment not found or error
    """
    import os

    import mlflow
    from mlflow.exceptions import MlflowException
    from mlflow.tracking import MlflowClient

    # Configure MLflow
    if profile:
        os.environ["DATABRICKS_CONFIG_PROFILE"] = profile
        mlflow.set_tracking_uri(f"databricks://{profile}")

    try:
        client = MlflowClient()
        experiment = client.get_experiment_by_name(experiment_name)
        if not experiment:
            return None

        traces = client.search_traces(
            locations=[experiment.experiment_id],
            max_results=max_traces,
        )
    except (MlflowException, ConnectionError, OSError) as e:
        # Print warning for connection/API failures during setup
        print(f"\033[33mWarning: Could not check existing traces: {e}\033[0m")
        return None

    if not traces:
        # Experiment exists but has no traces yet
        return set()

    # Detect enrichments from trace tags
    detected: set[str] = set()
    traces_with_tags = 0
    for trace in traces:
        tags = trace.info.tags or {}
        if tags:
            traces_with_tags += 1
        if any(k.startswith("git.") for k in tags):
            detected.add("git")
        if any(k.startswith("files.") for k in tags):
            detected.add("files")
        if any(k.startswith("tokens.") for k in tags):
            detected.add("tokens")

    # Warn if we got traces but none had tags - likely a data download issue
    if traces and traces_with_tags == 0:
        print(
            "\033[33mWarning: Found traces but none had readable tags. "
            "Detection may be unreliable.\033[0m"
        )
        return None  # Signal unreliable detection

    return detected


class EnrichmentMismatch(BaseModel):
    """Result of enrichment consistency check."""

    detected: set[str]
    local: set[str]

    @property
    def missing_locally(self) -> set[str]:
        """Enrichments used in traces but not configured locally."""
        return self.detected - self.local

    @property
    def extra_locally(self) -> set[str]:
        """Enrichments configured locally but not in existing traces."""
        return self.local - self.detected


def check_enrichment_consistency(
    experiment_name: str,
    local_enrichments: list[str],
    profile: str | None = None,
) -> EnrichmentMismatch | None:
    """Check if local enrichment config matches what's in existing traces.

    Args:
        experiment_name: MLflow experiment name/path
        local_enrichments: List of locally configured enrichments
        profile: Databricks profile (None for local)

    Returns:
        EnrichmentMismatch if there's a discrepancy, None if consistent or no traces
    """
    detected = detect_enrichments_from_traces(experiment_name, profile)
    if detected is None:
        return None  # No traces yet, nothing to compare

    local = set(local_enrichments)
    if detected == local:
        return None  # Consistent

    return EnrichmentMismatch(detected=detected, local=local)
