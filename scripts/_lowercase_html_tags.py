"""One-shot helper: lowercase HTML tag names + attribute names + values.

Targets:
  - Opening tags like `<TABLE>` / `<TABLE align="CENTER">` -> `<table>` / `<table align="center">`
  - Closing tags like `</TABLE>` -> `</table>`
  - Attribute names like `ALIGN=`, `ID=`, `BORDER=` -> `align=`, `id=`, `border=`
  - Boolean attributes like `SELECTED` -> `selected`
  - Presentation-keyword *values* like `align="CENTER"` -> `align="center"`,
    using a whitelist of safe-to-lowercase values (CENTER, LEFT, RIGHT,
    JUSTIFY, TOP, BOTTOM, MIDDLE, SUBMIT, BUTTON, RESET, POST, GET).
    Identifier values like `id="FUNCTION"` are NOT lowercased because
    JavaScript references them case-sensitively.

Run with: uv run python scripts/_lowercase_html_tags.py

Preserved at scripts/_lowercase_html_tags.py for auditability — the
leading underscore marks this as a one-shot maintenance helper.
"""

import re
from pathlib import Path

# Match opening tag: < followed by one or more uppercase letters, followed
# by space, >, or / (the boundary character). Capture the tag name and
# the boundary so we can preserve the boundary character verbatim.
_OPEN_TAG_RE = re.compile(r"<([A-Z][A-Z0-9]*)(\s|>|/)")

# Match closing tag: </ followed by one or more uppercase letters, then >.
_CLOSE_TAG_RE = re.compile(r"</([A-Z][A-Z0-9]*)>")

# Match attribute names: whitespace, uppercase letters/digits/underscores,
# equals sign. Capture the leading space, the name, and preserve the =.
_ATTR_NAME_RE = re.compile(r"(\s)([A-Z][A-Z0-9_]*)=")

# Match boolean-style attributes (no value). Restricted to a known list
# to avoid accidentally matching unrelated uppercase tokens.
_BOOLEAN_ATTRS = (
    "SELECTED",
    "CHECKED",
    "DISABLED",
    "READONLY",
    "REQUIRED",
    "MULTIPLE",
    "AUTOFOCUS",
    "HIDDEN",
    "NOSHADE",
)
_BOOLEAN_ATTR_RE = re.compile(rf"(\s)({'|'.join(_BOOLEAN_ATTRS)})(\s|/?>)")

# Whitelisted presentation-keyword values that are safe to lowercase
# (HTML5 treats these as case-insensitive). Identifiers and URLs are
# NOT in this list — those need to stay as-is to preserve JavaScript
# / CSS selector resolution.
_VALUE_WHITELIST = (
    "CENTER",
    "LEFT",
    "RIGHT",
    "JUSTIFY",
    "TOP",
    "BOTTOM",
    "MIDDLE",
    "SUBMIT",
    "BUTTON",
    "RESET",
    "POST",
    "GET",
)
# Match double-quoted, single-quoted, or unquoted (terminated by space
# or `>`) values. Three regexes for clarity.
_VALUE_DQUOTED_RE = re.compile(rf'=("(?:{"|".join(_VALUE_WHITELIST)})")')
_VALUE_SQUOTED_RE = re.compile(rf"=('(?:{'|'.join(_VALUE_WHITELIST)})')")
_VALUE_UNQUOTED_RE = re.compile(rf"=({'|'.join(_VALUE_WHITELIST)})([>\s/])")


def lowercase_tags(content: str) -> str:
    content = _OPEN_TAG_RE.sub(lambda m: f"<{m.group(1).lower()}{m.group(2)}", content)
    content = _CLOSE_TAG_RE.sub(lambda m: f"</{m.group(1).lower()}>", content)
    content = _ATTR_NAME_RE.sub(lambda m: f"{m.group(1)}{m.group(2).lower()}=", content)
    content = _BOOLEAN_ATTR_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2).lower()}{m.group(3)}", content
    )
    content = _VALUE_DQUOTED_RE.sub(lambda m: f"={m.group(1).lower()}", content)
    content = _VALUE_SQUOTED_RE.sub(lambda m: f"={m.group(1).lower()}", content)
    content = _VALUE_UNQUOTED_RE.sub(lambda m: f"={m.group(1).lower()}{m.group(2)}", content)
    return content


def main() -> None:
    template_dir = Path("templates/zunzun")
    changed = 0
    # Process .html templates AND .js files under templates/ — the JS
    # files build HTML strings at runtime and the same lowercase
    # convention applies to those literals.
    patterns = ("*.html", "*.js")
    for pattern in patterns:
        for path in template_dir.rglob(pattern):
            original = path.read_text(encoding="utf-8")
            new = lowercase_tags(original)
            if new != original:
                path.write_text(new, encoding="utf-8")
                changed += 1
                print(f"Updated: {path}")
    print(f"\nTotal files changed: {changed}")


if __name__ == "__main__":
    main()
