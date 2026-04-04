"""Inject Copilot session ID into agent context via SessionStart hook."""

import json
import sys


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"session_start: invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    session_id = data.get("session_id", "unknown")

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": (
                        f"Copilot session ID: {session_id}. "
                        "When updating ADO work items for this task, include "
                        f"'Copilot Session: {session_id}' in comments."
                    ),
                }
            }
        )
    )


if __name__ == "__main__":
    main()
