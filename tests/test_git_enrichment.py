"""Tests for the git_enrichment module."""

from unittest.mock import patch, MagicMock

from claudetracing.git_enrichment import get_git_metadata


class TestGetGitMetadata:
    def test_returns_git_info(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="abc123\n")
            metadata = get_git_metadata()
            assert "git.commit_id" in metadata

    def test_not_a_git_repo(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=128, stdout="")
            assert get_git_metadata() == {}

    def test_handles_exceptions(self):
        with patch("subprocess.run", side_effect=Exception("error")):
            assert get_git_metadata() == {}
