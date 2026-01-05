"""Tests for the enrichments module."""

import json
import tempfile
from pathlib import Path

from claudetracing.enrichments import (
    DEFAULT_HOOK_COMMAND,
    ENRICHED_HOOK_COMMAND,
    add_enrichments,
    get_active_enrichments,
    get_enrichment,
    list_enrichments,
    load_settings,
    remove_enrichments,
    save_settings,
    _set_active_enrichments,
    _update_hook_command,
)


class TestListAndGetEnrichments:
    def test_list_enrichments_returns_all(self):
        enrichments = list_enrichments()
        names = {e.name for e in enrichments}
        assert names == {"git", "files", "tokens"}

    def test_get_enrichment_valid(self):
        enrichment = get_enrichment("git")
        assert enrichment is not None
        assert enrichment.name == "git"
        assert len(enrichment.tags) > 0

    def test_get_enrichment_invalid(self):
        assert get_enrichment("nonexistent") is None


class TestGetActiveEnrichments:
    def test_empty_settings(self):
        assert get_active_enrichments(None) == []
        assert get_active_enrichments({}) == []

    def test_missing_env_key(self):
        settings = {"environment": {"OTHER_VAR": "value"}}
        assert get_active_enrichments(settings) == []

    def test_empty_env_value(self):
        settings = {"environment": {"CLAUDETRACING_ENRICHMENTS": ""}}
        assert get_active_enrichments(settings) == []

    def test_single_enrichment(self):
        settings = {"environment": {"CLAUDETRACING_ENRICHMENTS": "git"}}
        assert get_active_enrichments(settings) == ["git"]

    def test_multiple_enrichments(self):
        settings = {"environment": {"CLAUDETRACING_ENRICHMENTS": "git,files,tokens"}}
        assert get_active_enrichments(settings) == ["git", "files", "tokens"]

    def test_whitespace_handling(self):
        settings = {"environment": {"CLAUDETRACING_ENRICHMENTS": " git , files "}}
        assert get_active_enrichments(settings) == ["git", "files"]


class TestSetActiveEnrichments:
    def test_add_to_empty_settings(self):
        settings = {}
        result = _set_active_enrichments(settings, ["git", "files"])
        assert result["environment"]["CLAUDETRACING_ENRICHMENTS"] == "git,files"

    def test_add_to_existing_environment(self):
        settings = {"environment": {"OTHER_VAR": "value"}}
        result = _set_active_enrichments(settings, ["git"])
        assert result["environment"]["CLAUDETRACING_ENRICHMENTS"] == "git"
        assert result["environment"]["OTHER_VAR"] == "value"

    def test_clear_enrichments(self):
        settings = {"environment": {"CLAUDETRACING_ENRICHMENTS": "git,files"}}
        result = _set_active_enrichments(settings, [])
        assert "CLAUDETRACING_ENRICHMENTS" not in result["environment"]


class TestUpdateHookCommand:
    def test_switch_to_enriched_hook(self):
        settings = {
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": DEFAULT_HOOK_COMMAND}]}
                ]
            }
        }
        result = _update_hook_command(settings, use_enriched=True)
        assert (
            result["hooks"]["Stop"][0]["hooks"][0]["command"] == ENRICHED_HOOK_COMMAND
        )

    def test_switch_to_default_hook(self):
        settings = {
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": ENRICHED_HOOK_COMMAND}]}
                ]
            }
        }
        result = _update_hook_command(settings, use_enriched=False)
        assert result["hooks"]["Stop"][0]["hooks"][0]["command"] == DEFAULT_HOOK_COMMAND

    def test_flat_hook_structure(self):
        settings = {
            "hooks": {"Stop": [{"type": "command", "command": DEFAULT_HOOK_COMMAND}]}
        }
        result = _update_hook_command(settings, use_enriched=True)
        assert result["hooks"]["Stop"][0]["command"] == ENRICHED_HOOK_COMMAND

    def test_no_matching_hook(self):
        settings = {
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": "echo 'other'"}]}]
            }
        }
        result = _update_hook_command(settings, use_enriched=True)
        # Should return unchanged
        assert result["hooks"]["Stop"][0]["hooks"][0]["command"] == "echo 'other'"


class TestAddEnrichments:
    def test_add_single_enrichment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            # Create minimal settings
            settings = {
                "environment": {},
                "hooks": {"Stop": [{"hooks": [{"command": DEFAULT_HOOK_COMMAND}]}]},
            }
            save_settings(settings, project_root)

            success, msg = add_enrichments(["git"], project_root)

            assert success
            assert "Added: git" in msg

            loaded = load_settings(project_root)
            assert "git" in get_active_enrichments(loaded)

    def test_add_multiple_enrichments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            settings = {
                "environment": {},
                "hooks": {"Stop": [{"hooks": [{"command": DEFAULT_HOOK_COMMAND}]}]},
            }
            save_settings(settings, project_root)

            success, msg = add_enrichments(["git", "files", "tokens"], project_root)

            assert success
            assert "Added:" in msg
            assert "git" in msg and "files" in msg and "tokens" in msg

    def test_add_invalid_enrichment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            settings = {"environment": {}, "hooks": {"Stop": []}}
            save_settings(settings, project_root)

            success, msg = add_enrichments(["invalid"], project_root)

            assert not success
            assert "Unknown enrichment" in msg

    def test_add_already_active(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            settings = {
                "environment": {"CLAUDETRACING_ENRICHMENTS": "git"},
                "hooks": {"Stop": [{"hooks": [{"command": ENRICHED_HOOK_COMMAND}]}]},
            }
            save_settings(settings, project_root)

            success, msg = add_enrichments(["git"], project_root)

            assert not success
            assert "Already active" in msg

    def test_add_without_settings_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            success, msg = add_enrichments(["git"], project_root)

            assert not success
            assert "No .claude/settings.json found" in msg


class TestRemoveEnrichments:
    def test_remove_single_enrichment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            settings = {
                "environment": {"CLAUDETRACING_ENRICHMENTS": "git,files"},
                "hooks": {"Stop": [{"hooks": [{"command": ENRICHED_HOOK_COMMAND}]}]},
            }
            save_settings(settings, project_root)

            success, msg = remove_enrichments(["git"], project_root)

            assert success
            assert "Removed: git" in msg

            loaded = load_settings(project_root)
            active = get_active_enrichments(loaded)
            assert "git" not in active
            assert "files" in active

    def test_remove_all_enrichments_switches_hook(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            settings = {
                "environment": {"CLAUDETRACING_ENRICHMENTS": "git"},
                "hooks": {"Stop": [{"hooks": [{"command": ENRICHED_HOOK_COMMAND}]}]},
            }
            save_settings(settings, project_root)

            success, msg = remove_enrichments(["git"], project_root)

            assert success
            loaded = load_settings(project_root)
            # Should switch back to default hook
            assert (
                DEFAULT_HOOK_COMMAND
                in loaded["hooks"]["Stop"][0]["hooks"][0]["command"]
            )

    def test_remove_invalid_enrichment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            settings = {"environment": {}, "hooks": {"Stop": []}}
            save_settings(settings, project_root)

            success, msg = remove_enrichments(["invalid"], project_root)

            assert not success
            assert "Unknown enrichment" in msg

    def test_remove_not_active(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            settings = {"environment": {}, "hooks": {"Stop": []}}
            save_settings(settings, project_root)

            success, msg = remove_enrichments(["git"], project_root)

            assert not success
            assert "Not currently active" in msg


class TestLoadSaveSettings:
    def test_load_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert load_settings(Path(tmpdir)) is None

    def test_save_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            settings = {"test": "value"}

            path = save_settings(settings, project_root)

            assert path.exists()
            assert json.loads(path.read_text()) == settings

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            settings = {"environment": {"FOO": "bar"}, "hooks": {"Stop": []}}

            save_settings(settings, project_root)
            loaded = load_settings(project_root)

            assert loaded == settings
