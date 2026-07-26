"""Tests for the model enrichment."""

import json

from claudetracing.hooks import _extract_model_usage, _get_model_attributes


class FakeLogger:
    def debug(self, *args):
        pass


def write_transcript(tmp_path, models):
    path = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps({"type": "assistant", "message": {"model": m, "content": []}})
        for m in models
    ]
    path.write_text("\n".join(lines))
    return str(path)


class TestExtractModelUsage:
    def test_single_model_counted(self, tmp_path):
        path = write_transcript(tmp_path, ["claude-opus-5"] * 3)
        assert _extract_model_usage(path) == {"claude-opus-5": 3}

    def test_skips_synthetic_missing_and_blank_lines(self, tmp_path):
        path = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps({"type": "assistant", "message": {"model": "claude-opus-5"}}),
            json.dumps({"type": "assistant", "message": {"model": "<synthetic>"}}),
            json.dumps({"type": "user", "message": {"content": "hi"}}),
            "",
        ]
        path.write_text("\n".join(lines))
        assert _extract_model_usage(str(path)) == {"claude-opus-5": 1}


class TestGetModelAttributes:
    def test_mixed_models_lists_all_and_picks_primary(self, tmp_path):
        path = write_transcript(
            tmp_path, ["claude-opus-5", "claude-haiku-4-5", "claude-opus-5"]
        )
        tags = _get_model_attributes(path, FakeLogger())
        assert tags == {
            "model": "claude-haiku-4-5, claude-opus-5",
            "model.primary": "claude-opus-5",
        }

    def test_empty_transcript_yields_no_tags(self, tmp_path):
        path = tmp_path / "transcript.jsonl"
        path.write_text("")
        assert _get_model_attributes(str(path), FakeLogger()) == {}

    def test_tie_breaks_deterministically_on_name(self, tmp_path):
        path = write_transcript(tmp_path, ["claude-opus-5", "claude-haiku-4-5"])
        tags = _get_model_attributes(path, FakeLogger())
        assert tags["model.primary"] == "claude-opus-5"
