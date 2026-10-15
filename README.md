# `claudetracing` — Unified MLflow Tracing for Coding Agents

[![PyPI version](https://img.shields.io/pypi/v/claudetracing.svg)](https://pypi.org/project/claudetracing/)
[![Python versions](https://img.shields.io/pypi/pyversions/claudetracing.svg)](https://pypi.org/project/claudetracing/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/CauchyIO/claudetracing/actions/workflows/ci.yml/badge.svg)](https://github.com/CauchyIO/claudetracing/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/CauchyIO/claudetracing/branch/master/graph/badge.svg)](https://codecov.io/gh/CauchyIO/claudetracing)

Set up MLflow Tracing for **Claude Code**, **OpenAI Codex**, **GitHub Copilot**, and **Google Antigravity (`agy`)** in a single command.

- **One command, four agents**: Point all of your coding agents at the same MLflow experiment with `traces init`.
- **Works with any MLflow backend**: Databricks (OAuth profile or headless service principal), a self-hosted MLflow server, or a local `mlflow server`.
- **Safe to commit**: Shareable project config is separated from personal Databricks profile names and bearer tokens, which stay in gitignored `.local.json` files.

## Install

```bash
uv add claudetracing
# or: pip install claudetracing
```

## Quick Start

Run the interactive wizard inside your repo:

```bash
traces init
```

Or configure everything non-interactively:

```bash
# Databricks (using a profile from ~/.databrickscfg)
traces init --agent all --profile my-workspace --yes

# Databricks (headless / CI service principal)
traces init --agent all --spn --yes

# Self-hosted MLflow server
traces init --agent all --tracking-uri https://mlflow.example.com --token $MLFLOW_TRACKING_TOKEN --yes

# Local MLflow server (http://localhost:5000)
traces init --agent all --tracking-uri http://localhost:5000 --yes
```

Use `--agent` to target specific harnesses (`all`, `both` for Claude + Codex, `claude`, `codex`, `copilot` / `ghcp`, or `agy` / `antigravity`), or `-e <name>` / `--experiment-id <id>` to pick a custom experiment (defaults to `/Workspace/Shared/<repo>` on Databricks or `<repo>` elsewhere).

## CLI Reference

```bash
traces init                         # Configure tracing (interactive or with flags)
traces codex init                   # Configure OpenAI Codex only
traces copilot init                 # Configure GitHub Copilot only
traces agy init                     # Configure Google Antigravity (agy) only
traces status                       # Check tracing status across all 4 agents
traces disable                      # Remove tracing config from the current repo

traces list                         # List MLflow experiments
traces search                       # Show recent traces for this project
traces search --hours 24 -l 20      # Last 24h, up to 20 traces
traces search --since 2026-10-01    # Since an ISO-8601 date/timestamp
traces search --trace-id <id>       # Inspect a single trace
traces search -f [summary|json|context|tools]
```

## Supported Agents

| Agent | Committed Project Config | Gitignored Local Config | Prerequisites |
| :--- | :--- | :--- | :--- |
| **Claude Code** | `.claude/settings.json` | `.claude/settings.local.json` | Official `@mlflow/claude-code` plugin (installed automatically) |
| **OpenAI Codex** | `.codex/config.toml` | `.codex/mlflow-tracing.json` | `npm install -g @mlflow/codex` |
| **GitHub Copilot** | `.github/hooks/mlflow-tracing.json` | `.github/hooks/mlflow-tracing.local.json` | `claudetracing` on `PATH` |
| **Antigravity (`agy`)** | `.agents/hooks.json` | `.agents/mlflow-tracing.json` | `claudetracing` on `PATH` |

Every traced turn records prompts, responses, reasoning/thinking blocks, tool calls and outputs, token usage, git branch/commit tags, and session metadata in MLflow.

## Releasing

Merging a version bump to `master` cuts the release automatically:

1. Bump the version in your PR: `uv version --bump patch` (or `minor` / `major`).
2. Add a `## v<version>` section to [`CHANGELOG.md`](CHANGELOG.md).
3. Merge to `master` — CI builds the wheel, publishes to PyPI, tags `v<version>`, and creates the GitHub Release from that changelog section.

## License

MIT
