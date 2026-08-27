import json

import pytest

from fflood_nep import timeline


def test_add_entry_creates_file_with_one_entry(tmp_path):
    path = tmp_path / "timeline.json"
    entry = timeline.add_entry(
        path,
        date="2026-08-27T12:00:00Z",
        category="imagery",
        headline="Test entry",
        body="Body text",
        sources=[{"label": "Src", "url": "https://example.test"}],
    )

    assert entry["headline"] == "Test entry"
    assert "logged_at" in entry

    payload = json.loads(path.read_text())
    assert len(payload["entries"]) == 1
    assert payload["entries"][0]["headline"] == "Test entry"


def test_add_entry_prepends_and_sorts_newest_first(tmp_path):
    path = tmp_path / "timeline.json"
    timeline.add_entry(
        path, date="2026-08-26T09:00:00Z", category="activation", headline="Older",
        body="...", sources=[{"label": "A", "url": "https://a.test"}],
    )
    timeline.add_entry(
        path, date="2026-08-27T09:00:00Z", category="cause", headline="Newer",
        body="...", sources=[{"label": "B", "url": "https://b.test"}],
    )

    payload = json.loads(path.read_text())
    assert [e["headline"] for e in payload["entries"]] == ["Newer", "Older"]


def test_add_entry_rejects_unknown_category(tmp_path):
    with pytest.raises(ValueError):
        timeline.add_entry(
            tmp_path / "timeline.json", date="2026-08-27T09:00:00Z", category="nonsense",
            headline="X", body="...", sources=[{"label": "A", "url": "https://a.test"}],
        )


def test_add_entry_rejects_source_without_url(tmp_path):
    with pytest.raises(ValueError):
        timeline.add_entry(
            tmp_path / "timeline.json", date="2026-08-27T09:00:00Z", category="cause",
            headline="X", body="...", sources=[{"label": "A"}],
        )


def test_add_entry_rejects_empty_sources(tmp_path):
    with pytest.raises(ValueError):
        timeline.add_entry(
            tmp_path / "timeline.json", date="2026-08-27T09:00:00Z", category="cause",
            headline="X", body="...", sources=[],
        )
