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

        assert (
            settings["environment"]["MLFLOW_TRACKING_URI"]
            == "databricks://test-profile"
        )
        assert (
            settings["environment"]["MLFLOW_EXPERIMENT_NAME"]
            == "/Workspace/Shared/test-experiment"
        )
        assert settings["environment"]["DATABRICKS_CONFIG_PROFILE"] == "test-profile"
        assert settings["environment"]["MLFLOW_CLAUDE_TRACING_ENABLED"] == "true"
        assert "hooks" in settings
        assert "Stop" in settings["hooks"]


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

        # Tracing config added
        assert settings["environment"]["DATABRICKS_CONFIG_PROFILE"] == "new-profile"
        assert (
            settings["environment"]["MLFLOW_TRACKING_URI"] == "databricks://new-profile"
        )

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
