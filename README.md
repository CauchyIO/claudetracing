# Coding Agent MLflow Tracing (`claudetracing`)

[![PyPI version](https://img.shields.io/pypi/v/claudetracing.svg)](https://pypi.org/project/claudetracing/)
[![Python versions](https://img.shields.io/pypi/pyversions/claudetracing.svg)](https://pypi.org/project/claudetracing/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/CauchyIO/claudetracing/actions/workflows/ci.yml/badge.svg)](https://github.com/CauchyIO/claudetracing/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/CauchyIO/claudetracing/branch/master/graph/badge.svg)](https://codecov.io/gh/CauchyIO/claudetracing)

A lightweight helper CLI that standardizes MLflow Tracing setup across **Claude Code**, **OpenAI Codex CLI**, **GitHub Copilot** (`copilot` CLI / VS Code Copilot), and **Google Antigravity** (`agy` CLI / IDE).

`claudetracing` streamlines team setup by:
- **Configuring all four coding agents in one step** (`claude`, `codex`, `copilot`, `agy`) with the same experiment and backend.
- **Standardizing experiment naming** (e.g., `/Workspace/Shared/<project>` on Databricks or resolving experiment names to IDs automatically across agents).
- **Supporting Databricks, Self-Hosted MLflow Servers, and Local MLflow Servers** out of the box.
- **Preventing credential/profile leaks in git** by storing machine-specific Databricks OAuth profiles and bearer tokens in gitignored `.local.json` / local config files while keeping project settings shareable across teammates and headless service-principal (SPN) environments.

## Installation

```bash
uv add claudetracing
```

Or with pip:
```bash
pip install claudetracing
```

## Quick Start

Run the interactive setup wizard in your project directory:

```bash
traces init
```

The wizard will guide you through:
1. Choosing which agent(s) to configure (**All**, **Claude Code + Codex**, **Claude Code only**, **Codex only**, **GitHub Copilot only**, or **Google Antigravity (AGY) only**)
2. Selecting your storage backend:
   - **Databricks** (OAuth / CLI profile from `~/.databrickscfg` — no PAT required)
   - **Self-hosted MLflow Server** (`http://` or `https://` URL, with optional bearer token)
   - **Local MLflow Server** (`http://localhost:5000`)
3. Resolving or creating your MLflow experiment and writing the standard configuration files
4. Updating `.gitignore`

### Non-Interactive / Flag-Driven Setup

```bash
# Configure all 4 agents (Claude Code, Codex, Copilot, Antigravity) in one shot
traces init --agent all --tracking-uri http://localhost:5000 --experiment my-project --yes

# Databricks (using a CLI/OAuth profile from ~/.databrickscfg)
traces init --agent all --profile my-workspace --experiment /Workspace/Shared/my-project --yes

# Databricks headless / service-principal mode (uses DATABRICKS_HOST/CLIENT_ID/CLIENT_SECRET at runtime)
traces init --agent all --spn --experiment /Workspace/Shared/my-project --yes

# Self-hosted MLflow server (with optional bearer token saved to gitignored local config files)
traces init --agent all --tracking-uri https://mlflow.example.com --experiment my-project --token $MLFLOW_TRACKING_TOKEN --yes

# Configure a specific agent (--agent aliases: ghcp → copilot, antigravity → agy)
traces init --agent claude --tracking-uri https://mlflow.example.com --experiment my-project --yes
traces init --agent codex --tracking-uri https://mlflow.example.com --experiment my-project --yes
traces init --agent copilot --tracking-uri https://mlflow.example.com --experiment my-project --yes
traces init --agent agy --tracking-uri https://mlflow.example.com --experiment my-project --yes

# Pass an existing experiment ID instead of a name (skips create-or-resolve)
traces init --agent all --tracking-uri http://localhost:5000 --experiment-id 42 --yes

# Optional Unity Catalog trace destination (catalog.schema.table_prefix)
traces init --agent all --profile my-workspace --experiment /Workspace/Shared/my-project --trace-location main.genai.traces --yes
```

## CLI Commands

```bash
traces --version                 # Print installed version (also: traces -V, traces version)
traces init                      # Interactive or flag-based setup for Claude, Codex, Copilot & AGY
traces codex init                # Shortcut to configure Codex CLI only
traces copilot init              # Shortcut to configure GitHub Copilot only
traces agy init                  # Shortcut to configure Google Antigravity (AGY) only
traces status                    # Show current tracing status across all 4 agents
traces disable                   # Disable tracing in the current project across all 4 agents
traces list                      # List available experiments
traces search                    # Search recent traces in the project's experiment
traces search -e <experiment>    # Filter by experiment name
traces search --experiment-id <id>  # Filter by experiment ID (numeric)
traces search --hours 24         # Search last 24 hours
traces search --since 2026-10-01T00:00:00  # Search since an ISO-8601 timestamp
traces search --limit 50         # Return at most 50 traces (also: -l 50)
traces search --trace-id <id>    # Get specific trace by ID
traces search -f json            # Output as JSON
traces search -f context         # LLM-optimized format
traces search -f tools           # Summarize tool usage across traces
```

## How Each Agent Is Configured

### 1. Claude Code (`@mlflow/claude-code`)
- Installs the official `mlflow-tracing@mlflow-plugins` Claude Code plugin (`mlflow.claude_code.plugin`) and enables `"enabledPlugins": {"mlflow-tracing@mlflow-plugins": true}` in `.claude/settings.json`.
- Writes `.claude/settings.json` using Claude Code's native `"env"` block (`MLFLOW_CLAUDE_TRACING_ENABLED`, `MLFLOW_TRACKING_URI`, `MLFLOW_EXPERIMENT_ID`, `MLFLOW_EXPERIMENT_NAME`).
- Stores machine-specific overrides (`MLFLOW_TRACKING_URI=databricks://<profile>`, `DATABRICKS_CONFIG_PROFILE`, or `MLFLOW_TRACKING_TOKEN`) in the gitignored `.claude/settings.local.json`.

### 2. OpenAI Codex CLI (`@mlflow/codex`)
- Registers `notify = ["mlflow-codex", "notify-hook"]` in `./.codex/config.toml` and syncs `$CODEX_HOME/config.toml` (including chaining into Codex Desktop's `SkyComputerUseClient turn-ended --previous-notify` wrapper when present) while preserving existing TOML comments and sections.
- Writes `trackingUri` and resolved `experimentId` to `./.codex/mlflow-tracing.json`.
- Requires the official `@mlflow/codex` package (`npm install -g @mlflow/codex`).

### 3. GitHub Copilot (`copilot` CLI / VS Code Copilot)
- Writes `.github/hooks/mlflow-tracing.json` (`SessionStart` and `Stop` hooks invoking `traces copilot-hook session-start` and `traces copilot-hook stop`) and gitignored `.github/hooks/mlflow-tracing.local.json`.
- Converts Copilot JSONL transcripts (`user.message`, `assistant.message` with `toolRequests` and `reasoningText`, `tool.execution_complete`) into Claude Code JSONL format and delegates trace creation to `mlflow.claude_code.tracing.process_transcript()`.

### 4. Google Antigravity (`agy` CLI / IDE)
- Writes `.agents/hooks.json` with a top-level `"mlflow-tracing"` named `Stop` hook (preserving any other named hooks in `.agents/hooks.json`) and gitignored `.agents/mlflow-tracing.json`.
- Converts Antigravity `transcript.jsonl` / `transcript_full.jsonl` trajectories (`USER_INPUT`, `PLANNER_RESPONSE` with `thinking`, `tool_calls`, and token `usage`, plus `GENERIC` tool outputs) into Claude Code JSONL format and delegates trace creation to `mlflow.claude_code.tracing.process_transcript()`.

## Built-in Telemetry Captured in MLflow
- User prompts, assistant responses, and reasoning / thinking blocks
- Tool calls and outputs (`Read`, `Write`, `Edit`, `Bash`, `exec_command`, `run_in_terminal`, `run_command`, etc.)
- Subagent invocations as nested spans
- Per-call and per-session token usage (input, output, cache read/creation) and estimated cost
- Git provenance (`mlflow.source.git.commit`, `mlflow.source.git.branch`, `mlflow.source.git.repoURL`)
- Session metadata (user, working directory, model, permission mode, agent version)

## Releasing

Cutting a release is the merge that bumps the version, nothing else. In the pull request that changes the package:

```bash
uv version --bump patch   # or minor / major
```

Then add a `## v<version>` section to `CHANGELOG.md` describing the change. CI refuses a pull request that touches `src/` or `pyproject.toml` without a bump, a bump that is not above the latest tag, or a bump without its changelog section (`tools/check_version_bump.py`). When the pull request lands on `master`, CI builds the package, publishes it to PyPI through trusted publishing, tags the commit, and creates the GitHub release with the changelog section as its body. No tag is pushed by hand.

## License

MIT
