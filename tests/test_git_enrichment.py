"""Tests for the git_enrichment module."""

import subprocess
from unittest.mock import patch, MagicMock

import pytest

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

    def test_git_not_installed_raises(self):
        """Exceptions propagate instead of being silently caught."""
        with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
            with pytest.raises(FileNotFoundError):
                get_git_metadata()

    def test_timeout_raises(self):
        """Timeout exceptions propagate instead of being silently caught."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 5)):
            with pytest.raises(subprocess.TimeoutExpired):
                get_git_metadata()
