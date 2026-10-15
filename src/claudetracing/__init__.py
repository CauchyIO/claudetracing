"""Standardized MLflow tracing setup and CLI for Claude Code, Codex, Copilot, and Antigravity."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("claudetracing")
except PackageNotFoundError:
    __version__ = "0.6.0"
