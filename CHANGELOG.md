# Changelog

What each `claudetracing` release changed, newest first. Every pull request that bumps `version` in `pyproject.toml` (`uv version --bump patch|minor|major`) adds a `## v<version>` section here; when merged to `master`, CI publishes to PyPI and creates the GitHub Release using that section as the release notes.

## v0.6.0

- **Unified 4-agent setup (`traces init`)**: Configure **Claude Code**, **OpenAI Codex**, **GitHub Copilot** (CLI & VS Code), and **Google Antigravity (`agy`)** in a single command against the same MLflow experiment (`--agent [all|both|claude|codex|copilot|agy]`).
- **Any MLflow backend**: Support local (`http://localhost:5000`) and self-hosted (`http://` / `https://` + `--token`) MLflow servers alongside Databricks OAuth profiles (`--profile`) and headless service principals (`--spn`).
- **Aligned with MLflow 3.14+ native integrations**:
  - **Claude Code**: Uses the official `mlflow-tracing@mlflow-plugins` plugin and Claude Code's native `"env"` block in `.claude/settings.json` (storing personal profile/token overrides in gitignored `.claude/settings.local.json`). Retires the legacy Python Stop hook and custom enrichment wrappers now built into MLflow.
  - **OpenAI Codex**: Uses the official `@mlflow/codex` (`mlflow-codex notify-hook`) integration via `.codex/config.toml` and `.codex/mlflow-tracing.json` (replacing `traces codex replay` from `v0.5.0`), while staying compatible with Codex Desktop.
  - **GitHub Copilot & Google Antigravity (`agy`)**: Adds `traces copilot-hook` (`.github/hooks/mlflow-tracing.json`) and `traces agy-hook` (`.agents/hooks.json`) to stream turns, thinking blocks, tool calls, and token usage into MLflow.
- **Release on merge**: Merging a version bump to `master` automatically publishes to PyPI, tags `v<version>`, and creates the GitHub Release from `CHANGELOG.md`.

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
