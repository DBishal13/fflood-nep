import requests

from fflood_nep import ems

REAL_STYLE_ACTIVATION = {
    "code": "EMSR927",
    "name": "Flood in Nepal",
    "reason": "On the 26 August 2026, a flash flood reportedly triggered by a Glacial Lake Outburst "
    "Flood (GLOF) in Nepal has caused significant damage in Rasuwa District.",
    "category": "Flood",
    "subCategory": "Flash flood",
    "eventTime": "2026-08-25T22:00:00",
    "activationTime": "2026-08-26T09:53:00",
    "closed": False,
    "reportLink": "https://storymaps.arcgis.com/stories/f76baefadfa74d6d9a18265875f48870",
    "productsPath": "https://rapidmapping.emergency.copernicus.eu/backend/EMSR927/EMSR927_products.zip",
    "aois": [
        {
            "name": "Syapru Besi",
            "number": 1,
            "products": [
                {
                    "type": "DEL",
                    "expectedDelivery": "2026-08-27T19:30:00",
                    "downloadPath": "",
                    "images": [{"sensorName": "ICEYE"}],
                    "version": {"statusCode": "W", "deliveryTime": None},
                }
            ],
        },
        {
            "name": "Timure",
            "number": 2,
            "products": [
                {
                    "type": "DEL",
                    "expectedDelivery": "2026-08-27T19:30:00",
                    "downloadPath": "",
                    "images": [{"sensorName": "ICEYE"}],
                    "version": {"statusCode": "W", "deliveryTime": None},
                }
            ],
        },
    ],
}


def test_fetch_ems_activation_returns_none_on_network_failure(monkeypatch):
    def raise_connection_error(*args, **kwargs):
        raise requests.ConnectionError("no network")

    monkeypatch.setattr(requests, "get", raise_connection_error)
    assert ems.fetch_ems_activation() is None


def test_fetch_ems_activation_returns_none_on_bad_json(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())
    assert ems.fetch_ems_activation() is None


def test_fetch_ems_activation_returns_none_when_no_results(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"count": 0, "results": []}

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())
    assert ems.fetch_ems_activation() is None


def test_fetch_ems_activation_returns_first_result(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"count": 1, "results": [REAL_STYLE_ACTIVATION]}

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())
    activation = ems.fetch_ems_activation()
    assert activation["code"] == "EMSR927"


def test_summarize_activation_flattens_products_across_aois():
    summary = ems.summarize_activation(REAL_STYLE_ACTIVATION)

    assert summary["code"] == "EMSR927"
    assert summary["name"] == "Flood in Nepal"
    assert summary["activation_page"] == ems.EMS_ACTIVATION_PAGE
    assert len(summary["products"]) == 2
    assert summary["products"][0]["aoi_name"] == "Syapru Besi"
    assert summary["products"][0]["status"] == "W"
    assert summary["products"][0]["download_path"] is None  # empty string normalized to None
    assert summary["products"][0]["sensors"] == ["ICEYE"]
    assert summary["products"][1]["aoi_name"] == "Timure"
