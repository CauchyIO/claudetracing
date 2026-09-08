# Claude Code and Codex MLflow Tracing

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

## Codex support

Configure a project using a Databricks profile (OAuth/CLI authentication; no PAT required):

```bash
traces codex init --profile my-workspace --experiment /Workspace/Shared/my-project
```

Or use a tracking server or local storage:

```bash
traces codex init --tracking-uri http://localhost:5000 --experiment my-project
traces codex init --experiment my-project  # SQLite and artifacts under CODEX_HOME
```

For a headless Databricks environment, use `--tracking-uri databricks` and supply
`DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, and `DATABRICKS_CLIENT_SECRET` through the
environment. `--profile` and `--tracking-uri` are mutually exclusive. `--yes` skips
the installation confirmation.

Restart Codex after setup. This integration is Python-native; it does not require
Node.js or `@mlflow/codex`.

### What setup changes

Codex CLI 0.153.4 ignores project-level `notify` entries, so setup installs the hook
in `$CODEX_HOME/config.toml` (`~/.codex/config.toml` by default). It preserves TOML
comments, unrelated settings, and the existing notification command. The original
config is backed up once as `config.before-claudetracing.toml`.

Project paths and tracing destinations are registered in
`$CODEX_HOME/claudetracing.json`, outside the project repository. Only registered
directories and their descendants are traced; the most specific registration wins.
Other projects still receive the original notification. Setup can be repeated for
multiple projects without chaining duplicate hooks. The hook uses the Python
interpreter that ran setup, so keep that environment installed.

### Conversation capture and replay

- Each completed turn becomes an AGENT trace grouped by Codex thread ID. Prompts
  and assistant messages are retained on the root span; TOOL spans include both
  `function_call` and `custom_tool_call` inputs/results and recorded timestamps.
- Token counts are deltas of Codex's cumulative usage, rather than repeated sums
  of the session total. The serving model is recorded as a trace tag.
- Each notification scans the persisted rollout for missed completed turns.
  Local checkpoints skip turns already exported successfully; per-session locks
  serialize overlapping notifications.
- By default, the entire available rollout is also saved as
  `conversation/rollout.jsonl` in an MLflow run tagged `codex.session_id`. A
  `codex.rollout_sha256` tag verifies the snapshot. This retains unsupported record
  types, instructions, and partial turns that the readable trace view omits.
  Choose `--no-archive` during setup to disable this additional raw upload.

Exports run in a detached worker so a short-lived Codex CLI process can exit
without cutting off the upload. Failures are recorded in
`$CODEX_HOME/claudetracing/errors.log`; worker/notifier output is in `notify.log`.
After resolving a connectivity or authentication problem, replay from the
configured project directory:

```bash
traces codex replay <thread-uuid>
```

`MLFLOW_TRACKING_URI`, `MLFLOW_EXPERIMENT_NAME`, and `MLFLOW_EXPERIMENT_ID` in the
Codex launch environment override the registered destination. Credentials stay in
Databricks profiles or environment variables, not in generated tracing settings.

Capture requires a local rollout under `$CODEX_HOME/sessions`. Ephemeral sessions
and remote subagent transcripts are not recoverable through this hook. Interrupted
turns remain in the raw archive but are not presented as completed turn traces.
The raw archive contains everything Codex persisted, which can include sensitive
prompt and tool content; it is not a reconstruction of unrecorded model context.
An exporter crash between successful remote persistence and writing the local
checkpoint can result in a duplicate turn on replay. Deleting checkpoints also
allows re-export; they are not a server-side exactly-once guarantee.

The existing `traces enrichment` commands configure Claude hooks. Codex currently
records model and token metadata directly and does not apply Claude-specific
enrichment settings.

See [Codex configuration](https://developers.openai.com/codex/config-reference/)
and [MLflow's Codex integration](https://mlflow.org/docs/latest/genai/tracing/integrations/listing/codex/)
for the underlying notify/rollout model.

## Enrichments

Enrichments add extra metadata to your traces. They are optional and can be enabled per-project. Multiple enrichments can be active simultaneously.

### Available Enrichments

| Name | Description |
|------|-------------|
| `git` | Adds git repository context: commit ID, branch, remote URL, repo name |
| `files` | Adds list of files modified (written/edited) during the session |
| `tokens` | Adds token usage statistics including cache metrics |
| `model` | Adds the Claude model(s) that served the session |

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

### Model Enrichment

See which Claude model(s) served the session:

- `model` - Comma-separated distinct models seen in the transcript
- `model.primary` - Model with the most assistant messages

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

Enrichment configuration is stored locally per-user in `.claude/settings.json`. If teammates configure different enrichments, their traces will have different tags. See [ADR-001](docs/adr/001-enrichment-consistency.md) for the design rationale.

### What happens when I join an existing experiment?

During `traces init`, we check existing traces for enrichment patterns. If enrichments are detected, you'll see:

```
Enrichment mismatch detected
Existing traces use: files, git, tokens

Options:
  [1] Match existing enrichments (recommended)
  [2] Continue without enrichments
  [3] Cancel setup
```

Choosing option 1 automatically enables the matching enrichments.

### Why warn instead of auto-configuring enrichments?

We chose advisory warnings over enforcement because:
- Teams may intentionally use different enrichments for different use cases
- Some users may not have all enrichments available (e.g., no git repo)
- Respecting user autonomy while surfacing potential issues

## License

MIT

---

Built with [Claude Opus 4.5](https://www.anthropic.com/claude)
