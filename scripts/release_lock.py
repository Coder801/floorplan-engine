"""Version in web/package-lock.json at release time (pre_bump_hooks in pyproject.toml,
[tool.commitizen]): commitizen edits only the version files, while the lock file has a
"version" line for every package, so a pattern replace is not safe. Only the two root entries
are changed here (the top one and packages[""]); the file is written the way npm writes it
(indent 2, trailing newline) and staged: cz bump commits the index together with the version files.

The new version comes from the CZ_PRE_NEW_VERSION variable (set by commitizen); for a manual
check pass it as an argument: `uv run python scripts/release_lock.py 0.2.0 --no-add`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

LOCK = Path(__file__).resolve().parents[1] / "web" / "package-lock.json"


def set_version(lock: Path, version: str) -> None:
    data = json.loads(lock.read_text(encoding="utf-8"))
    data["version"] = version
    data["packages"][""]["version"] = version
    lock.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    version = args[0] if args else os.environ.get("CZ_PRE_NEW_VERSION")
    if not version:
        print("release_lock: нет версии — CZ_PRE_NEW_VERSION или аргумент", file=sys.stderr)
        return 2
    set_version(LOCK, version)
    if "--no-add" not in argv:
        subprocess.run(["git", "add", str(LOCK)], check=True)
    print(f"release_lock: {LOCK.name} → {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
