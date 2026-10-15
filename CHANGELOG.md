# Changelog

What each claudetracing release changed, newest first. The pull request that
bumps the version in `pyproject.toml` (`uv version --bump patch|minor|major`)
adds its section here and reviewers trim it in that same PR. When the bump
lands on `master`, CI publishes the package to PyPI and creates the GitHub
release with this section as its body. Releases before v0.6.0 were tagged by
hand (v0.5.0 on master was superseded by v0.6.0); their entries below were
backfilled from the merged pull requests.

## v0.6.0

- **Unified 4-agent tracing setup (`traces init --agent [all|both|claude|codex|copilot|agy]`)**: Configure **Claude Code**, **OpenAI Codex CLI**, **GitHub Copilot** (`copilot` CLI / VS Code Copilot), and **Google Antigravity** (`agy` CLI / IDE) in a single command against the same MLflow experiment.
- **Databricks, Self-Hosted MLflow, and Local MLflow backends**: Support `--tracking-uri` (`http://` / `https://`) with optional `--token` (`MLFLOW_TRACKING_TOKEN`), alongside Databricks OAuth profiles (`--profile`) and headless service principals (`--spn`).
- **Official MLflow 3.14+ convention alignment**:
  - **Claude Code (`@mlflow/claude-code`)**: Installs and activates `mlflow-tracing@mlflow-plugins` (`enabledPlugins`) and writes Claude Code's native `"env"` block in `.claude/settings.json` (with machine-local profile/token overrides in gitignored `.claude/settings.local.json`). Removes the legacy Python Stop hook and custom git/token/model enrichment wrappers now handled natively by MLflow.
  - **OpenAI Codex CLI (`@mlflow/codex`)**: Writes `notify = ["mlflow-codex", "notify-hook"]` to `.codex/config.toml` and `trackingUri` / `experimentId` to `.codex/mlflow-tracing.json`, syncs `$CODEX_HOME/config.toml` (including chaining into Codex Desktop's `SkyComputerUseClient --previous-notify`), and injects `DATABRICKS_CONFIG_PROFILE` before delegating to `mlflow-codex notify-hook`. The custom `traces codex replay` command and `claudetracing.codex_transcript` parser shipped in v0.5.0 were retired in favor of this official `@mlflow/codex` (`mlflow-codex notify-hook`) integration.
  - **GitHub Copilot (`traces copilot init` / `traces copilot-hook`)**: Configures `.github/hooks/mlflow-tracing.json` (and gitignored `.local.json`) and converts Copilot JSONL transcripts for `mlflow.claude_code.tracing.process_transcript()`.
  - **Google Antigravity (`traces agy init` / `traces agy-hook`)**: Configures `.agents/hooks.json` and gitignored `.agents/mlflow-tracing.json` and converts Antigravity `transcript.jsonl` / `transcript_full.jsonl` trajectories (including tool spans and token usage) for `mlflow.claude_code.tracing.process_transcript()`.
- **Automated release-on-merge pipeline**: Merging a version bump to `master` automatically builds, publishes to PyPI, tags `v<version>`, and creates the GitHub Release from `CHANGELOG.md`.

## v0.5.0

- Native Codex conversation tracing: `traces codex init` registers tracing per project and `traces codex replay` backfills completed turns into session-grouped MLflow traces with tool calls, timings, model tags and token deltas. The full rollout is archived with a checksum (`--no-archive` opts out). (#5)

## v0.4.0

- `model` enrichment: traces carry `model` and `model.primary` tags recording the serving model(s) of the session. (#4)

## v0.3.0

- Databricks auth resolved from the environment: the Stop hook loads the project's `environment` block (`settings.json`, then `settings.local.json`; existing environment wins) before any MLflow call, so a bare `databricks` tracking URI works on a laptop with the profile in `.local` and headless with a service principal. (#3)
- `traces init --spn` for headless service-principal setup. (#3)

## v0.2.0

- Trace enrichment system: `git`, `files` and `tokens` enrichments attached as trace tags, configured per project through `CLAUDETRACING_ENRICHMENTS`. (#2)

## v0.1.3

- Fix the CLI hanging on start by removing eager MLflow imports from the package init.
- Tag-based PyPI release workflow. (#1)

## v0.1.0

- Initial release: the `traces` CLI wires the MLflow Claude Code Stop hook into a project against a Databricks workspace.
