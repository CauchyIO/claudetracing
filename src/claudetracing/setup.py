"""Interactive setup for Claude Code tracing."""

import json
import os
import subprocess
from pathlib import Path

# ANSI color codes
YELLOW = "\033[33m"
GREEN = "\033[32m"
CYAN = "\033[36m"
BOLD = "\033[1m"
RESET = "\033[0m"


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
        suffix = " (recommended)" if i == default else ""
        print(f"  {GREEN}[{i + 1}]{RESET} {choice}{suffix}")

    result = input(f"\nChoice [1-{len(choices)}] (default: {default + 1}): ").strip()
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
    """Get current user's email from Databricks.

    Returns None if the command fails, with a warning printed to stderr.
    """
    result = subprocess.run(
        ["databricks", "current-user", "me", "--profile", profile, "-o", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"{YELLOW}Warning: Could not get Databricks user: {result.stderr.strip()}{RESET}"
        )
        return None
    data = json.loads(result.stdout)
    return data.get("userName") or data.get("user_name")


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

    # Tracing-specific config - uses MLflow's built-in handler
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

    # Clear enrichments on init (start fresh)
    existing["environment"].pop("CLAUDETRACING_ENRICHMENTS", None)

    # Merge Stop hooks - ensure exactly one tracing hook with default command
    if "hooks" not in existing:
        existing["hooks"] = {}
    if "Stop" not in existing["hooks"]:
        existing["hooks"]["Stop"] = []

    # Remove all existing tracing hooks (mlflow or claudetracing)
    for hook_block in existing["hooks"]["Stop"]:
        if "hooks" in hook_block:
            hook_block["hooks"] = [
                h
                for h in hook_block["hooks"]
                if "mlflow" not in h.get("command", "")
                and "claudetracing" not in h.get("command", "")
            ]

    # Remove empty hook blocks
    existing["hooks"]["Stop"] = [
        hb for hb in existing["hooks"]["Stop"] if hb.get("hooks") or hb.get("command")
    ]

    # Add the default tracing hook
    if existing["hooks"]["Stop"] and "hooks" in existing["hooks"]["Stop"][0]:
        existing["hooks"]["Stop"][0]["hooks"].append(tracing_hook)
    else:
        existing["hooks"]["Stop"] = [{"hooks": [tracing_hook]}]

    settings_path.write_text(json.dumps(existing, indent=2))
    return settings_path


def update_gitignore(project_root: Path) -> bool:
    """Add Claude Code entries to .gitignore if user confirms.

    Args:
        project_root: Project root directory

    Returns:
        True if gitignore was updated, False otherwise
    """
    gitignore = project_root / ".gitignore"
    entries = [".claude/settings.local.json", ".claude/mlflow/", "mlruns/"]
    existing = gitignore.read_text() if gitignore.exists() else ""

    to_add = [e for e in entries if e not in existing]
    if not to_add:
        return False

    green = "\033[32m"
    reset = "\033[0m"
    print("\nAdd these entries to .gitignore?")
    for entry in to_add:
        print(f"  - {entry}")
    print(f"  {green}[1]{reset} Yes (recommended)")
    print(f"  {green}[2]{reset} No")

    choice = input("\nChoice [1/2] (default: 1): ").strip()
    if choice == "2":
        return False

    with open(gitignore, "a") as f:
        f.write("\n# Claude Code Tracing\n" + "\n".join(to_add) + "\n")
    return True


def verify_connection(profile: str, experiment_path: str) -> bool:
    """Verify MLflow connection to Databricks.

    Args:
        profile: Databricks profile name
        experiment_path: MLflow experiment path

    Returns:
        True if connection succeeded

    Raises:
        Any unexpected exception - only catches connection/auth failures
    """
    import signal

    import mlflow
    from mlflow import get_experiment_by_name
    from mlflow.exceptions import MlflowException

    def timeout_handler(signum, frame):
        raise TimeoutError("Connection timed out")

    try:
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(30)  # 30 second timeout

        os.environ["DATABRICKS_CONFIG_PROFILE"] = profile
        mlflow.set_tracking_uri(f"databricks://{profile}")
        get_experiment_by_name(experiment_path)

        signal.alarm(0)  # Cancel timeout
        return True
    except (TimeoutError, MlflowException, ConnectionError, OSError) as e:
        signal.alarm(0)
        print(f"Connection failed: {e}")
        return False


def _check_and_warn_enrichment_mismatch(
    experiment_path: str, profile: str | None = None
) -> tuple[bool, list[str]]:
    """Check for enrichment mismatch and prompt user.

    Args:
        experiment_path: MLflow experiment path
        profile: Databricks profile (None for local)

    Returns:
        Tuple of (continue_setup, enrichments_to_add)
    """
    from claudetracing.enrichments import detect_enrichments_from_traces

    print("Checking last 5 traces for enrichment configuration...")
    detected = detect_enrichments_from_traces(experiment_path, profile)

    if detected is None:
        # Error occurred (warning already printed) or experiment doesn't exist
        print("Could not detect existing enrichments - continuing with setup.")
        return True, []

    if len(detected) == 0:
        print("No enrichments detected in existing traces.")
        return True, []

    detected_list = sorted(detected)
    detected_str = ", ".join(detected_list)

    print(f"\n{YELLOW}{BOLD}Enrichment mismatch detected{RESET}")
    print(f"Existing traces use: {CYAN}{detected_str}{RESET}")
    print("\nOptions:")
    print(f"  {GREEN}[1]{RESET} Match existing enrichments (recommended)")
    print(f"  {GREEN}[2]{RESET} Continue without enrichments")
    print(f"  {GREEN}[3]{RESET} Cancel setup")

    choice = input("\nChoice [1/2/3] (default: 1): ").strip()

    if choice == "3":
        return False, []
    elif choice == "2":
        return True, []
    else:
        # Default to matching (option 1)
        return True, detected_list


def run_setup() -> int:
    """Run the interactive setup process."""
    print("\n=== Claude Code Tracing Setup ===\n")

    # Choose storage backend
    storage_type = prompt_choice(
        "Where should traces be stored?",
        [
            "Databricks (requires workspace access)",
            "Local (mlruns/ folder - no setup required)",
        ],
    )

    if storage_type == 0:
        return setup_databricks()
    return setup_local()


def setup_local() -> int:
    """Setup local MLflow storage."""
    project_root = Path.cwd()
    project_name = project_root.name

    exp_name = prompt("Experiment name", default=project_name)

    # Check for enrichment consistency with existing traces
    continue_setup, enrichments_to_add = _check_and_warn_enrichment_mismatch(
        exp_name, profile=None
    )
    if not continue_setup:
        print("Setup cancelled.")
        return 1

    settings_path = create_settings_file(
        profile=None,
        experiment_path=exp_name,
        project_root=project_root,
    )
    print(f"Created {settings_path.relative_to(project_root)}")

    # Add enrichments if user chose to match
    if enrichments_to_add:
        from claudetracing.enrichments import add_enrichments

        success, msg = add_enrichments(enrichments_to_add, project_root)
        if success:
            print(f"Enabled enrichments: {', '.join(enrichments_to_add)}")

    if update_gitignore(project_root):
        print("Updated .gitignore")

    print("\nSetup complete! Restart Claude Code to enable tracing.")
    print("Traces will be stored locally in: mlruns/")
    return 0


def _authenticate_new_workspace() -> tuple[str, str | None]:
    """Prompt for workspace URL, authenticate, and return (profile, user)."""
    workspace = prompt(
        "Databricks workspace URL (e.g., https://dbc-xxx.cloud.databricks.com)"
    )
    if not workspace.startswith("https://"):
        workspace = f"https://{workspace}"
    subprocess.run(["databricks", "auth", "login", "--host", workspace], check=True)
    profile = workspace.replace("https://", "").split(".")[0]
    return profile, get_databricks_user(profile)


def setup_databricks() -> int:
    """Setup Databricks MLflow storage."""
    # Check databricks CLI
    try:
        subprocess.run(["databricks", "--version"], capture_output=True, check=True)
    except FileNotFoundError:
        print("Error: Databricks CLI not found. Install with: brew install databricks")
        return 1

    # Get or create profile
    profiles = get_databricks_profiles()

    if not profiles:
        profile, user = _authenticate_new_workspace()
    else:
        choices = [f"{p['name']} ({p['host']})" for p in profiles] + [
            "Add new workspace"
        ]
        idx = prompt_choice("Select Databricks profile:", choices)

        if idx < len(profiles):
            profile = profiles[idx]["name"]
            user = get_databricks_user(profile)
        else:
            profile, user = _authenticate_new_workspace()

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

    # Check for enrichment consistency with existing traces
    continue_setup, enrichments_to_add = _check_and_warn_enrichment_mismatch(
        experiment_path, profile
    )
    if not continue_setup:
        print("Setup cancelled.")
        return 1

    # Create settings.json
    project_root = Path.cwd()
    settings_path = create_settings_file(profile, experiment_path, project_root)
    print(f"Created {settings_path.relative_to(project_root)}")

    # Add enrichments if user chose to match
    if enrichments_to_add:
        from claudetracing.enrichments import add_enrichments

        success, msg = add_enrichments(enrichments_to_add, project_root)
        if success:
            print(f"Enabled enrichments: {', '.join(enrichments_to_add)}")

    # Update .gitignore
    if update_gitignore(project_root):
        print("Updated .gitignore")

    print("\nSetup complete! Restart Claude Code to enable tracing.")
    print(f"Traces will be sent to: {experiment_path}")
    return 0
