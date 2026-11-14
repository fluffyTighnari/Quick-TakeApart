"""Small, app-level recent-project list.

This is intentionally outside any project's `.qta/` directory: the entry screen
needs it before a project has been opened. It is only a convenience; a corrupt
or missing file is ignored rather than blocking startup.
"""

from __future__ import annotations

import json
import pathlib

RECENT_FILE = pathlib.Path.home() / ".quick-takeapart" / "recent.json"
MAX_RECENT = 10


def load_recent() -> list[str]:
    try:
        raw = json.loads(RECENT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get("recent") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for item in items:
        if isinstance(item, str) and item and item not in out:
            out.append(item)
    return out[:MAX_RECENT]


def remember(root: str) -> list[str]:
    items = [root] + [item for item in load_recent() if item != root]
    items = items[:MAX_RECENT]
    try:
        RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = RECENT_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"recent": items}, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(RECENT_FILE)
    except OSError:
        pass
    return items
