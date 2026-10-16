# claudetracing

[![PyPI version](https://img.shields.io/pypi/v/claudetracing.svg)](https://pypi.org/project/claudetracing/)
[![Python versions](https://img.shields.io/pypi/pyversions/claudetracing.svg)](https://pypi.org/project/claudetracing/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/CauchyIO/claudetracing/actions/workflows/ci.yml/badge.svg)](https://github.com/CauchyIO/claudetracing/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/CauchyIO/claudetracing/branch/master/graph/badge.svg)](https://codecov.io/gh/CauchyIO/claudetracing)

CLI to set up MLflow tracing for Claude Code, Codex, GitHub Copilot, and Antigravity (`agy`).

## Why this exists

MLflow supports tracing coding agents, but each agent uses a different config file, hook format, and environment setup. Some agents accept an experiment name while others (`@mlflow/codex`) require a numeric experiment ID, and putting Databricks profiles or bearer tokens directly into project config files makes them easy to leak into git.

`claudetracing` standardizes that setup across a project and team:

- **One setup for whichever agent you use**: Run `traces init` once in a repo to wire up Claude Code, Codex, Copilot, and Antigravity against the same MLflow experiment (defaulting to `/Workspace/Shared/<repo>` on Databricks). Teammates can switch between agents and still log to the same place.
- **Shared project config, local credentials**: Project-level settings (experiment name/ID, enabled plugins, hooks) are written to files you can commit to the repo, while personal `~/.databrickscfg` profile names and tokens stay in gitignored `.local.json` files. The same committed config also works headlessly in CI with a service principal (`--spn`).
- **No manual wiring**: It creates or looks up the MLflow experiment ID up front, installs the Claude Code plugin, chains into Codex Desktop's notify hook without clobbering it, and updates `.gitignore`.

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
