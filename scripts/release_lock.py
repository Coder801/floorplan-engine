"""Version in web/ and admin/ package-lock.json and in uv.lock at release time (pre_bump_hooks
in pyproject.toml, [tool.commitizen]): commitizen edits only the version files, while a lock file
has a "version" line for every package, so a pattern replace is not safe. In package-lock.json
only the two root entries are changed (the top one and packages[""]), and the file is written the
way npm writes it (indent 2, trailing newline); in uv.lock only the line of our own package. The
files are staged: cz bump commits the index together with the version files.

The new version comes from the CZ_PRE_NEW_VERSION variable (set by commitizen); for a manual
check pass it as an argument: `uv run python scripts/release_lock.py 0.2.0 --no-add`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCKS = (ROOT / "web" / "package-lock.json", ROOT / "admin" / "package-lock.json")
UV_LOCK = ROOT / "uv.lock"
UV_PACKAGE = re.compile(r'(name = "floorplan-engine"\nversion = ")[^"]+(")')


def set_version(lock: Path, version: str) -> None:
    data = json.loads(lock.read_text(encoding="utf-8"))
    data["version"] = version
    data["packages"][""]["version"] = version
    lock.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def set_uv_version(lock: Path, version: str) -> None:
    text, found = UV_PACKAGE.subn(rf"\g<1>{version}\g<2>", lock.read_text(encoding="utf-8"))
    if found != 1:
        raise SystemExit(f"release_lock: floorplan-engine в {lock.name} не найден")
    lock.write_text(text, encoding="utf-8")


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    version = args[0] if args else os.environ.get("CZ_PRE_NEW_VERSION")
    if not version:
        print("release_lock: нет версии — CZ_PRE_NEW_VERSION или аргумент", file=sys.stderr)
        return 2
    for lock in LOCKS:
        set_version(lock, version)
    set_uv_version(UV_LOCK, version)
    for lock in (*LOCKS, UV_LOCK):
        if "--no-add" not in argv:
            subprocess.run(["git", "add", str(lock)], check=True)
        print(f"release_lock: {lock.relative_to(ROOT)} → {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
