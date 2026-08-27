import io
import zipfile

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


def _fake_ems_zip(**named_geojsons) -> bytes:
    """Builds a real in-memory ZIP shaped like a delivered EMS product -- {suffix: geojson} becomes
    a file named like EMS's own convention (..._<suffix>_v1.json), plus a couple of irrelevant
    files (.shp/.dbf/.pdf) real deliveries always include, to make sure those get ignored."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for suffix, geojson in named_geojsons.items():
            zf.writestr(f"EMSR927_AOI02_GRA_PRODUCT_{suffix}_v1.json", __import__("json").dumps(geojson))
        zf.writestr("EMSR927_AOI02_GRA_PRODUCT_v1.gpkg", b"not-actually-a-geopackage")
        zf.writestr("Maps/EMSR927_AOI02_GRA_PRODUCT_map_v1.pdf", b"not-actually-a-pdf")
    return buf.getvalue()


def test_download_zip_geojson_layers_extracts_only_known_suffixes(monkeypatch):
    built_up = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [85.1, 28.1]}, "properties": {"damage_gra": "Destroyed"}}]}
    zip_bytes = _fake_ems_zip(builtUpP=built_up)

    class FakeResponse:
        content = zip_bytes

        def raise_for_status(self):
            pass

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())

    layers = ems._download_zip_geojson_layers("https://example.test/product.zip")

    assert set(layers.keys()) == {"builtUpP"}
    assert layers["builtUpP"]["features"][0]["properties"]["damage_gra"] == "Destroyed"


def test_download_zip_geojson_layers_returns_empty_on_network_failure(monkeypatch):
    def raise_connection_error(*args, **kwargs):
        raise requests.ConnectionError("no network")

    monkeypatch.setattr(requests, "get", raise_connection_error)
    assert ems._download_zip_geojson_layers("https://example.test/product.zip") == {}


def test_download_zip_geojson_layers_returns_empty_on_bad_zip(monkeypatch):
    class FakeResponse:
        content = b"not a zip file at all"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())
    assert ems._download_zip_geojson_layers("https://example.test/product.zip") == {}


def test_merge_damage_layers_tags_features_with_aoi_and_layer(monkeypatch):
    built_up = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [85.1, 28.1]}, "properties": {"damage_gra": "Destroyed"}}]}
    monkeypatch.setattr(ems, "_download_zip_geojson_layers", lambda url: {"builtUpP": built_up})

    merged = ems.merge_damage_layers([
        {"aoi_name": "Timure", "download_path": "https://example.test/timure.zip"},
        {"aoi_name": "Bidur", "download_path": None},  # not yet delivered -- must be skipped
    ])

    assert len(merged["features"]) == 1
    props = merged["features"][0]["properties"]
    assert props["aoi_name"] == "Timure"
    assert props["ems_layer"] == "builtUpP"
    assert props["damage_gra"] == "Destroyed"
    assert merged["aois_included"] == ["Timure"]


def test_merge_damage_layers_skips_null_geometry_features(monkeypatch):
    # a handful of real EMS features are attribute-only records with no mapped geometry
    layer_with_null_geom = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": None, "properties": {"damage_gra": "No visible damage"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [85.1, 28.1]}, "properties": {"damage_gra": "Destroyed"}},
    ]}
    monkeypatch.setattr(ems, "_download_zip_geojson_layers", lambda url: {"transportationL": layer_with_null_geom})

    merged = ems.merge_damage_layers([{"aoi_name": "Timure", "download_path": "https://example.test/timure.zip"}])

    assert len(merged["features"]) == 1
    assert merged["features"][0]["properties"]["damage_gra"] == "Destroyed"


def test_merge_damage_layers_handles_no_delivered_products(monkeypatch):
    merged = ems.merge_damage_layers([{"aoi_name": "Bidur", "download_path": None}])
    assert merged == {"type": "FeatureCollection", "features": [], "aois_included": []}
