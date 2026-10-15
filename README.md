# claudetracing

[![PyPI version](https://img.shields.io/pypi/v/claudetracing.svg)](https://pypi.org/project/claudetracing/)
[![Python versions](https://img.shields.io/pypi/pyversions/claudetracing.svg)](https://pypi.org/project/claudetracing/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/CauchyIO/claudetracing/actions/workflows/ci.yml/badge.svg)](https://github.com/CauchyIO/claudetracing/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/CauchyIO/claudetracing/branch/master/graph/badge.svg)](https://codecov.io/gh/CauchyIO/claudetracing)

CLI to set up MLflow tracing for Claude Code, Codex, GitHub Copilot, and Antigravity (`agy`).

It writes the config files each agent expects, resolves the experiment ID up front, and keeps personal Databricks profiles and tokens in gitignored `.local.json` files so the shared project config can be committed.

## Install

```bash
uv add claudetracing
# or: pip install claudetracing
```

## Setup

Run interactively in your repo:

```bash
traces init
```

Or pass flags directly:

```bash
# Databricks (CLI profile from ~/.databrickscfg)
traces init --agent all --profile my-workspace --yes

# Databricks (headless / CI service principal via DATABRICKS_* env vars)
traces init --agent all --spn --yes

# Self-hosted MLflow
traces init --agent all --tracking-uri https://mlflow.example.com --token $MLFLOW_TRACKING_TOKEN --yes

# Local MLflow (http://localhost:5000)
traces init --agent all --tracking-uri http://localhost:5000 --yes
```

`--agent` accepts `all`, `both` (Claude + Codex), `claude`, `codex`, `copilot` (`ghcp`), or `agy` (`antigravity`).
Experiment names default to `/Workspace/Shared/<repo>` on Databricks and `<repo>` elsewhere; override with `-e <name>` or `--experiment-id <id>`.

## Commands

```bash
traces init                         # Configure tracing
traces codex init                   # Configure Codex only
traces copilot init                 # Configure Copilot only
traces agy init                     # Configure Antigravity only
traces status                       # Show config status per agent
traces disable                      # Remove tracing config from the repo

traces list                         # List experiments
traces search                       # Recent traces for this project
traces search --hours 24 -l 20      # Last 24h, limit 20
traces search --since 2026-10-01    # Since ISO date/timestamp
traces search --trace-id <id>       # Single trace by ID
traces search -f [summary|json|context|tools]
```

## What gets written

| Agent | Committed | Gitignored | Notes |
| :--- | :--- | :--- | :--- |
| Claude Code | `.claude/settings.json` | `.claude/settings.local.json` | Installs `mlflow-tracing@mlflow-plugins` |
| Codex | `.codex/config.toml` | `.codex/mlflow-tracing.json` | Requires `npm i -g @mlflow/codex` |
| Copilot | `.github/hooks/mlflow-tracing.json` | `.github/hooks/mlflow-tracing.local.json` | Runs `traces copilot-hook` on stop |
| Antigravity | `.agents/hooks.json` | `.agents/mlflow-tracing.json` | Runs `traces agy-hook` on stop |

## Releasing

Bump the version in `pyproject.toml` and add a `## v<version>` section to `CHANGELOG.md`:

```bash
uv version --bump patch   # or minor / major
```

Merging to `master` builds the package, publishes to PyPI, tags `v<version>`, and creates the GitHub release from `CHANGELOG.md`.

## License

MIT
