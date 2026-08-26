import json
from pathlib import Path

import numpy as np
from affine import Affine
from shapely.geometry import box

from fflood_nep import detect, exposure, pc_client
from fflood_nep.config import EventConfig

CONFIG_PATH = Path(__file__).parents[1] / "config" / "rasuwa-2026-08-26.toml"


class FakeAsset:
    def __init__(self, href: str):
        self.href = href


class FakeItem:
    def __init__(self, item_id: str):
        self.id = item_id
        self.assets = {
            "rendered_preview": FakeAsset(f"https://example.test/preview.png?item={item_id}&expression=x"),
            "tilejson": FakeAsset(f"https://example.test/tilejson/{item_id}.json"),
        }


def _fake_gauge_bulletin():
    return {
        "updated_at": "2026-08-26T15:47:36+00:00",
        "note_np": "test note",
        "stations": [{"name": "Test Station", "level_m": 3.5, "warning_m": 4.1, "washed": False}],
    }


def test_run_detection_reports_waiting_when_post_event_scene_is_missing(tmp_path):
    config = EventConfig.from_toml(CONFIG_PATH)
    pre_item = FakeItem("pre-1")

    def fake_search(cfg, start, end):
        return None if start == cfg.post_start else pre_item

    output_dir = tmp_path / "out"
    report = detect.run_detection(config, output_dir, search=fake_search, fetch_gauge=_fake_gauge_bulletin)

    assert report["status"] == "waiting_for_post_event_scene"
    assert report["preview"]["pre_event"]["item"] == "pre-1"
    assert report["preview"]["post_event"] is None
    assert report["river_gauges"]["stations"][0]["name"] == "Test Station"
    written = json.loads((output_dir / "detection_report.json").read_text())
    assert written["status"] == "waiting_for_post_event_scene"
    assert not (output_dir / "flood_mask.tif").exists()


def test_run_detection_reports_no_river_gauges_when_fetch_fails(tmp_path):
    config = EventConfig.from_toml(CONFIG_PATH)

    def fake_search(cfg, start, end):
        return None

    output_dir = tmp_path / "out"
    report = detect.run_detection(config, output_dir, search=fake_search, fetch_gauge=lambda: None)

    assert report["river_gauges"] is None
    assert report["preview"] is None


def test_run_detection_writes_outputs_when_both_scenes_are_present(tmp_path, monkeypatch):
    config = EventConfig.from_toml(CONFIG_PATH)
    pre_item = FakeItem("pre-1")
    post_item = FakeItem("post-1")

    size = 20
    background = 10 ** (-5.0 / 10.0)
    flooded = 10 ** (-10.0 / 10.0)
    pre_gamma = np.full((size, size), background, dtype=np.float32)
    post_gamma = np.full((size, size), background, dtype=np.float32)
    post_gamma[5:15, 5:15] = flooded
    worldcover = np.zeros((size, size), dtype=np.uint8)
    transform = Affine(10.0, 0.0, 0.0, 0.0, -10.0, 0.0)
    crs = "EPSG:32645"

    def fake_search(cfg, start, end):
        return pre_item if start == cfg.pre_start else post_item

    def fake_read_aoi(item, asset_key, transform, width, height):
        return (pre_gamma if item is pre_item else post_gamma), transform, crs

    def fake_read_worldcover(bbox, transform, width, height):
        return worldcover, transform, crs

    monkeypatch.setattr(pc_client, "target_grid", lambda bbox: (transform, size, size))
    monkeypatch.setattr(pc_client, "read_aoi", fake_read_aoi)
    monkeypatch.setattr(pc_client, "read_worldcover", fake_read_worldcover)
    monkeypatch.setattr(detect, "_reproject_geom", lambda geom, src, dst: geom)
    monkeypatch.setattr(exposure, "load_hot_aoi", lambda data_dir: box(-10000, -10000, 10000, 10000))
    monkeypatch.setattr(exposure, "load_hot_layer", lambda name, data_dir: Path(f"unused-{name}.gpkg"))
    monkeypatch.setattr(
        exposure,
        "summarize_exposure",
        lambda flood_extent, layer_paths: {"total": {"buildings_affected": 3}, "by_municipality": {}},
    )

    output_dir = tmp_path / "out"
    report = detect.run_detection(config, output_dir, search=fake_search, fetch_gauge=_fake_gauge_bulletin)

    assert report["status"] == "complete"
    assert report["flood_polygons"] >= 1
    assert report["preview"]["pre_event"]["png"].startswith("https://example.test/api/data/v1/item/bbox/")
    assert "item=pre-1" in report["preview"]["pre_event"]["png"]
    assert "item=post-1" in report["preview"]["post_event"]["png"]
    assert report["river_gauges"]["stations"][0]["name"] == "Test Station"
    assert (output_dir / "flood_mask.tif").exists()
    assert (output_dir / "flood_extent.gpkg").exists()

    summary = json.loads((output_dir / "exposure_summary.json").read_text())
    assert summary["total"]["buildings_affected"] == 3
