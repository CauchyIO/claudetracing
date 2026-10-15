"""Interactive and non-interactive setup for Claude Code, Codex, Copilot, and Antigravity (agy) MLflow tracing."""

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Literal
from urllib.parse import urlparse

from claudetracing.agy import (
    AgyTracingStatus,
    agy_tracing_config_path,
    configure_agy,
    disable_agy,
    get_agy_status,
)
from claudetracing.codex import (
    CodexStatus,
    configure_codex,
    disable_codex,
    get_codex_status,
    is_mlflow_codex_installed,
    load_codex_tracing_config,
)
from claudetracing.copilot import (
    CopilotTracingStatus,
    configure_copilot,
    copilot_config_path,
    copilot_local_config_path,
    disable_copilot,
    get_copilot_status,
)

# ANSI color codes
YELLOW = "\033[33m"
GREEN = "\033[32m"
CYAN = "\033[36m"
BOLD = "\033[1m"
RESET = "\033[0m"

ENV_KEY = "env"
LEGACY_ENV_KEY = "environment"
LOCAL_DEFAULT_URI = "http://localhost:5000"
MLFLOW_CLAUDE_PLUGIN_ID = "mlflow-tracing@mlflow-plugins"

AgentChoice = Literal["all", "both", "claude", "codex", "copilot", "agy"]
VALID_AGENTS: tuple[str, ...] = ("all", "both", "claude", "codex", "copilot", "agy")


def _extract_env_dict(data: dict) -> dict[str, str]:
    """Read environment variables from a Claude settings dict ('env' or legacy 'environment')."""
    merged: dict[str, str] = {}
    for key in (LEGACY_ENV_KEY, ENV_KEY):
        block = data.get(key)
        if isinstance(block, dict):
            merged.update({str(k): str(v) for k, v in block.items()})
    return merged


def load_tracing_env(project_root: Path | None = None) -> None:
    """Populate os.environ with tracing settings from the project's agent configs.

    Precedence (highest first):
      1. Existing os.environ
      2. .claude/settings.local.json ('env', fallback 'environment')
      3. .claude/settings.json ('env', fallback 'environment')
      4. .github/hooks/mlflow-tracing.local.json & .github/hooks/mlflow-tracing.json
      5. .agents/mlflow-tracing.json
      6. .codex/mlflow-tracing.json (or ~/.codex/mlflow-tracing.json)
    """
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    root = Path(project_root).resolve() if project_root else Path.cwd().resolve()

    merged: dict[str, str] = {}

    # 6. Codex tracing config
    codex_cfg, _, _ = load_codex_tracing_config(root)
    if codex_cfg is not None:
        if codex_cfg.tracking_uri:
            merged["MLFLOW_TRACKING_URI"] = codex_cfg.tracking_uri
        if codex_cfg.experiment_id:
            merged["MLFLOW_EXPERIMENT_ID"] = codex_cfg.experiment_id
        if codex_cfg.trace_location:
            merged["MLFLOW_TRACE_LOCATION"] = codex_cfg.trace_location

    # 5. Antigravity (.agents/mlflow-tracing.json)
    agy_cfg_file = agy_tracing_config_path(root)
    if agy_cfg_file.exists():
        try:
            agy_raw = json.loads(agy_cfg_file.read_text(encoding="utf-8"))
            if isinstance(agy_raw, dict):
                merged["MLFLOW_CLAUDE_TRACING_ENABLED"] = "true"
                if agy_raw.get("trackingUri"):
                    merged["MLFLOW_TRACKING_URI"] = str(agy_raw["trackingUri"])
                if agy_raw.get("experimentId"):
                    merged["MLFLOW_EXPERIMENT_ID"] = str(agy_raw["experimentId"])
                if agy_raw.get("experimentName"):
                    merged["MLFLOW_EXPERIMENT_NAME"] = str(agy_raw["experimentName"])
                if agy_raw.get("trackingToken"):
                    merged["MLFLOW_TRACKING_TOKEN"] = str(agy_raw["trackingToken"])
        except (json.JSONDecodeError, OSError):
            pass

    # 4. GitHub Copilot (.github/hooks/mlflow-tracing.json + .local.json)
    cp_cfg_file = copilot_config_path(root)
    if cp_cfg_file.exists():
        try:
            cp_data = json.loads(cp_cfg_file.read_text(encoding="utf-8"))
            for h in cp_data.get("hooks", {}).get("Stop", []):
                if isinstance(h, dict) and isinstance(h.get("env"), dict):
                    merged.update({str(k): str(v) for k, v in h["env"].items()})
        except (json.JSONDecodeError, OSError):
            pass
    cp_local_file = copilot_local_config_path(root)
    if cp_local_file.exists():
        try:
            cp_local = json.loads(cp_local_file.read_text(encoding="utf-8"))
            if isinstance(cp_local.get("env"), dict):
                merged.update({str(k): str(v) for k, v in cp_local["env"].items()})
        except (json.JSONDecodeError, OSError):
            pass

    # 3 & 2. Claude Code (.claude/settings.json then .claude/settings.local.json)
    for name in ("settings.json", "settings.local.json"):
        path = root / ".claude" / name
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        merged.update(_extract_env_dict(data))

    uri_val = merged.get("MLFLOW_TRACKING_URI", "")
    if uri_val.startswith("databricks://"):
        extracted_prof = uri_val.removeprefix("databricks://").strip("/")
        if extracted_prof:
            merged.setdefault("DATABRICKS_CONFIG_PROFILE", extracted_prof)

    for key, value in merged.items():
        os.environ.setdefault(key, value)


def load_settings(project_root: Path | None = None) -> dict | None:
    """Load .claude/settings.json and populate tracing environment variables."""
    root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    settings_path = root / ".claude" / "settings.json"
    load_tracing_env(root)
    if not settings_path.exists():
        return None
    return json.loads(settings_path.read_text(encoding="utf-8"))


def is_valid_http_uri(uri: str) -> bool:
    """Return True if uri is a valid http:// or https:// URL with a host."""
    try:
        parsed = urlparse(uri.strip())
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def is_valid_tracking_uri(uri: str) -> bool:
    """Return True if uri is a valid MLflow tracking URI ('databricks', 'databricks://...', or http/https)."""
    cleaned = uri.strip()
    if cleaned == "databricks" or cleaned.startswith("databricks://"):
        return True
    return is_valid_http_uri(cleaned)


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

    for line in config_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            if current_profile:
                profiles.append({"name": current_profile, "host": current_host})
            current_profile = line[1:-1]
            current_host = None
        elif line.startswith("host") and "=" in line:
            current_host = line.split("=", 1)[1].strip()

    if current_profile:
        profiles.append({"name": current_profile, "host": current_host})

    return profiles


def get_databricks_user(profile: str) -> str | None:
    """Get current user's email from Databricks CLI."""
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


def _clean_legacy_hooks(existing: dict) -> None:
    """Remove retired Python Stop hooks (mlflow.claude_code.hooks / claudetracing.hooks)
    while preserving any custom user hooks.
    """
    hooks = existing.get("hooks")
    if not isinstance(hooks, dict) or "Stop" not in hooks:
        return

    stop_blocks = hooks.get("Stop")
    if not isinstance(stop_blocks, list):
        return

    cleaned_blocks = []
    for block in stop_blocks:
        if not isinstance(block, dict):
            continue
        if "hooks" in block and isinstance(block["hooks"], list):
            remaining = [
                h
                for h in block["hooks"]
                if not isinstance(h, dict)
                or (
                    "mlflow" not in h.get("command", "")
                    and "claudetracing" not in h.get("command", "")
                )
            ]
            if remaining:
                cleaned_blocks.append({**block, "hooks": remaining})
        else:
            cmd = block.get("command", "")
            if "mlflow" not in cmd and "claudetracing" not in cmd:
                cleaned_blocks.append(block)

    if cleaned_blocks:
        hooks["Stop"] = cleaned_blocks
    else:
        hooks.pop("Stop", None)

    if not hooks:
        existing.pop("hooks", None)


def create_settings_file(
    profile: str | None,
    experiment_path: str,
    project_root: Path,
    *,
    spn: bool = False,
    tracking_uri: str | None = None,
    experiment_id: str | None = None,
    tracking_token: str | None = None,
    trace_location: str | None = None,
) -> Path:
    """Create or update `.claude/settings.json` (and `.claude/settings.local.json` for local auth).

    Adheres to MLflow 3.14+ conventions:
      - Writes configuration under `"env"` (Claude Code's native environment key).
      - Enables `"mlflow-tracing@mlflow-plugins"` in `"enabledPlugins"`.
      - Migrates any legacy `"environment"` user keys to `"env"` and removes retired
        Python Stop hooks so `@mlflow/claude-code` runs cleanly.
      - Keeps machine-specific credentials (`databricks://<profile>`, `DATABRICKS_CONFIG_PROFILE`,
        `MLFLOW_TRACKING_TOKEN`) in the gitignored `.claude/settings.local.json`.
    """
    claude_dir = project_root / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    settings_path = claude_dir / "settings.json"

    databricks = spn or bool(profile) or (tracking_uri or "").startswith("databricks")

    if databricks:
        committed_uri = "databricks"
    elif tracking_uri:
        committed_uri = tracking_uri
    else:
        committed_uri = LOCAL_DEFAULT_URI

    if settings_path.exists():
        existing = json.loads(settings_path.read_text(encoding="utf-8"))
    else:
        existing = {}

    env_block: dict[str, str] = {}
    if isinstance(existing.get(LEGACY_ENV_KEY), dict):
        for k, v in existing[LEGACY_ENV_KEY].items():
            env_block[str(k)] = str(v)
        existing.pop(LEGACY_ENV_KEY, None)

    if isinstance(existing.get(ENV_KEY), dict):
        for k, v in existing[ENV_KEY].items():
            env_block[str(k)] = str(v)

    env_block["MLFLOW_CLAUDE_TRACING_ENABLED"] = "true"
    env_block["MLFLOW_TRACKING_URI"] = committed_uri

    if experiment_path:
        env_block["MLFLOW_EXPERIMENT_NAME"] = experiment_path
    else:
        env_block.pop("MLFLOW_EXPERIMENT_NAME", None)

    if experiment_id:
        env_block["MLFLOW_EXPERIMENT_ID"] = str(experiment_id)
    else:
        env_block.pop("MLFLOW_EXPERIMENT_ID", None)

    if trace_location and trace_location.strip():
        env_block["MLFLOW_TRACE_LOCATION"] = trace_location.strip()
    else:
        env_block.pop("MLFLOW_TRACE_LOCATION", None)

    # Never commit machine-local profiles, tokens, or legacy enrichment flags
    env_block.pop("DATABRICKS_CONFIG_PROFILE", None)
    env_block.pop("MLFLOW_TRACKING_TOKEN", None)
    env_block.pop("CLAUDETRACING_ENRICHMENTS", None)

    existing[ENV_KEY] = env_block

    enabled_plugins = existing.get("enabledPlugins")
    if not isinstance(enabled_plugins, dict):
        enabled_plugins = {}
    enabled_plugins[MLFLOW_CLAUDE_PLUGIN_ID] = True
    existing["enabledPlugins"] = enabled_plugins

    _clean_legacy_hooks(existing)

    settings_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

    if profile and not spn:
        _write_local_settings(
            project_root,
            {
                "MLFLOW_TRACKING_URI": f"databricks://{profile}",
                "DATABRICKS_CONFIG_PROFILE": profile,
            },
        )
    elif tracking_token:
        _write_local_settings(
            project_root,
            {"MLFLOW_TRACKING_TOKEN": tracking_token},
        )

    return settings_path


def _write_local_settings(project_root: Path, updates: dict[str, str]) -> Path:
    """Write machine-local env overrides into the gitignored .claude/settings.local.json."""
    local_path = project_root / ".claude" / "settings.local.json"
    data = (
        json.loads(local_path.read_text(encoding="utf-8"))
        if local_path.exists()
        else {}
    )

    env_block: dict[str, str] = {}
    if isinstance(data.get(LEGACY_ENV_KEY), dict):
        env_block.update({str(k): str(v) for k, v in data.pop(LEGACY_ENV_KEY).items()})
    if isinstance(data.get(ENV_KEY), dict):
        env_block.update({str(k): str(v) for k, v in data[ENV_KEY].items()})

    env_block.update(updates)
    data[ENV_KEY] = env_block
    local_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return local_path


def _is_claude_plugin_cached() -> bool:
    """Return True if mlflow-tracing@mlflow-plugins is already installed in ~/.claude/plugins/."""
    installed_file = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    if not installed_file.exists():
        return False
    try:
        data = json.loads(installed_file.read_text(encoding="utf-8"))
        entries = data.get("plugins", {}).get(MLFLOW_CLAUDE_PLUGIN_ID, [])
        return any(
            isinstance(e, dict)
            and e.get("scope") == "user"
            and Path(str(e.get("installPath", ""))).exists()
            for e in entries
        )
    except Exception:
        return False


def ensure_claude_plugin(project_root: Path) -> bool:
    """Install the official MLflow Claude Code plugin via `mlflow.claude_code.plugin`."""
    if _is_claude_plugin_cached():
        return True

    if shutil.which("claude") is None:
        print(
            f"{YELLOW}Note: `claude` CLI not found on PATH; skipped plugin installation.\n"
            "Once Claude Code is installed, run:\n"
            "  claude plugin marketplace add mlflow/mlflow --scope local --sparse .claude-plugin libs/typescript/integrations/claude-code\n"
            f"  claude plugin install {MLFLOW_CLAUDE_PLUGIN_ID} --scope local{RESET}"
        )
        return False

    try:
        from mlflow.claude_code.plugin import ensure_plugin_installed

        ensure_plugin_installed(project_root)
        return True
    except Exception as e:
        print(f"{YELLOW}Warning: Could not auto-install Claude Code plugin: {e}{RESET}")
        return False


def update_gitignore(project_root: Path, *, yes: bool = False) -> bool:
    """Add local tracing entries to .gitignore if confirmed."""
    gitignore = project_root / ".gitignore"
    entries = [
        ".claude/settings.local.json",
        ".claude/mlflow/",
        ".codex/mlflow-tracing.json",
        ".github/hooks/mlflow-tracing.local.json",
        ".agents/mlflow-tracing.json",
        "mlruns/",
    ]
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""

    to_add = [e for e in entries if e not in existing]
    if not to_add:
        return False

    if not yes:
        print("\nAdd these entries to .gitignore?")
        for entry in to_add:
            print(f"  - {entry}")
        print(f"  {GREEN}[1]{RESET} Yes (recommended)")
        print(f"  {GREEN}[2]{RESET} No")

        choice = input("\nChoice [1/2] (default: 1): ").strip()
        if choice == "2":
            return False

    with open(gitignore, "a", encoding="utf-8") as f:
        f.write("\n# MLflow Agent Tracing\n" + "\n".join(to_add) + "\n")
    return True


def resolve_experiment(
    tracking_uri: str,
    experiment_name: str,
    *,
    profile: str | None = None,
    tracking_token: str | None = None,
) -> tuple[bool, str | None]:
    """Verify connection to the MLflow tracking server and resolve (or create) the experiment ID.

    Returns:
        Tuple of `(connected, experiment_id)`.
    """
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "15")

    import mlflow
    from mlflow import MlflowClient
    from mlflow.exceptions import MlflowException

    effective_uri = f"databricks://{profile}" if profile else tracking_uri
    saved_profile = os.environ.get("DATABRICKS_CONFIG_PROFILE")
    saved_token = os.environ.get("MLFLOW_TRACKING_TOKEN")

    try:
        if profile:
            os.environ["DATABRICKS_CONFIG_PROFILE"] = profile
        if tracking_token:
            os.environ["MLFLOW_TRACKING_TOKEN"] = tracking_token

        mlflow.set_tracking_uri(effective_uri)
        client = MlflowClient(tracking_uri=effective_uri)
        experiment = client.get_experiment_by_name(experiment_name)
        if experiment is not None:
            return True, experiment.experiment_id
        exp_id = client.create_experiment(experiment_name)
        return True, str(exp_id)
    except (TimeoutError, MlflowException, ConnectionError, OSError) as e:
        print(f"{YELLOW}Connection check failed: {e}{RESET}")
        return False, None
    finally:
        if profile:
            if saved_profile is None:
                os.environ.pop("DATABRICKS_CONFIG_PROFILE", None)
            else:
                os.environ["DATABRICKS_CONFIG_PROFILE"] = saved_profile
        if tracking_token:
            if saved_token is None:
                os.environ.pop("MLFLOW_TRACKING_TOKEN", None)
            else:
                os.environ["MLFLOW_TRACKING_TOKEN"] = saved_token


def verify_connection(profile: str, experiment_path: str) -> bool:
    """Verify MLflow connection to Databricks."""
    ok, _ = resolve_experiment("databricks", experiment_path, profile=profile)
    return ok


def get_claude_status(project_root: Path | None = None) -> dict:
    """Return current Claude Code tracing status for the project."""
    root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    settings_path = root / ".claude" / "settings.json"
    local_path = root / ".claude" / "settings.local.json"

    shared_env = (
        _extract_env_dict(json.loads(settings_path.read_text(encoding="utf-8")))
        if settings_path.exists()
        else {}
    )
    local_env = (
        _extract_env_dict(json.loads(local_path.read_text(encoding="utf-8")))
        if local_path.exists()
        else {}
    )
    merged = {**shared_env, **local_env}
    enabled = merged.get("MLFLOW_CLAUDE_TRACING_ENABLED", "").lower() in (
        "true",
        "1",
        "yes",
    )
    return {
        "enabled": enabled,
        "tracking_uri": merged.get("MLFLOW_TRACKING_URI"),
        "experiment_id": merged.get("MLFLOW_EXPERIMENT_ID"),
        "experiment_name": merged.get("MLFLOW_EXPERIMENT_NAME"),
        "trace_location": merged.get("MLFLOW_TRACE_LOCATION"),
        "profile": merged.get("DATABRICKS_CONFIG_PROFILE"),
    }


def get_project_status(project_root: Path | None = None) -> tuple[dict, CodexStatus]:
    """Return (claude_status, codex_status) for backwards compatibility."""
    root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    return get_claude_status(root), get_codex_status(root)


def get_all_agent_statuses(
    project_root: Path | None = None,
) -> tuple[dict, CodexStatus, CopilotTracingStatus, AgyTracingStatus]:
    """Return status objects for Claude Code, Codex, GitHub Copilot, and Antigravity (agy)."""
    root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    return (
        get_claude_status(root),
        get_codex_status(root),
        get_copilot_status(root),
        get_agy_status(root),
    )


def disable_claude_tracing(project_root: Path | None = None) -> bool:
    """Disable Claude Code tracing in the project."""
    from mlflow.claude_code.plugin import disable_tracing_plugin

    root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    claude_dir = root / ".claude"
    claude_changed = False

    for name in ("settings.json", "settings.local.json"):
        path = claude_dir / name
        if not path.exists():
            continue
        if disable_tracing_plugin(path):
            claude_changed = True
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            for key in (ENV_KEY, LEGACY_ENV_KEY):
                block = data.get(key)
                if isinstance(block, dict):
                    for var in (
                        "MLFLOW_CLAUDE_TRACING_ENABLED",
                        "MLFLOW_TRACKING_URI",
                        "MLFLOW_EXPERIMENT_ID",
                        "MLFLOW_EXPERIMENT_NAME",
                        "MLFLOW_TRACE_LOCATION",
                        "DATABRICKS_CONFIG_PROFILE",
                        "MLFLOW_TRACKING_TOKEN",
                        "CLAUDETRACING_ENRICHMENTS",
                    ):
                        if var in block:
                            del block[var]
                            claude_changed = True
                    if not block:
                        del data[key]
            enabled_plugins = data.get("enabledPlugins")
            if (
                isinstance(enabled_plugins, dict)
                and MLFLOW_CLAUDE_PLUGIN_ID in enabled_plugins
            ):
                del enabled_plugins[MLFLOW_CLAUDE_PLUGIN_ID]
                claude_changed = True
                if not enabled_plugins:
                    del data["enabledPlugins"]
            _clean_legacy_hooks(data)
            if data:
                path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            else:
                path.unlink()

    return claude_changed


def disable_project_tracing(
    project_root: Path | None = None,
) -> tuple[bool, bool]:
    """Disable Claude Code and Codex tracing in the project (also cleans Copilot and Agy)."""
    root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    claude_changed = disable_claude_tracing(root)
    codex_changed = disable_codex(root)
    disable_copilot(root)
    disable_agy(root)
    return claude_changed, codex_changed


def disable_all_project_tracing(
    project_root: Path | None = None,
) -> dict[str, bool]:
    """Disable tracing for all 4 supported agents and return a dict of changed flags."""
    root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    return {
        "claude": disable_claude_tracing(root),
        "codex": disable_codex(root),
        "copilot": disable_copilot(root),
        "agy": disable_agy(root),
    }


def _existing_tracing_config(project_root: Path | None = None) -> dict | None:
    """Return existing tracing configuration summary if any agent tracing is already set up."""
    claude_st, codex_st, copilot_st, agy_st = get_all_agent_statuses(project_root)
    if claude_st["enabled"] or claude_st["tracking_uri"]:
        return {
            "uri": claude_st["tracking_uri"] or LOCAL_DEFAULT_URI,
            "experiment": claude_st["experiment_name"]
            or claude_st["experiment_id"]
            or "0",
        }
    if codex_st.enabled:
        return {
            "uri": codex_st.tracking_uri or LOCAL_DEFAULT_URI,
            "experiment": codex_st.experiment_id or "0",
        }
    if copilot_st.enabled:
        return {
            "uri": copilot_st.tracking_uri or LOCAL_DEFAULT_URI,
            "experiment": copilot_st.experiment_name or copilot_st.experiment_id or "0",
        }
    if agy_st.enabled:
        return {
            "uri": agy_st.tracking_uri or LOCAL_DEFAULT_URI,
            "experiment": agy_st.experiment_name or agy_st.experiment_id or "0",
        }
    return None


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


def _apply_agent_configs(
    project_root: Path,
    agent: AgentChoice,
    *,
    profile: str | None = None,
    spn: bool = False,
    tracking_uri: str,
    experiment_name: str,
    experiment_id: str | None = None,
    tracking_token: str | None = None,
    trace_location: str | None = None,
    install_plugin: bool = True,
    yes: bool = False,
) -> int:
    """Write configuration files for the selected coding agent(s)."""
    configure_claude_agent = agent in ("all", "both", "claude")
    configure_codex_agent = agent in ("all", "both", "codex")
    configure_copilot_agent = agent in ("all", "copilot")
    configure_agy_agent = agent in ("all", "agy")

    effective_uri = f"databricks://{profile}" if (profile and not spn) else tracking_uri

    if configure_claude_agent:
        settings_path = create_settings_file(
            profile=profile,
            experiment_path=experiment_name,
            project_root=project_root,
            spn=spn,
            tracking_uri=tracking_uri,
            experiment_id=experiment_id,
            tracking_token=tracking_token,
            trace_location=trace_location,
        )
        print(f"Configured Claude Code: {settings_path.relative_to(project_root)}")
        if install_plugin:
            if ensure_claude_plugin(project_root):
                print("Verified MLflow Claude Code plugin.")

    if configure_codex_agent:
        codex_exp_id = experiment_id or "0"
        try:
            config_toml, tracing_json = configure_codex(
                project_root=project_root,
                tracking_uri=effective_uri,
                experiment_id=codex_exp_id,
                trace_location=trace_location,
                project_local=True,
            )
            print(
                f"Configured Codex: {config_toml.relative_to(project_root)}, "
                f"{tracing_json.relative_to(project_root)}"
            )
            if not is_mlflow_codex_installed():
                print(
                    f"{YELLOW}Note: `mlflow-codex` is not on PATH. Install it with:\n"
                    f"  npm install -g @mlflow/codex{RESET}"
                )
        except ValueError as e:
            print(f"{YELLOW}Error configuring Codex: {e}{RESET}")
            return 1

    if configure_copilot_agent:
        cp_path = configure_copilot(
            project_root=project_root,
            tracking_uri=effective_uri,
            experiment_id=experiment_id,
            experiment_name=experiment_name,
            profile=profile if not spn else None,
            tracking_token=tracking_token,
        )
        print(f"Configured GitHub Copilot: {cp_path.relative_to(project_root)}")

    if configure_agy_agent:
        hooks_file, agy_cfg = configure_agy(
            project_root=project_root,
            tracking_uri=effective_uri,
            experiment_id=experiment_id,
            experiment_name=experiment_name,
            tracking_token=tracking_token,
        )
        print(
            f"Configured Antigravity (agy): {hooks_file.relative_to(project_root)}, "
            f"{agy_cfg.relative_to(project_root)}"
        )

    if update_gitignore(project_root, yes=yes):
        print("Updated .gitignore")

    return 0


def run_setup(
    *,
    spn: bool = False,
    agent: AgentChoice | None = None,
    tracking_uri: str | None = None,
    profile: str | None = None,
    experiment: str | None = None,
    experiment_id: str | None = None,
    tracking_token: str | None = None,
    trace_location: str | None = None,
    yes: bool = False,
) -> int:
    """Run the interactive or flag-driven setup process."""
    project_root = Path.cwd().resolve()

    if profile and tracking_uri:
        print("Error: Use --profile or --tracking-uri, not both.")
        return 1

    # Non-interactive fast path when flags are supplied
    if yes or tracking_uri or profile or experiment or experiment_id:
        selected_agent: AgentChoice = agent or "both"
        exp_name = experiment or project_root.name

        if spn:
            uri = "databricks"
            if not experiment and not exp_name.startswith("/Workspace/"):
                exp_name = f"/Workspace/Shared/{exp_name}"
            return _apply_agent_configs(
                project_root,
                selected_agent,
                spn=True,
                tracking_uri=uri,
                experiment_name=exp_name,
                experiment_id=experiment_id,
                trace_location=trace_location,
                install_plugin=not yes,
                yes=yes,
            )

        if profile:
            uri = "databricks"
            if not experiment and not exp_name.startswith("/Workspace/"):
                exp_name = f"/Workspace/Shared/{exp_name}"
            resolved_id = experiment_id
            if not resolved_id:
                ok, resolved_id = resolve_experiment(uri, exp_name, profile=profile)
                if not ok:
                    return 1
            return _apply_agent_configs(
                project_root,
                selected_agent,
                profile=profile,
                tracking_uri=uri,
                experiment_name=exp_name,
                experiment_id=resolved_id,
                trace_location=trace_location,
                install_plugin=not yes,
                yes=yes,
            )

        uri = tracking_uri or LOCAL_DEFAULT_URI
        if not is_valid_tracking_uri(uri):
            print(
                f"Error: Invalid tracking URI '{uri}'. Expected 'databricks' or an http(s):// URL."
            )
            return 1

        resolved_id = experiment_id
        if not resolved_id and uri != "databricks":
            _, resolved_id = resolve_experiment(
                uri, exp_name, tracking_token=tracking_token
            )

        return _apply_agent_configs(
            project_root,
            selected_agent,
            tracking_uri=uri,
            experiment_name=exp_name,
            experiment_id=resolved_id,
            tracking_token=tracking_token,
            trace_location=trace_location,
            install_plugin=not yes,
            yes=yes,
        )

    print("\n=== MLflow Coding Agent Tracing Setup ===\n")

    existing = _existing_tracing_config(project_root)
    if existing is not None:
        print(
            f"Tracing is already configured (uri={existing['uri']}, experiment={existing['experiment']})."
        )
        if prompt_choice("What would you like to do?", ["Keep it", "Reconfigure"]) == 0:
            print("Keeping existing tracing configuration. Nothing to do.")
            return 0

    if agent is None:
        agent_idx = prompt_choice(
            "Which coding agent(s) do you want to configure?",
            [
                "All agents (Claude Code, Codex, Copilot, Antigravity)",
                "Claude Code and Codex",
                "Claude Code only",
                "Codex only",
                "GitHub Copilot (CLI / VS Code) only",
                "Google Antigravity (agy) only",
            ],
        )
        selected_agent = ("all", "both", "claude", "codex", "copilot", "agy")[agent_idx]
    else:
        selected_agent = agent

    if spn:
        return setup_spn(agent=selected_agent)

    storage_type = prompt_choice(
        "\nWhere should traces be stored?",
        [
            "Databricks (OAuth / CLI profile)",
            "Self-hosted MLflow Server (http:// or https://)",
            f"Local MLflow Server ({LOCAL_DEFAULT_URI})",
        ],
    )

    if storage_type == 0:
        return setup_databricks(agent=selected_agent)
    if storage_type == 1:
        return setup_self_hosted(agent=selected_agent)
    return setup_local(agent=selected_agent)


def setup_spn(agent: AgentChoice = "claude") -> int:
    """Configure headless service-principal tracing — no local profile, no secrets on disk."""
    project_root = Path.cwd().resolve()
    print("\nService-principal / headless tracing.")
    print("Auth is resolved from the environment at run time — no profile is stored.\n")

    exp_name = prompt("Experiment name", default=project_root.name)
    exp_type = prompt_choice(
        "Experiment location:",
        [
            "Shared folder - visible to all workspace users (recommended)",
            "Personal folder",
        ],
    )
    if exp_type == 0:
        experiment_path = f"/Workspace/Shared/{exp_name}"
    else:
        user = prompt("Databricks email (for personal folder path)")
        experiment_path = f"/Workspace/Users/{user}/{exp_name}"

    rc = _apply_agent_configs(
        project_root,
        agent,
        spn=True,
        tracking_uri="databricks",
        experiment_name=experiment_path,
    )
    if rc != 0:
        return rc

    print("\nSetup complete (service-principal mode).")
    print(
        "Provide these in the run environment (e.g. cloud routine secrets) — never commit them:"
    )
    print("  DATABRICKS_HOST=https://<workspace-host>")
    print("  DATABRICKS_CLIENT_ID=<service principal application id>")
    print("  DATABRICKS_CLIENT_SECRET=<service principal secret>")
    print(f"\nTraces will be sent to: {experiment_path}")
    return 0


def setup_self_hosted(agent: AgentChoice = "both") -> int:
    """Setup self-hosted MLflow tracking server (http:// or https://)."""
    project_root = Path.cwd().resolve()

    while True:
        uri = prompt("MLflow Tracking Server URL (e.g., https://mlflow.example.com)")
        if is_valid_http_uri(uri):
            break
        print(f"{YELLOW}Please enter a valid http:// or https:// URL.{RESET}")

    exp_name = prompt("Experiment name", default=project_root.name)
    token = input(
        "Bearer token / MLFLOW_TRACKING_TOKEN (optional, press Enter to skip): "
    ).strip()

    print(f"\nVerifying connection to {uri}...")
    ok, exp_id = resolve_experiment(uri, exp_name, tracking_token=token or None)
    if not ok:
        print(f"{YELLOW}Could not verify connection to {uri} right now.{RESET}")
        if (
            prompt_choice(
                "Continue writing configuration anyway?",
                ["Yes, save configuration", "Cancel setup"],
            )
            == 1
        ):
            print("Setup cancelled.")
            return 1
    else:
        print(f"Connected! Resolved experiment '{exp_name}' (id={exp_id}).")

    rc = _apply_agent_configs(
        project_root,
        agent,
        tracking_uri=uri,
        experiment_name=exp_name,
        experiment_id=exp_id,
        tracking_token=token or None,
    )
    if rc != 0:
        return rc

    print("\nSetup complete! Restart your coding agent to enable tracing.")
    print(f"Traces will be sent to: {uri} (experiment: {exp_name})")
    return 0


def setup_local(agent: AgentChoice = "both") -> int:
    """Setup local MLflow tracking server (http://localhost:5000)."""
    project_root = Path.cwd().resolve()
    uri = prompt("Local MLflow Server URL", default=LOCAL_DEFAULT_URI)
    if not is_valid_http_uri(uri):
        print(f"{YELLOW}Invalid URL '{uri}', using {LOCAL_DEFAULT_URI}.{RESET}")
        uri = LOCAL_DEFAULT_URI

    exp_name = prompt("Experiment name", default=project_root.name)

    ok, exp_id = resolve_experiment(uri, exp_name)
    if ok:
        print(f"Connected to local server! Experiment '{exp_name}' (id={exp_id}).")
    else:
        exp_id = "0"
        print(
            f"{YELLOW}Note: Local MLflow server is not running yet at {uri}. "
            f"Defaulting experiment ID to 0.{RESET}"
        )

    rc = _apply_agent_configs(
        project_root,
        agent,
        tracking_uri=uri,
        experiment_name=exp_name,
        experiment_id=exp_id,
    )
    if rc != 0:
        return rc

    print("\nSetup complete!")
    print("Make sure your local MLflow server is running:")
    print(f"  {CYAN}mlflow server --port {urlparse(uri).port or 5000}{RESET}")
    return 0


def setup_databricks(agent: AgentChoice = "both") -> int:
    """Setup Databricks MLflow storage."""
    try:
        subprocess.run(["databricks", "--version"], capture_output=True, check=True)
    except FileNotFoundError:
        print("Error: Databricks CLI not found. Install with: brew install databricks")
        return 1

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

    print("\nMLflow experiments are stored in Databricks Workspace folders.")
    exp_type = prompt_choice(
        "Experiment location:",
        [
            "Shared folder - visible to all workspace users (recommended)",
            f"Personal folder - only visible to you ({user or 'your account'})",
        ],
    )
    project_root = Path.cwd().resolve()
    exp_name = prompt("Experiment name", default=project_root.name)

    if exp_type == 0:
        experiment_path = f"/Workspace/Shared/{exp_name}"
    else:
        if not user:
            user = prompt("Databricks email (for personal folder path)")
        experiment_path = f"/Workspace/Users/{user}/{exp_name}"

    print("\nVerifying connection to Databricks...")
    ok, exp_id = resolve_experiment("databricks", experiment_path, profile=profile)
    if not ok:
        print("\n" + "=" * 50)
        print("ERROR: Could not connect to Databricks!")
        print("=" * 50)
        print(f"\nProfile '{profile}' failed to authenticate.")
        print("To fix, re-authenticate with:")
        print(f"  databricks auth login --profile {profile}")
        print("\nThen run 'traces init' again.")
        return 1

    print(f"Connection verified! (experiment_id={exp_id})")

    rc = _apply_agent_configs(
        project_root,
        agent,
        profile=profile,
        tracking_uri="databricks",
        experiment_name=experiment_path,
        experiment_id=exp_id,
    )
    if rc != 0:
        return rc

    print("\nSetup complete! Restart your coding agent to enable tracing.")
    print(f"Traces will be sent to: {experiment_path}")
    return 0
