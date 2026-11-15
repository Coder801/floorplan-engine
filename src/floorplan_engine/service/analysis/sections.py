"""One top-level section of a YAML file replaced as text (decision 2026-11-15, the targeted
analysis `--stages floor_heating`): the rest of the file — other sections, their comments, the
field order — stays byte for byte.

The section is the lines from `key:` at the start of a line to the next line that starts with
something other than a space, `#` or a `- ` list item (the next top-level key; PyYAML writes the
items of a list value at column 0). The result is checked: parsed, it
must be the old data with only this key changed; otherwise None and the caller does not write.
"""

from __future__ import annotations

import re
from typing import Any

import yaml


def _load(text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return None


def section_value(section: str, key: str) -> tuple[bool, Any]:
    """The value of key in a YAML text that holds only this section; (False, None) if the text
    is not such a mapping."""
    data = _load(section)
    if not isinstance(data, dict) or set(data) != {key}:
        return False, None
    return True, data[key]


def _next_key(line: str) -> bool:
    """The line starts the next top-level key: not blank, not indented, not a comment and not a
    list item at column 0 (PyYAML writes the items of a mapping value there by default)."""
    return bool(line) and line[0] not in " #" and re.match(r"-(\s|$)", line) is None


def replace_section(text: str, key: str, section: str) -> str | None:
    """text with its top-level `key` section replaced by section (YAML text of `key: …`, comments
    allowed); the section is appended when the file has none. None when the file or the section
    is not a mapping or the result does not parse into exactly that change."""
    ok, value = section_value(section, key)
    old = _load(text) if text.strip() else {}
    if not ok or not isinstance(old, dict):
        return None
    lines = text.splitlines()
    head = next((k for k, s in enumerate(lines) if re.match(rf"{re.escape(key)}\s*:", s)), None)
    new = section.strip("\n").splitlines()
    if head is None:
        body = "\n".join(lines).rstrip("\n")
        result = f"{body}\n\n" if body else ""
        result += "\n".join(new) + "\n"
    else:
        end = next((k for k in range(head + 1, len(lines)) if _next_key(lines[k])), len(lines))
        # Comment lines and blank lines just before the next key belong to it
        while end > head + 1 and (not lines[end - 1].strip() or lines[end - 1].startswith("#")):
            end -= 1
        result = "\n".join([*lines[:head], *new, *lines[end:]]) + "\n"
    expected = {**old, key: value}
    return result if _load(result) == expected else None
