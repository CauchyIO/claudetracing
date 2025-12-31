"""Custom hook handlers with enrichment support for Claude Code tracing."""

import json
import os
import sys


def enriched_stop_hook_handler() -> None:
    """Stop hook handler that creates trace and applies enrichments as trace tags.

    Reads CLAUDETRACING_ENRICHMENTS env var to determine which enrichments to apply.
    Uses MlflowClient.set_trace_tag() to attach tags to the specific trace.
    """
    import mlflow
    from mlflow.claude_code.tracing import (
        get_hook_response,
        get_logger,
        is_tracing_enabled,
        process_transcript,
        setup_mlflow,
    )

    logger = get_logger()

    if not is_tracing_enabled():
        print(json.dumps(get_hook_response()))
        return

    try:
        # Read hook input from stdin
        input_data = sys.stdin.read()
        hook_data = json.loads(input_data) if input_data else {}
        session_id = hook_data.get("session_id")
        transcript_path = hook_data.get("transcript_path")

        setup_mlflow()

        if not transcript_path:
            print(json.dumps(get_hook_response(error="No transcript_path provided")))
            return

        # Create the trace
        trace = process_transcript(transcript_path, session_id)

        if trace is not None:
            request_id = trace.info.request_id

            # Collect all enrichment data
            enrichments = {}

            # Get active enrichments from environment or settings.json
            enrichments_str = os.environ.get("CLAUDETRACING_ENRICHMENTS", "")
            if not enrichments_str:
                # Fallback: read from settings.json since env vars may not be passed to hook
                enrichments_str = _get_enrichments_from_settings()
            active_enrichments = [
                e.strip() for e in enrichments_str.split(",") if e.strip()
            ]
            logger.debug(
                "Enrichments: %r, active: %s", enrichments_str, active_enrichments
            )

            for name in active_enrichments:
                if name == "git":
                    enrichments.update(_get_git_attributes(logger))
                elif name == "files" and transcript_path:
                    enrichments.update(_get_files_attributes(transcript_path, logger))
                elif name == "tokens" and transcript_path:
                    enrichments.update(_get_tokens_attributes(transcript_path, logger))

            # Set enrichments as trace tags (the only post-creation option in MLflow)
            if enrichments:
                from mlflow.tracking import MlflowClient

                client = MlflowClient()
                logger.info("Setting trace tags: %s", list(enrichments.keys()))
                for key, value in enrichments.items():
                    client.set_trace_tag(request_id, key, value)

            print(json.dumps(get_hook_response()))
        else:
            print(
                json.dumps(
                    get_hook_response(
                        error="Failed to process transcript, check .claude/mlflow/claude_tracing.log"
                    )
                )
            )

    except Exception as e:
        from mlflow.claude_code.tracing import get_hook_response, get_logger

        get_logger().error("Error in enriched Stop hook: %s", e, exc_info=True)
        print(json.dumps(get_hook_response(error=str(e))))
        sys.exit(1)


def _get_enrichments_from_settings() -> str:
    """Read CLAUDETRACING_ENRICHMENTS from .claude/settings.json."""
    from pathlib import Path
    import json as json_module

    settings_path = Path.cwd() / ".claude" / "settings.json"
    if settings_path.exists():
        try:
            settings = json_module.loads(settings_path.read_text())
            return settings.get("environment", {}).get("CLAUDETRACING_ENRICHMENTS", "")
        except Exception:
            pass
    return ""


def _get_git_attributes(logger) -> dict[str, str]:
    """Get git metadata as span attributes."""
    from claudetracing.git_enrichment import get_git_metadata

    git_meta = get_git_metadata()
    logger.debug("Git enrichment: %s", git_meta)
    return git_meta


def _get_files_attributes(transcript_path: str, logger) -> dict[str, str]:
    """Get modified files list as span attribute."""
    try:
        modified_files = _extract_modified_files(transcript_path)
        logger.debug("Files enrichment: %s files", len(modified_files))
        if modified_files:
            return {"files.modified": json.dumps(sorted(modified_files))}
    except Exception as e:
        logger.error("Failed to get files enrichment: %s", e)
    return {}


def _get_tokens_attributes(transcript_path: str, logger) -> dict[str, str]:
    """Get token usage statistics as span attributes."""
    try:
        usage = _extract_token_usage(transcript_path)
        logger.debug("Tokens enrichment: %s", usage)
        return {k: str(v) for k, v in usage.items() if v > 0}
    except Exception as e:
        logger.error("Failed to get tokens enrichment: %s", e)
    return {}


def _extract_modified_files(transcript_path: str) -> set[str]:
    """Extract file paths from Write and Edit tool calls in transcript."""
    modified = set()

    try:
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)
                msg = entry.get("message", {})
                content = msg.get("content", [])

                if not isinstance(content, list):
                    continue

                for block in content:
                    if block.get("type") != "tool_use":
                        continue

                    tool_name = block.get("name", "")
                    # Only include Write and Edit (modified files)
                    if tool_name not in ("Write", "Edit"):
                        continue

                    inputs = block.get("input", {})
                    file_path = inputs.get("file_path")
                    if file_path:
                        modified.add(file_path)
    except Exception:
        pass

    return modified


def _extract_token_usage(transcript_path: str) -> dict[str, int]:
    """Extract token usage from transcript entries."""
    totals = {
        "tokens.input": 0,
        "tokens.output": 0,
        "tokens.cache_read": 0,
        "tokens.cache_creation": 0,
        "tokens.total": 0,
    }

    try:
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)

                # Token usage might be in different locations depending on format
                usage = entry.get("usage", {})
                if not usage:
                    # Try nested in message
                    usage = entry.get("message", {}).get("usage", {})

                totals["tokens.input"] += usage.get("input_tokens", 0)
                totals["tokens.output"] += usage.get("output_tokens", 0)
                totals["tokens.cache_read"] += usage.get("cache_read_input_tokens", 0)
                totals["tokens.cache_creation"] += usage.get(
                    "cache_creation_input_tokens", 0
                )
    except Exception:
        pass

    totals["tokens.total"] = totals["tokens.input"] + totals["tokens.output"]
    return totals
