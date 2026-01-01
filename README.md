# Claude Code MLflow Tracing

[![PyPI version](https://img.shields.io/pypi/v/claudetracing.svg)](https://pypi.org/project/claudetracing/)
[![Python versions](https://img.shields.io/pypi/pyversions/claudetracing.svg)](https://pypi.org/project/claudetracing/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/CauchyIO/claudetracing/actions/workflows/ci.yml/badge.svg)](https://github.com/CauchyIO/claudetracing/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/CauchyIO/claudetracing/branch/master/graph/badge.svg)](https://codecov.io/gh/CauchyIO/claudetracing)

A simple helper CLI to help you setup the MLFlow tracing in Claude Code in Databricks. While the MLFlow documentation already can set up claude code tracing for you with the command `mlflow autolog claude` this goes a step further in guiding you through the process such to make sure your experiments have the same naming convention as well as use the correct profile and prevent the use of a PAT.


## Installation

```bash
uv add claudetracing
```

Or with pip:
```bash
pip install claudetracing
```

## Quick Start

Run the interactive setup in your project directory:

```bash
traces init
```

This will:
1. Authenticate with Databricks (or use existing credentials)
2. Configure your experiment path (shared or personal)
3. Create `.claude/settings.json` with the proper hooks
4. Update `.gitignore`

Restart Claude Code after setup. Traces are automatically sent to Databricks when sessions end.

## CLI Commands

```bash
traces init                      # Interactive setup
traces list                      # List available experiments
traces search                    # Search recent traces
traces search -e <experiment>    # Filter by experiment name
traces search --hours 24         # Last 24 hours
traces search --trace-id <id>    # Get specific trace
traces search -f json            # Output as JSON
traces search -f context         # LLM-optimized format
```

## Enrichments

Enrichments add extra metadata to your traces. They are optional and can be enabled per-project. Multiple enrichments can be active simultaneously.

### Available Enrichments

| Name | Description |
|------|-------------|
| `git` | Adds git repository context: commit ID, branch, remote URL, repo name |
| `files` | Adds list of files modified (written/edited) during the session |
| `tokens` | Adds token usage statistics including cache metrics |

### Managing Enrichments

```bash
traces enrichment list              # List available enrichments
traces enrichment info git          # Show details about an enrichment
traces enrichment add git files     # Enable multiple enrichments
traces enrichment remove tokens     # Disable an enrichment
```

After adding or removing enrichments, restart Claude Code to apply the changes.

### Git Enrichment

Correlate traces with specific commits and branches:

- `git.commit_id` - Full commit SHA
- `git.branch` - Current branch name
- `git.remote_url` - Origin remote URL
- `git.repo_name` - Repository name (e.g., `org/repo`)

### Files Enrichment

Track which files were modified during the session:

- `files.modified` - JSON array of file paths that were written or edited

### Tokens Enrichment

Monitor token consumption and cache efficiency:

- `tokens.input` - Total input tokens
- `tokens.output` - Total output tokens
- `tokens.cache_read` - Tokens read from prompt cache
- `tokens.cache_creation` - Tokens written to prompt cache
- `tokens.total` - Total tokens (input + output)

---

MLflow tracing for Claude Code sessions with Databricks integration. Automatically captures conversations, tool usage, and session metadata.

## Why Trace Claude Code Sessions?

When Claude Code becomes part of your development workflow, visibility into how it's being used becomes valuable:

- **Review past sessions** - What did Claude do while you were away? Search and replay any session to understand decisions made.
- **Team insights** - See how your team uses Claude Code across projects. Identify patterns, common tasks, and areas for improvement.
- **Debug failures** - When something goes wrong, trace data shows exactly which tools were called, in what order, and what inputs/outputs were involved.
- **Cost awareness** - Track token usage and session duration to understand resource consumption.
- **Compliance & audit** - Maintain records of AI-assisted code changes for regulated environments.

## Prerequisites

- Python 3.10+
- [Databricks CLI](https://docs.databricks.com/dev-tools/cli/index.html) installed
- Access to a Databricks workspace

## What Gets Traced

- User prompts and Claude responses
- Tool usage (Read, Write, Edit, Bash, etc.)
- Execution timing per operation
- Session metadata (user, working directory, git branch)

## How It Works

1. The `traces init` command creates a `.claude/settings.json` file
2. This configures a Stop hook that runs when Claude Code sessions end
3. The hook calls MLflow's built-in Claude Code tracing to capture the session
4. Traces are uploaded to your Databricks MLflow experiment

## FAQ

### Why might my traces have different metadata than my teammate's?

Enrichment configuration is stored locally per-user in `.claude/settings.json`. If teammates configure different enrichments, their traces will have different tags. See [ADR-001](docs/adr/001-enrichment-consistency.md) for the design rationale and options considered.

### Can I join an existing experiment with different enrichments?

Currently yes, but this creates inconsistent trace data. We recommend teams align on enrichment configuration when sharing an experiment.

## License

MIT

---

Built with [Claude Opus 4.5](https://www.anthropic.com/claude)
