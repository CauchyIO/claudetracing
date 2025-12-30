"""Interactive setup for Claude Code tracing."""

import json
import os
import subprocess
from pathlib import Path


def load_settings() -> dict | None:
    """Load settings from .claude/settings.json and set environment variables.

    Returns:
        The settings dict, or None if not found.
    """
    settings_path = Path.cwd() / ".claude" / "settings.json"
    if not settings_path.exists():
        return None

    settings = json.loads(settings_path.read_text())

    # Set environment variables from settings
    if "environment" in settings:
        for key, value in settings["environment"].items():
            os.environ[key] = value

    return settings


def prompt(message: str, default: str | None = None) -> str:
    """Prompt user for input with optional default."""
    suffix = f" [{default}]: " if default else ": "
    result = input(f"{message}{suffix}").strip()
    return result if result else (default or prompt(message, default))


def prompt_choice(message: str, choices: list[str], default: int = 0) -> int:
    """Prompt user to choose from a list. Returns index."""
    print(message)
    for i, choice in enumerate(choices):
        marker = "*" if i == default else " "
        print(f"  {marker} [{i + 1}] {choice}")

    result = input(f"Choice [1-{len(choices)}] (default: {default + 1}): ").strip()
    if not result:
        return default
    try:
        idx = int(result) - 1
        return idx if 0 <= idx < len(choices) else default
    except ValueError:
        return default


def get_databricks_profiles() -> list[dict]:
    """Get list of configured Databricks profiles from ~/.databrickscfg."""
    config_path = Path.home() / ".databrickscfg"
    if not config_path.exists():
        return []

    profiles = []
    current_profile = None
    current_host = None

    for line in config_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            if current_profile:
                profiles.append({"name": current_profile, "host": current_host})
            current_profile = line[1:-1]
            current_host = None
        elif line.startswith("host"):
            current_host = line.split("=", 1)[1].strip()

    if current_profile:
        profiles.append({"name": current_profile, "host": current_host})

    return profiles


def get_databricks_user(profile: str) -> str | None:
    """Get current user's email from Databricks."""
    try:
        result = subprocess.run(
            ["databricks", "current-user", "me", "--profile", profile, "-o", "json"],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)
        return data.get("userName") or data.get("user_name")
    except Exception:
        return None


def create_settings_file(
    profile: str | None, experiment_path: str, project_root: Path
) -> Path:
    """Create or update .claude/settings.json file.

    Merges tracing config into existing settings, preserving other hooks and env vars.

    Args:
        profile: Databricks profile name, or None for local storage
        experiment_path: MLflow experiment path/name
        project_root: Project root directory

    Returns:
        Path to the settings file
    """
    claude_dir = project_root / ".claude"
    claude_dir.mkdir(exist_ok=True)
    settings_path = claude_dir / "settings.json"

    # Tracing-specific config
    tracing_hook = {
        "type": "command",
        "command": 'uv run python -c "from mlflow.claude_code.hooks import stop_hook_handler; stop_hook_handler()"',
    }

    # Environment config depends on local vs Databricks
    if profile:
        tracing_env = {
            "MLFLOW_CLAUDE_TRACING_ENABLED": "true",
            "MLFLOW_TRACKING_URI": f"databricks://{profile}",
            "MLFLOW_EXPERIMENT_NAME": experiment_path,
            "DATABRICKS_CONFIG_PROFILE": profile,
        }
    else:
        tracing_env = {
            "MLFLOW_CLAUDE_TRACING_ENABLED": "true",
            "MLFLOW_EXPERIMENT_NAME": experiment_path,
        }

    # Load existing settings or start fresh
    if settings_path.exists():
        existing = json.loads(settings_path.read_text())
        print("Found existing settings.json, merging tracing config...")
    else:
        existing = {}

    # Merge environment variables (tracing vars override existing)
    if "environment" not in existing:
        existing["environment"] = {}
    existing["environment"].update(tracing_env)

    # Merge Stop hooks (append tracing hook to existing hooks)
    if "hooks" not in existing:
        existing["hooks"] = {}
    if "Stop" not in existing["hooks"]:
        existing["hooks"]["Stop"] = []

    # Check if tracing hook already exists anywhere in Stop hooks
    hook_command = tracing_hook["command"]
    hook_exists = any(
        hook.get("command") == hook_command
        or any(h.get("command") == hook_command for h in hook.get("hooks", []))
        for hook in existing["hooks"]["Stop"]
    )

    if not hook_exists:
        # Append to existing Stop block, or create new one if empty
        if existing["hooks"]["Stop"] and "hooks" in existing["hooks"]["Stop"][0]:
            existing["hooks"]["Stop"][0]["hooks"].append(tracing_hook)
        else:
            existing["hooks"]["Stop"] = [{"hooks": [tracing_hook]}]

    settings_path.write_text(json.dumps(existing, indent=2))
    return settings_path


def update_gitignore(project_root: Path) -> None:
    """Add Claude Code entries to .gitignore.

    Args:
        project_root: Project root directory
    """
    gitignore = project_root / ".gitignore"
    entries = [".claude/settings.local.json", ".claude/mlflow/", "mlruns/"]
    existing = gitignore.read_text() if gitignore.exists() else ""

    to_add = [e for e in entries if e not in existing]
    if to_add:
        with open(gitignore, "a") as f:
            f.write("\n# Claude Code Tracing\n" + "\n".join(to_add) + "\n")


def verify_connection(profile: str, experiment_path: str) -> bool:
    """Verify MLflow connection to Databricks.

    Args:
        profile: Databricks profile name
        experiment_path: MLflow experiment path

    Returns:
        True if connection succeeded
    """
    try:
        import mlflow

        os.environ["DATABRICKS_CONFIG_PROFILE"] = profile
        mlflow.set_tracking_uri(f"databricks://{profile}")
        mlflow.get_experiment_by_name(experiment_path)  # type: ignore[possibly-missing-attribute]
        return True
    except Exception:
        return False


def run_setup() -> int:
    """Run the interactive setup process."""
    print("\n=== Claude Code Tracing Setup ===\n")

    # Choose storage backend
    storage_type = prompt_choice(
        "Where should traces be stored?",
        [
            "Local (mlruns/ folder - no setup required)",
            "Databricks (requires workspace access)",
        ],
    )

    if storage_type == 0:
        return setup_local()
    return setup_databricks()


def setup_local() -> int:
    """Setup local MLflow storage."""
    project_root = Path.cwd()
    project_name = project_root.name

    exp_name = prompt("Experiment name", default=project_name)

    settings_path = create_settings_file(
        profile=None,
        experiment_path=exp_name,
        project_root=project_root,
    )
    print(f"Created {settings_path.relative_to(project_root)}")

    update_gitignore(project_root)
    print("Updated .gitignore")

    print("\nSetup complete! Restart Claude Code to enable tracing.")
    print("Traces will be stored locally in: mlruns/")
    return 0


def setup_databricks() -> int:
    """Setup Databricks MLflow storage."""
    # Check databricks CLI
    try:
        subprocess.run(["databricks", "--version"], capture_output=True, check=True)
    except Exception:
        print("Error: Databricks CLI not found. Install with: brew install databricks")
        return 1

    # Get or create profile
    profiles = get_databricks_profiles()

    if profiles:
        choices = [f"{p['name']} ({p['host']})" for p in profiles] + [
            "Add new workspace"
        ]
        idx = prompt_choice("Select Databricks profile:", choices)

        if idx < len(profiles):
            profile = profiles[idx]["name"]
            user = get_databricks_user(profile)
        else:
            workspace = prompt(
                "Databricks workspace URL (e.g., https://dbc-xxx.cloud.databricks.com)"
            )
            if not workspace.startswith("https://"):
                workspace = f"https://{workspace}"
            subprocess.run(
                ["databricks", "auth", "login", "--host", workspace], check=True
            )
            profile = workspace.replace("https://", "").split(".")[0]
            user = get_databricks_user(profile)
    else:
        workspace = prompt(
            "Databricks workspace URL (e.g., https://dbc-xxx.cloud.databricks.com)"
        )
        if not workspace.startswith("https://"):
            workspace = f"https://{workspace}"
        subprocess.run(["databricks", "auth", "login", "--host", workspace], check=True)
        profile = workspace.replace("https://", "").split(".")[0]
        user = get_databricks_user(profile)

    if user:
        print(f"Authenticated as: {user}")

    # Configure experiment location
    print("\nMLflow experiments are stored in Databricks Workspace folders.")
    exp_type = prompt_choice(
        "Experiment location:",
        [
            "Shared folder - visible to all workspace users (recommended)",
            f"Personal folder - only visible to you ({user or 'your account'})",
        ],
    )
    project_name = Path.cwd().name
    exp_name = prompt("Experiment name", default=project_name)

    if exp_type == 0:
        experiment_path = f"/Workspace/Shared/{exp_name}"
    else:
        if not user:
            user = prompt("Databricks email (for personal folder path)")
        experiment_path = f"/Workspace/Users/{user}/{exp_name}"

    # Verify connection BEFORE creating config
    print("\nVerifying connection to Databricks...")
    if not verify_connection(profile, experiment_path):
        print("\n" + "=" * 50)
        print("ERROR: Could not connect to Databricks!")
        print("=" * 50)
        print(f"\nProfile '{profile}' failed to authenticate.")
        print("This usually means:")
        print("  - Your token/OAuth session has expired")
        print("  - The profile doesn't have valid credentials")
        print("\nTo fix, re-authenticate with:")
        print(f"  databricks auth login --profile {profile}")
        print("\nThen run 'traces init' again.")
        return 1

    print("Connection verified!")

    # Create settings.json
    project_root = Path.cwd()
    settings_path = create_settings_file(profile, experiment_path, project_root)
    print(f"Created {settings_path.relative_to(project_root)}")

    # Update .gitignore
    update_gitignore(project_root)
    print("Updated .gitignore")

    print("\nSetup complete! Restart Claude Code to enable tracing.")
    print(f"Traces will be sent to: {experiment_path}")
    return 0
