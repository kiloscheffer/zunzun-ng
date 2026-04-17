#!/usr/bin/env python3
# PostToolUse hook: py_compile every edited .py file.
# The project has no linter/formatter/CI, so this is the cheapest way
# to catch syntax errors before they reach the dev server.

import json
import py_compile
import sys


def main():
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    file_path = event.get("tool_input", {}).get("file_path", "")
    if not file_path.endswith(".py"):
        sys.exit(0)

    try:
        py_compile.compile(file_path, doraise=True)
    except py_compile.PyCompileError as e:
        sys.stderr.write("Syntax error in {0}:\n{1}\n".format(file_path, e.msg))
        sys.exit(2)
    except FileNotFoundError:
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
