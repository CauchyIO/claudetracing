"""Tests for the git_enrichment module."""

from unittest.mock import patch, MagicMock

from claudetracing.git_enrichment import (
    _git_cmd,
    is_git_repo,
    get_git_metadata,
    get_recent_commits,
)


class TestGitCmd:
    def test_successful_command(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="output\n")
            result = _git_cmd(["status"])
            assert result == "output"

    def test_failed_command(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            result = _git_cmd(["invalid"])
            assert result is None

    def test_exception_handling(self):
        with patch("subprocess.run", side_effect=Exception("error")):
            result = _git_cmd(["status"])
            assert result is None


class TestIsGitRepo:
    def test_is_git_repo_true(self):
        with patch("claudetracing.git_enrichment._git_cmd", return_value=".git"):
            assert is_git_repo() is True

    def test_is_git_repo_false(self):
        with patch("claudetracing.git_enrichment._git_cmd", return_value=None):
            assert is_git_repo() is False


class TestGetGitMetadata:
    def test_not_a_git_repo(self):
        with patch("claudetracing.git_enrichment.is_git_repo", return_value=False):
            assert get_git_metadata() == {}

    def test_https_remote_url(self):
        def mock_git_cmd(args, cwd=None):
            commands = {
                ("rev-parse", "HEAD"): "abc123def456",
                ("rev-parse", "--abbrev-ref", "HEAD"): "main",
                ("remote", "get-url", "origin"): "https://github.com/myorg/myrepo.git",
                ("rev-parse", "--show-toplevel"): "/path/to/repo",
            }
            return commands.get(tuple(args))

        with patch("claudetracing.git_enrichment.is_git_repo", return_value=True):
            with patch(
                "claudetracing.git_enrichment._git_cmd", side_effect=mock_git_cmd
            ):
                metadata = get_git_metadata()

                assert metadata["git.commit_id"] == "abc123def456"
                assert metadata["git.branch"] == "main"
                assert (
                    metadata["git.remote_url"] == "https://github.com/myorg/myrepo.git"
                )
                assert metadata["git.repo_name"] == "myorg/myrepo"

    def test_ssh_remote_url(self):
        def mock_git_cmd(args, cwd=None):
            commands = {
                ("rev-parse", "HEAD"): "abc123",
                ("rev-parse", "--abbrev-ref", "HEAD"): "feature",
                ("remote", "get-url", "origin"): "git@github.com:myorg/myrepo.git",
                ("rev-parse", "--show-toplevel"): "/path/to/repo",
            }
            return commands.get(tuple(args))

        with patch("claudetracing.git_enrichment.is_git_repo", return_value=True):
            with patch(
                "claudetracing.git_enrichment._git_cmd", side_effect=mock_git_cmd
            ):
                metadata = get_git_metadata()

                assert metadata["git.repo_name"] == "myorg/myrepo"

    def test_no_remote_uses_directory_name(self):
        def mock_git_cmd(args, cwd=None):
            commands = {
                ("rev-parse", "HEAD"): "abc123",
                ("rev-parse", "--abbrev-ref", "HEAD"): "main",
                ("remote", "get-url", "origin"): None,
                ("rev-parse", "--show-toplevel"): "/home/user/my-project",
            }
            return commands.get(tuple(args))

        with patch("claudetracing.git_enrichment.is_git_repo", return_value=True):
            with patch(
                "claudetracing.git_enrichment._git_cmd", side_effect=mock_git_cmd
            ):
                metadata = get_git_metadata()

                assert metadata["git.repo_name"] == "my-project"
                assert "git.remote_url" not in metadata

    def test_filters_none_values(self):
        def mock_git_cmd(args, cwd=None):
            commands = {
                ("rev-parse", "HEAD"): "abc123",
                ("rev-parse", "--abbrev-ref", "HEAD"): None,
                ("remote", "get-url", "origin"): None,
                ("rev-parse", "--show-toplevel"): None,
            }
            return commands.get(tuple(args))

        with patch("claudetracing.git_enrichment.is_git_repo", return_value=True):
            with patch(
                "claudetracing.git_enrichment._git_cmd", side_effect=mock_git_cmd
            ):
                metadata = get_git_metadata()

                assert "git.commit_id" in metadata
                assert "git.branch" not in metadata
                assert "git.remote_url" not in metadata
                assert "git.repo_name" not in metadata

    def test_https_url_without_git_suffix(self):
        def mock_git_cmd(args, cwd=None):
            commands = {
                ("rev-parse", "HEAD"): "abc123",
                ("rev-parse", "--abbrev-ref", "HEAD"): "main",
                ("remote", "get-url", "origin"): "https://github.com/myorg/myrepo",
                ("rev-parse", "--show-toplevel"): "/path/to/repo",
            }
            return commands.get(tuple(args))

        with patch("claudetracing.git_enrichment.is_git_repo", return_value=True):
            with patch(
                "claudetracing.git_enrichment._git_cmd", side_effect=mock_git_cmd
            ):
                metadata = get_git_metadata()
                assert metadata["git.repo_name"] == "myorg/myrepo"

    def test_https_url_with_trailing_slash(self):
        def mock_git_cmd(args, cwd=None):
            commands = {
                ("rev-parse", "HEAD"): "abc123",
                ("rev-parse", "--abbrev-ref", "HEAD"): "main",
                ("remote", "get-url", "origin"): "https://github.com/myorg/myrepo/",
                ("rev-parse", "--show-toplevel"): "/path/to/repo",
            }
            return commands.get(tuple(args))

        with patch("claudetracing.git_enrichment.is_git_repo", return_value=True):
            with patch(
                "claudetracing.git_enrichment._git_cmd", side_effect=mock_git_cmd
            ):
                metadata = get_git_metadata()
                assert metadata["git.repo_name"] == "myorg/myrepo"


class TestGetRecentCommits:
    def test_not_a_git_repo(self):
        with patch("claudetracing.git_enrichment.is_git_repo", return_value=False):
            assert get_recent_commits() == []

    def test_empty_log(self):
        with patch("claudetracing.git_enrichment.is_git_repo", return_value=True):
            with patch("claudetracing.git_enrichment._git_cmd", return_value=None):
                assert get_recent_commits() == []

    def test_parse_commits(self):
        log_output = (
            "abc123|abc1|Alice|2024-01-15T10:30:00+00:00|Initial commit\n"
            "def456|def4|Bob|2024-01-16T11:00:00+00:00|Add feature"
        )

        with patch("claudetracing.git_enrichment.is_git_repo", return_value=True):
            with patch(
                "claudetracing.git_enrichment._git_cmd", return_value=log_output
            ):
                commits = get_recent_commits(n=2)

                assert len(commits) == 2
                assert commits[0]["hash"] == "abc123"
                assert commits[0]["short_hash"] == "abc1"
                assert commits[0]["author"] == "Alice"
                assert commits[0]["date"] == "2024-01-15T10:30:00+00:00"
                assert commits[0]["subject"] == "Initial commit"

    def test_commit_subject_with_pipe(self):
        log_output = (
            "abc123|abc1|Alice|2024-01-15T10:30:00+00:00|Fix bug | handle edge case"
        )

        with patch("claudetracing.git_enrichment.is_git_repo", return_value=True):
            with patch(
                "claudetracing.git_enrichment._git_cmd", return_value=log_output
            ):
                commits = get_recent_commits(n=1)

                assert len(commits) == 1
                assert commits[0]["subject"] == "Fix bug | handle edge case"

    def test_skips_malformed_lines(self):
        log_output = (
            "abc123|abc1|Alice|2024-01-15T10:30:00+00:00|Good commit\n"
            "malformed line\n"
            "def456|def4|Bob|2024-01-16T11:00:00+00:00|Another good commit"
        )

        with patch("claudetracing.git_enrichment.is_git_repo", return_value=True):
            with patch(
                "claudetracing.git_enrichment._git_cmd", return_value=log_output
            ):
                commits = get_recent_commits(n=3)

                assert len(commits) == 2

    def test_handles_empty_lines(self):
        log_output = "abc123|abc1|Alice|2024-01-15T10:30:00+00:00|Commit\n\n"

        with patch("claudetracing.git_enrichment.is_git_repo", return_value=True):
            with patch(
                "claudetracing.git_enrichment._git_cmd", return_value=log_output
            ):
                commits = get_recent_commits(n=1)

                assert len(commits) == 1
