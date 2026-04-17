#!/usr/bin/env python3
# PreToolUse hook: refuse Edit/Write against live runtime state.
# session_db/db.sqlite3 holds live session cookies; temp/ is scratch output
# (also served as STATIC_URL) and is auto-trimmed when it exceeds 500 MB.
# Hand-editing either corrupts a running server.

import json
import sys


def main():
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    file_path = event.get("tool_input", {}).get("file_path", "")
    if not file_path:
        sys.exit(0)

    norm = file_path.replace("\\", "/")
    blocked = (
        norm.endswith("session_db/db.sqlite3")
        or "/session_db/" in norm
        or "/temp/" in norm
        or norm.endswith("/temp")
    )
    if blocked:
        sys.stderr.write(
            "Refusing Edit/Write on {0}: runtime state (live session DB or "
            "auto-cleaned scratch dir). If this is intentional, bypass by "
            "disabling the hook in .claude/settings.json.\n".format(file_path)
        )
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
