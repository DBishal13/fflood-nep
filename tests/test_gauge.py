import requests

from fflood_nep import gauge


def test_fetch_gauge_status_returns_none_on_network_failure(monkeypatch):
    def raise_connection_error(*args, **kwargs):
        raise requests.ConnectionError("no network")

    monkeypatch.setattr(requests, "get", raise_connection_error)
    assert gauge.fetch_gauge_status() is None


def test_fetch_gauge_status_returns_none_on_bad_json(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())
    assert gauge.fetch_gauge_status() is None


def test_fetch_gauge_status_returns_parsed_bulletin(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"updated_at": "2026-08-26T15:47:36+00:00", "stations": [{"name": "Test Station"}]}

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())
    bulletin = gauge.fetch_gauge_status()
    assert bulletin["stations"][0]["name"] == "Test Station"
