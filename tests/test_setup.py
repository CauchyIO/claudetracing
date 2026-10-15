"""Tests for Claude Code and unified MLflow tracing setup."""

import json
import os
from pathlib import Path
from unittest.mock import patch

from claudetracing.setup import (
    create_settings_file,
    disable_project_tracing,
    get_databricks_profiles,
    get_project_status,
    is_valid_tracking_uri,
    load_tracing_env,
    resolve_experiment,
    run_setup,
    update_gitignore,
)


def test_creates_settings_for_databricks_profile(tmp_path: Path):
    """Databricks profile setup writes bare URI to settings.json and profile URI to settings.local.json."""
    settings_path = create_settings_file(
        profile="my-profile",
        experiment_path="/Workspace/Shared/test-experiment",
        project_root=tmp_path,
        experiment_id="12345",
    )

    assert settings_path == tmp_path / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))

    assert settings["env"]["MLFLOW_CLAUDE_TRACING_ENABLED"] == "true"
    assert settings["env"]["MLFLOW_TRACKING_URI"] == "databricks"
    assert (
        settings["env"]["MLFLOW_EXPERIMENT_NAME"] == "/Workspace/Shared/test-experiment"
    )
    assert settings["env"]["MLFLOW_EXPERIMENT_ID"] == "12345"
    assert "DATABRICKS_CONFIG_PROFILE" not in settings["env"]
    assert "environment" not in settings

    local = json.loads(
        (tmp_path / ".claude" / "settings.local.json").read_text(encoding="utf-8")
    )
    assert local["env"]["MLFLOW_TRACKING_URI"] == "databricks://my-profile"
    assert local["env"]["DATABRICKS_CONFIG_PROFILE"] == "my-profile"


def test_creates_settings_for_self_hosted_mlflow(tmp_path: Path):
    """Self-hosted MLflow stores tracking URI in settings.json and bearer token in settings.local.json."""
    settings_path = create_settings_file(
        profile=None,
        experiment_path="my-team-project",
        project_root=tmp_path,
        tracking_uri="https://mlflow.internal.example.com",
        experiment_id="42",
        tracking_token="secret-bearer-token",
    )

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert (
        settings["env"]["MLFLOW_TRACKING_URI"] == "https://mlflow.internal.example.com"
    )
    assert settings["env"]["MLFLOW_EXPERIMENT_NAME"] == "my-team-project"
    assert settings["env"]["MLFLOW_EXPERIMENT_ID"] == "42"
    assert "MLFLOW_TRACKING_TOKEN" not in settings["env"]

    local = json.loads(
        (tmp_path / ".claude" / "settings.local.json").read_text(encoding="utf-8")
    )
    assert local["env"]["MLFLOW_TRACKING_TOKEN"] == "secret-bearer-token"


def test_spn_mode_commits_bare_uri_without_local_file(tmp_path: Path):
    """spn=True commits a bare databricks URI and writes no settings.local.json."""
    create_settings_file(
        profile=None,
        experiment_path="/Workspace/Shared/spn-exp",
        project_root=tmp_path,
        spn=True,
    )

    settings = json.loads(
        (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    assert settings["env"]["MLFLOW_TRACKING_URI"] == "databricks"
    assert "DATABRICKS_CONFIG_PROFILE" not in settings["env"]
    assert not (tmp_path / ".claude" / "settings.local.json").exists()


def test_migrates_legacy_environment_and_cleans_retired_python_hooks(tmp_path: Path):
    """Legacy 'environment' block and retired Python Stop hooks are migrated/removed while preserving user config."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    existing = {
        "hooks": {
            "Stop": [
                {
                    "hooks": [
                        {"type": "command", "command": "echo 'custom stop hook'"},
                        {
                            "type": "command",
                            "command": 'uv run python -c "from claudetracing.hooks import enriched_stop_hook_handler; enriched_stop_hook_handler()"',
                        },
                    ]
                }
            ],
            "PreToolUse": [{"hooks": [{"type": "command", "command": "echo 'pre'"}]}],
        },
        "environment": {
            "CUSTOM_VAR": "preserve-me",
            "MLFLOW_TRACKING_URI": "databricks://old-profile",
            "DATABRICKS_CONFIG_PROFILE": "old-profile",
            "CLAUDETRACING_ENRICHMENTS": "git,tokens",
        },
    }
    settings_path = claude_dir / "settings.json"
    settings_path.write_text(json.dumps(existing), encoding="utf-8")

    create_settings_file(
        profile="new-profile",
        experiment_path="/Workspace/Shared/new",
        project_root=tmp_path,
    )

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "environment" not in settings
    assert settings["env"]["CUSTOM_VAR"] == "preserve-me"
    assert settings["env"]["MLFLOW_TRACKING_URI"] == "databricks"
    assert "DATABRICKS_CONFIG_PROFILE" not in settings["env"]
    assert "CLAUDETRACING_ENRICHMENTS" not in settings["env"]

    assert "PreToolUse" in settings["hooks"]
    stop_hooks = settings["hooks"]["Stop"][0]["hooks"]
    assert len(stop_hooks) == 1
    assert stop_hooks[0]["command"] == "echo 'custom stop hook'"


def test_load_tracing_env_precedence(tmp_path: Path, monkeypatch):
    """Precedence: os.environ > settings.local.json > settings.json > .codex/mlflow-tracing.json."""
    for key in list(os.environ):
        if key.startswith(("MLFLOW_", "DATABRICKS_", "CT_TEST_")):
            monkeypatch.delenv(key, raising=False)

    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    (codex_dir / "mlflow-tracing.json").write_text(
        json.dumps({"trackingUri": "http://from-codex:5000", "experimentId": "99"}),
        encoding="utf-8",
    )

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(
        json.dumps(
            {
                "env": {
                    "MLFLOW_TRACKING_URI": "http://from-settings:5000",
                    "CT_TEST_OVERRIDE": "from_settings",
                    "CT_TEST_EXISTING": "from_settings",
                }
            }
        ),
        encoding="utf-8",
    )
    (claude_dir / "settings.local.json").write_text(
        json.dumps({"env": {"CT_TEST_OVERRIDE": "from_local"}}),
        encoding="utf-8",
    )

    monkeypatch.setenv("CT_TEST_EXISTING", "from_real_env")
    load_tracing_env(project_root=tmp_path)

    assert os.environ["MLFLOW_EXPERIMENT_ID"] == "99"  # from .codex fallback
    assert (
        os.environ["MLFLOW_TRACKING_URI"] == "http://from-settings:5000"
    )  # settings.json beats codex
    assert (
        os.environ["CT_TEST_OVERRIDE"] == "from_local"
    )  # settings.local.json beats settings.json
    assert os.environ["CT_TEST_EXISTING"] == "from_real_env"  # real env beats all


def test_resolve_experiment_creates_and_reuses_experiment(tmp_path: Path):
    """resolve_experiment creates a missing experiment and returns its existing ID on subsequent calls."""
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"

    ok1, exp_id1 = resolve_experiment(uri, "my-test-exp")
    assert ok1 is True
    assert exp_id1 is not None

    ok2, exp_id2 = resolve_experiment(uri, "my-test-exp")
    assert ok2 is True
    assert exp_id2 == exp_id1


def test_run_setup_non_interactive_configures_both_agents_and_disable(
    tmp_path: Path, monkeypatch
):
    """Non-interactive setup configures both Claude Code and Codex, reports status, and disables cleanly."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "user_codex"))

    with patch("claudetracing.setup.resolve_experiment", return_value=(True, "7")):
        rc = run_setup(
            agent="both",
            tracking_uri="https://mlflow.example.com",
            experiment="team-exp",
            tracking_token="tok-123",
            yes=True,
        )
    assert rc == 0

    claude_st, codex_st = get_project_status(tmp_path)
    assert claude_st["enabled"] is True
    assert claude_st["tracking_uri"] == "https://mlflow.example.com"
    assert claude_st["experiment_name"] == "team-exp"
    assert claude_st["experiment_id"] == "7"

    assert codex_st.enabled is True
    assert codex_st.tracking_uri == "https://mlflow.example.com"
    assert codex_st.experiment_id == "7"
    assert codex_st.scope == "project"

    claude_removed, codex_removed = disable_project_tracing(tmp_path)
    assert claude_removed is True
    assert codex_removed is True

    claude_st_after, codex_st_after = get_project_status(tmp_path)
    assert claude_st_after["enabled"] is False
    assert codex_st_after.enabled is False


def test_run_setup_all_agents_and_disable_all(tmp_path: Path, monkeypatch):
    """Non-interactive setup with agent='all' configures Claude, Codex, Copilot, and AGY."""
    from claudetracing.setup import disable_all_project_tracing, get_all_agent_statuses

    monkeypatch.chdir(tmp_path)
    with patch("claudetracing.setup.resolve_experiment", return_value=(True, "9")):
        rc = run_setup(
            agent="all",
            tracking_uri="http://localhost:5000",
            experiment="all-agents-exp",
            yes=True,
        )
    assert rc == 0

    claude_st, codex_st, copilot_st, agy_st = get_all_agent_statuses(tmp_path)
    assert claude_st["enabled"] is True
    assert codex_st.enabled is True
    assert copilot_st.enabled is True
    assert agy_st.enabled is True

    settings = json.loads(
        (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    assert settings["enabledPlugins"]["mlflow-tracing@mlflow-plugins"] is True

    removed = disable_all_project_tracing(tmp_path)
    assert removed == {"claude": True, "codex": True, "copilot": True, "agy": True}


def test_gitignore_updated_and_idempotent(tmp_path: Path):
    """update_gitignore adds Claude, Codex, Copilot, and AGY entries once and does not duplicate."""
    gitignore_path = tmp_path / ".gitignore"
    gitignore_path.write_text("*.pyc\n", encoding="utf-8")

    assert update_gitignore(tmp_path, yes=True) is True
    content = gitignore_path.read_text(encoding="utf-8")
    assert ".claude/settings.local.json" in content
    assert ".codex/mlflow-tracing.json" in content
    assert ".github/hooks/mlflow-tracing.local.json" in content
    assert ".agents/mlflow-tracing.json" in content
    assert "mlruns/" in content

    assert update_gitignore(tmp_path, yes=True) is False


def test_is_valid_tracking_uri():
    assert is_valid_tracking_uri("databricks") is True
    assert is_valid_tracking_uri("databricks://my-profile") is True
    assert is_valid_tracking_uri("http://localhost:5000") is True
    assert is_valid_tracking_uri("https://mlflow.example.com") is True
    assert is_valid_tracking_uri("localhost:5000") is False
    assert is_valid_tracking_uri("ftp://example.com") is False


def test_get_databricks_profiles(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert get_databricks_profiles() == []

    cfg = tmp_path / ".databrickscfg"
    cfg.write_text(
        "[DEFAULT]\nhost = https://dbc-1.cloud.databricks.com\n\n[work]\nhost = https://dbc-2.cloud.databricks.com\n",
        encoding="utf-8",
    )
    profiles = get_databricks_profiles()
    assert profiles == [
        {"name": "DEFAULT", "host": "https://dbc-1.cloud.databricks.com"},
        {"name": "work", "host": "https://dbc-2.cloud.databricks.com"},
    ]
