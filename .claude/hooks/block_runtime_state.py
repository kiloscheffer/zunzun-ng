#!/usr/bin/env python3
# PreToolUse hook: refuse Edit/Write against live runtime state.
# session_db/db.sqlite3 holds live session cookies; temp/ is scratch
# output (PDFs, graphs, animations from spawn-fit children), auto-trimmed
# when it exceeds 500 MB. Hand-editing either corrupts a running server.
# Committed static assets live at static/ (project root, separate from
# temp/) since the static-files restructure on 2026-04-28.

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
