"""Tests for the setup module."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


def test_creates_settings_in_fresh_directory():
    """Test that setup creates .claude/settings.json in a fresh directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)

        from claudetracing.setup import create_settings_file

        project_root = Path(tmpdir)
        settings_path = create_settings_file(
            profile="test-profile",
            experiment_path="/Workspace/Shared/test-experiment",
            project_root=project_root,
        )

        assert settings_path.exists()
        assert settings_path == project_root / ".claude" / "settings.json"

        with open(settings_path) as f:
            settings = json.load(f)

        assert settings["environment"]["MLFLOW_TRACKING_URI"] == "databricks"
        assert (
            settings["environment"]["MLFLOW_EXPERIMENT_NAME"]
            == "/Workspace/Shared/test-experiment"
        )
        # Profile is no longer committed — it lives in the gitignored .local
        assert "DATABRICKS_CONFIG_PROFILE" not in settings["environment"]
        assert settings["environment"]["MLFLOW_CLAUDE_TRACING_ENABLED"] == "true"
        assert "hooks" in settings
        assert "Stop" in settings["hooks"]

        # Databricks auth uses the enriched hook (it runs the env loader)
        hook_cmd = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
        assert "enriched_stop_hook_handler" in hook_cmd

        # Per-machine profile written to the gitignored .local, not the committed file
        local = json.loads(
            (project_root / ".claude" / "settings.local.json").read_text()
        )
        assert local["environment"]["DATABRICKS_CONFIG_PROFILE"] == "test-profile"


def test_creates_claude_directory_if_missing():
    """Test that .claude directory is created if it doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)

        from claudetracing.setup import create_settings_file

        project_root = Path(tmpdir)
        claude_dir = project_root / ".claude"

        assert not claude_dir.exists()

        create_settings_file(
            profile="test",
            experiment_path="/Workspace/Shared/test",
            project_root=project_root,
        )

        assert claude_dir.exists()
        assert claude_dir.is_dir()


def test_merges_with_existing_settings():
    """Test that existing settings are preserved when adding tracing config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)

        from claudetracing.setup import create_settings_file

        project_root = Path(tmpdir)
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()

        # Create existing settings with custom hook and env var
        existing_settings = {
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "echo 'custom hook'"}]}
                ],
                "PreToolUse": [
                    {"hooks": [{"type": "command", "command": "echo 'pre'"}]}
                ],
            },
            "environment": {"CUSTOM_VAR": "should-be-preserved"},
        }
        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps(existing_settings))

        # Run setup
        create_settings_file(
            profile="new-profile",
            experiment_path="/Workspace/Shared/new",
            project_root=project_root,
        )

        # Verify merge
        with open(settings_path) as f:
            settings = json.load(f)

        # Tracing config added — bare URI committed; profile not in the committed file
        assert settings["environment"]["MLFLOW_TRACKING_URI"] == "databricks"
        assert "DATABRICKS_CONFIG_PROFILE" not in settings["environment"]

        # Existing config preserved
        assert settings["environment"]["CUSTOM_VAR"] == "should-be-preserved"
        assert "PreToolUse" in settings["hooks"]

        # Tracing hook appended to existing Stop block (not new block)
        stop_hooks = settings["hooks"]["Stop"]
        assert len(stop_hooks) == 1  # Still one block
        assert len(stop_hooks[0]["hooks"]) == 2  # Original + tracing hook appended


def test_does_not_duplicate_tracing_hook():
    """Test that running setup twice doesn't duplicate the tracing hook."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)

        from claudetracing.setup import create_settings_file

        project_root = Path(tmpdir)

        # Run setup twice
        create_settings_file(
            profile="test",
            experiment_path="/Workspace/Shared/test",
            project_root=project_root,
        )
        create_settings_file(
            profile="test",
            experiment_path="/Workspace/Shared/test",
            project_root=project_root,
        )

        settings_path = project_root / ".claude" / "settings.json"
        with open(settings_path) as f:
            settings = json.load(f)

        # Should only have one Stop hook
        assert len(settings["hooks"]["Stop"]) == 1


def test_gitignore_updated():
    """Test that .gitignore is updated with Claude Code entries when user confirms."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)

        from claudetracing.setup import update_gitignore

        project_root = Path(tmpdir)
        gitignore_path = project_root / ".gitignore"

        gitignore_path.write_text("*.pyc\n")

        with patch("builtins.input", return_value="1"):
            result = update_gitignore(project_root)

        assert result is True
        content = gitignore_path.read_text()
        assert ".claude/settings.local.json" in content
        assert ".claude/mlflow/" in content
        assert "mlruns/" in content
        assert "*.pyc" in content


def test_load_tracing_env_precedence():
    """load_tracing_env: existing os.environ > settings.local.json > settings.json."""
    from claudetracing.setup import load_tracing_env

    with tempfile.TemporaryDirectory() as tmpdir:
        claude = Path(tmpdir) / ".claude"
        claude.mkdir()
        (claude / "settings.json").write_text(
            json.dumps(
                {
                    "environment": {
                        "CT_TEST_BASE": "from_settings",
                        "CT_TEST_OVERRIDE": "from_settings",
                        "CT_TEST_EXISTING": "from_settings",
                    }
                }
            )
        )
        (claude / "settings.local.json").write_text(
            json.dumps({"environment": {"CT_TEST_OVERRIDE": "from_local"}})
        )

        keys = ["CT_TEST_BASE", "CT_TEST_OVERRIDE", "CT_TEST_EXISTING"]
        saved = {k: os.environ.get(k) for k in keys}
        try:
            for k in keys:
                os.environ.pop(k, None)
            os.environ["CT_TEST_EXISTING"] = "from_real_env"  # must win

            load_tracing_env(project_root=Path(tmpdir))

            assert os.environ["CT_TEST_BASE"] == "from_settings"  # settings.json base
            assert (
                os.environ["CT_TEST_OVERRIDE"] == "from_local"
            )  # .local wins over settings.json
            assert (
                os.environ["CT_TEST_EXISTING"] == "from_real_env"
            )  # real env wins over both
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


def test_load_tracing_env_no_files_is_noop():
    """No .claude settings present → no error, no changes."""
    from claudetracing.setup import load_tracing_env

    with tempfile.TemporaryDirectory() as tmpdir:
        load_tracing_env(project_root=Path(tmpdir))  # must not raise


def test_spn_mode_bare_uri_no_profile_no_local():
    """spn=True commits a bare URI, writes no profile and no settings.local.json."""
    with tempfile.TemporaryDirectory() as tmpdir:
        from claudetracing.setup import create_settings_file

        project_root = Path(tmpdir)
        create_settings_file(
            profile=None,
            experiment_path="/Workspace/Shared/spn-exp",
            project_root=project_root,
            spn=True,
        )

        settings = json.loads((project_root / ".claude" / "settings.json").read_text())
        assert settings["environment"]["MLFLOW_TRACKING_URI"] == "databricks"
        assert "DATABRICKS_CONFIG_PROFILE" not in settings["environment"]
        # Enriched hook (runs the loader) even in headless mode
        assert (
            "enriched_stop_hook_handler"
            in settings["hooks"]["Stop"][0]["hooks"][0]["command"]
        )
        # No secrets and no per-machine profile file are created
        assert not (project_root / ".claude" / "settings.local.json").exists()


def test_existing_committed_profile_is_dropped_on_reinit():
    """Re-init over an old `databricks://profile` setup removes the stale committed profile."""
    with tempfile.TemporaryDirectory() as tmpdir:
        from claudetracing.setup import create_settings_file

        project_root = Path(tmpdir)
        claude_dir = project_root / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text(
            json.dumps(
                {
                    "environment": {
                        "MLFLOW_TRACKING_URI": "databricks://old-profile",
                        "DATABRICKS_CONFIG_PROFILE": "old-profile",
                    }
                }
            )
        )

        create_settings_file(
            profile="old-profile",
            experiment_path="/Workspace/Shared/x",
            project_root=project_root,
        )

        settings = json.loads((claude_dir / "settings.json").read_text())
        assert settings["environment"]["MLFLOW_TRACKING_URI"] == "databricks"
        assert "DATABRICKS_CONFIG_PROFILE" not in settings["environment"]
        local = json.loads((claude_dir / "settings.local.json").read_text())
        assert local["environment"]["DATABRICKS_CONFIG_PROFILE"] == "old-profile"


def test_gitignore_not_duplicated():
    """Test that .gitignore entries are not duplicated."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)

        from claudetracing.setup import update_gitignore

        project_root = Path(tmpdir)
        gitignore_path = project_root / ".gitignore"

        # Already has all entries
        gitignore_path.write_text(
            ".claude/settings.local.json\n.claude/mlflow/\nmlruns/\n"
        )

        # Should return False without prompting since nothing to add
        result = update_gitignore(project_root)

        assert result is False
        content = gitignore_path.read_text()
        assert content.count(".claude/settings.local.json") == 1
        assert content.count("mlruns/") == 1


def test_get_databricks_profiles_empty():
    """Test profile detection when no config exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict(os.environ, {"HOME": tmpdir}):
            from claudetracing import setup
            from importlib import reload

            reload(setup)

            profiles = setup.get_databricks_profiles()
            assert profiles == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
