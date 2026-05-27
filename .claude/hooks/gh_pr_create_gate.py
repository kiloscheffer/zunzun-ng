#!/usr/bin/env python3
# PreToolUse hook: gate `gh pr create` on a code-review-passed marker.
#
# Denies any Bash command starting with "gh pr create" unless the marker
# file <git-common-dir>/.code-review-passed-<HEAD-SHA> exists. The marker
# is tied to the current HEAD; any new commit invalidates it.
#
# To satisfy the gate:
#   1. Run a code review (e.g. /code-review or /code-review:code-review)
#      against the diff vs origin/main.
#   2. Address any Critical findings.
#   3. touch "$(git rev-parse --git-common-dir)/.code-review-passed-$(git rev-parse HEAD)"
#   4. Retry `gh pr create`.
#
# Uses --git-common-dir (not --git-dir) so the marker lives in the shared
# gitdir and is reachable from any worktree at the same SHA. Marker files
# are written under .git/, which is gitignored — no cleanup needed.
#
# Adapted from the dbxignore project's .claude/settings.json hook.

import json
import os
import subprocess
import sys


def main():
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    command = event.get("tool_input", {}).get("command", "")
    if not command.startswith("gh pr create"):
        sys.exit(0)

    try:
        head_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        git_common_dir = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        sys.exit(0)  # not in a git repo; let it through

    marker = os.path.normpath(
        os.path.join(git_common_dir, ".code-review-passed-" + head_sha)
    )
    if os.path.isfile(marker):
        sys.exit(0)

    sys.stderr.write(
        "Refusing `gh pr create`: this branch has not passed a code review "
        "at HEAD {short}.\n\n"
        "Run a code review against the diff vs origin/main (e.g. "
        "/code-review or /code-review:code-review), address any Critical "
        "findings, then:\n"
        '    touch "{marker}"\n\n'
        "Marker is tied to current HEAD SHA; new commits invalidate it. "
        "After touching the marker, retry `gh pr create`.\n".format(
            short=head_sha[:12],
            marker=marker,
        )
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
