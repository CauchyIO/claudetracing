# Changelog

What each claudetracing release changed, newest first. The pull request that bumps the version in `pyproject.toml` (`uv version --bump patch|minor|major`) adds its section here. When the bump lands on `master`, CI publishes the package to PyPI and creates the GitHub release with that section as its body.

## v0.6.0

- Support Claude Code, Codex, GitHub Copilot (`copilot`), and Antigravity (`agy`) via `traces init --agent [all|both|claude|codex|copilot|agy]`.
- Support local (`http://localhost:5000`) and self-hosted (`--tracking-uri` + `--token`) MLflow servers in addition to Databricks profiles (`--profile`) and service principals (`--spn`).
- Switch Claude Code setup to MLflow 3.14's `mlflow-tracing@mlflow-plugins` plugin and native `"env"` block in `.claude/settings.json`, removing the old Python Stop hook and custom git/token/model enrichment wrappers.
- Switch Codex setup to `@mlflow/codex` (`mlflow-codex notify-hook`) via `.codex/config.toml` and `.codex/mlflow-tracing.json`, replacing `traces codex replay` from v0.5.0.
- Add `traces copilot-hook` and `traces agy-hook` to convert Copilot and Antigravity session transcripts into MLflow traces.
- Release on merge: pushing a new version in `pyproject.toml` to `master` publishes to PyPI, tags `v<version>`, and creates the GitHub release from `CHANGELOG.md`.

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
