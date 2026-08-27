"""Append-only research log for the event, surfaced as a public timeline on the web UI.

Unlike ems.py (a pure API poll), a new entry here isn't discovered by hitting a REST endpoint --
it's drafted by hand, usually by a scheduled Claude session check-in that re-checks known sources
(EMS, Planet, DHM) and searches for fresh reporting on the event. add_entry() exists so every
entry that gets appended has a consistent, validated shape, not so the research itself is
automated.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

CATEGORIES = {"casualty", "cause", "imagery", "activation", "recovery", "gauge", "other"}


def add_entry(
    path: Path,
    *,
    date: str,
    category: str,
    headline: str,
    body: str,
    sources: list[dict],
) -> dict:
    """Prepend a new dated entry to the timeline at `path` (created if missing), keeping the file
    sorted newest-first by `date`. `sources` is a list of {"label": ..., "url": ...} dicts -- every
    entry needs at least one, so a claim on the public timeline is always traceable.

    Raises ValueError on an unknown category or a source missing a url, so a malformed entry fails
    loudly rather than silently corrupting the log.
    """
    if category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}; expected one of {sorted(CATEGORIES)}")
    if not sources or any(not s.get("url") for s in sources):
        raise ValueError("every entry needs at least one source with a url")

    entry = {
        "date": date,
        "category": category,
        "headline": headline,
        "body": body,
        "sources": sources,
        "logged_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    payload = {"entries": []}
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))

    payload["entries"].insert(0, entry)
    payload["entries"].sort(key=lambda e: e["date"], reverse=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return entry
