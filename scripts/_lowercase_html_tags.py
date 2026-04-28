"""One-shot helper: lowercase HTML tag names across templates/zunzun/.

Targets opening tags like `<TABLE>` / `<TABLE ALIGN="CENTER">` and closing
tags like `</TABLE>`. Leaves attribute names (ALIGN, BORDER, etc.)
unchanged — those are case-insensitive in HTML5 but lowercasing them is
a separate concern.

Run with: uv run python scripts/_lowercase_html_tags.py

Removed after the lowercase commit lands (this is a one-shot helper).
"""
import re
from pathlib import Path

# Match opening tag: < followed by one or more uppercase letters, followed
# by space, >, or / (the boundary character). Capture the tag name and
# the boundary so we can preserve the boundary character verbatim.
_OPEN_TAG_RE = re.compile(r"<([A-Z][A-Z0-9]*)(\s|>|/)")

# Match closing tag: </ followed by one or more uppercase letters, then >.
_CLOSE_TAG_RE = re.compile(r"</([A-Z][A-Z0-9]*)>")


def lowercase_tags(content: str) -> str:
    content = _OPEN_TAG_RE.sub(
        lambda m: f"<{m.group(1).lower()}{m.group(2)}", content
    )
    content = _CLOSE_TAG_RE.sub(
        lambda m: f"</{m.group(1).lower()}>", content
    )
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
