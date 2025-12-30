# Claude Code MLflow Tracing

[![PyPI version](https://img.shields.io/pypi/v/claudetracing.svg)](https://pypi.org/project/claudetracing/)
[![Python versions](https://img.shields.io/pypi/pyversions/claudetracing.svg)](https://pypi.org/project/claudetracing/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

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

## Python API

```python
from claudetracing import TracingClient

client = TracingClient()

# List experiments
experiments = client.list_experiments()

# Search traces
traces = client.search_traces(experiment_name="my-experiment", max_results=10)

# Search by time
traces = client.search_traces_by_time(hours=24)

# Get specific trace
trace = client.get_trace("trace-id")

# Access trace data
for trace in traces:
    print(f"Session: {trace.info.trace_id}")
    print(f"Tools used: {trace.get_tool_calls()}")
    for span in trace.spans:
        print(f"  {span.name}: {span.execution_time_ms}ms")
```

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

## License

MIT

---

Built with [Claude Opus 4.5](https://www.anthropic.com/claude)
