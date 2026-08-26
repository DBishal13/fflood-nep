import json
from pathlib import Path

from . import change_detection, exposure, gauge, pc_client
from .config import EventConfig

ASSUMPTIONS = [
    "AOI is the HOT hot_flood_npl 1 km river-corridor buffer, not a modelled or observed flood extent on its own.",
    "SAR shadow, layover, steep terrain, sediment, vegetation, and river morphology can create false positives.",
    "The backscatter-drop threshold is a coarse heuristic, not a calibrated flood-probability model.",
    "OpenStreetMap coverage in the exposure layers reflects volunteer mapping activity and changes between "
    "the HOT dataset's daily rebuilds; treat exposure counts as approximate, not authoritative.",
    gauge.GAUGE_CAVEAT,
    "Do not use this output as the sole basis for evacuation or rescue decisions.",
]


def _gauge_section(fetch_gauge) -> dict | None:
    bulletin = fetch_gauge()
    if bulletin is None:
        return None
    return {
        "source": gauge.DHM_BULLETIN_URL,
        "source_note": (
            "Numeric readings originate from DHM's own station pages (dhm_source below verifies each one "
            "directly); the washed/silent flags are this community mirror's own annotation -- DHM's raw feed "
            "does not publish gauge-outage status itself."
        ),
        "updated_at": bulletin.get("updated_at"),
        "note_np": bulletin.get("note_np"),
        "stations": [
            {
                "name": station.get("name"),
                "district_np": station.get("district_np"),
                "level_m": station.get("level_m"),
                "warning_m": station.get("warning_m"),
                "danger_m": station.get("danger_m"),
                "status": station.get("status"),
                "steady": station.get("steady"),
                "observed_at": station.get("observed_at"),
                "silent": station.get("silent"),
                "washed": station.get("washed"),
                "dhm_source": station.get("source"),
            }
            for station in bulletin.get("stations", [])
        ],
    }


def _item_preview(item, label: str, bbox: tuple) -> dict | None:
    if item is None:
        return None
    preview = {}
    cropped = pc_client.preview_url(item, bbox)
    if cropped is not None:
        preview["png"] = cropped
    tilejson_asset = item.assets.get("tilejson")
    if tilejson_asset is not None:
        preview["tilejson"] = tilejson_asset.href
    if not preview:
        return None
    preview["item"] = item.id
    preview["label"] = label
    return preview


def _preview_section(pre_item, post_item, bbox: tuple) -> dict | None:
    pre_preview = _item_preview(pre_item, "pre_event", bbox)
    post_preview = _item_preview(post_item, "post_event", bbox)
    if pre_preview is None and post_preview is None:
        return None
    return {
        "note": "Browser-viewable PNG/tile links for the SAR scenes, cropped to the AOI bbox (not the whole "
        "scene footprint) by Planetary Computer's /data API -- not the flood-extent output itself.",
        "pre_event": pre_preview,
        "post_event": post_preview,
    }


def run_detection(
    config: EventConfig,
    output_dir: Path,
    data_dir: Path = Path("data"),
    polarization: str = "VV",
    threshold_db: float = -3.0,
    with_exposure: bool = True,
    with_gauge: bool = True,
    search=pc_client.find_best_item,
    fetch_gauge=gauge.fetch_gauge_status,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    asset_key = polarization.lower()

    river_gauges = _gauge_section(fetch_gauge) if with_gauge else None

    pre_item = search(config, config.pre_start, config.pre_end)
    post_item = search(config, config.post_start, config.post_end)

    if pre_item is None or post_item is None:
        missing = "pre" if pre_item is None else "post"
        report = {
            "schema": "fflood-nep/detection-report/v1",
            "status": f"waiting_for_{missing}_event_scene",
            "preview": _preview_section(pre_item, post_item, config.bbox),
            "river_gauges": river_gauges,
            "assumptions": ASSUMPTIONS,
        }
        (output_dir / "detection_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report

    transform, width, height = pc_client.target_grid(config.bbox)
    crs = pc_client.EXPOSURE_CRS
    pre_arr, _, _ = pc_client.read_aoi(pre_item, asset_key, transform, width, height)
    post_arr, _, _ = pc_client.read_aoi(post_item, asset_key, transform, width, height)
    worldcover_arr, _, _ = pc_client.read_worldcover(config.bbox, transform, width, height)

    pre_db = change_detection.speckle_filter(change_detection.to_db(pre_arr))
    post_db = change_detection.speckle_filter(change_detection.to_db(post_arr))

    mask = change_detection.flood_mask(pre_db, post_db, threshold_db)
    mask = change_detection.remove_permanent_water(mask, worldcover_arr)

    flood_extent = change_detection.polygonize(mask, transform, crs, pre_db, post_db)

    aoi = exposure.load_hot_aoi(data_dir)
    aoi_in_crs = _reproject_geom(aoi, "EPSG:4326", crs)
    if not flood_extent.empty:
        import geopandas as gpd

        flood_extent = gpd.clip(flood_extent, gpd.GeoDataFrame(geometry=[aoi_in_crs], crs=crs))
        flood_extent["area_m2"] = flood_extent.geometry.area

    _write_mask(mask, transform, crs, output_dir / "flood_mask.tif")
    flood_extent.to_file(output_dir / "flood_extent.gpkg", driver="GPKG")

    exposure_summary = None
    if with_exposure:
        layer_paths = {name: exposure.load_hot_layer(name, data_dir) for name in exposure.HOT_LAYERS}
        exposure_summary = exposure.summarize_exposure(flood_extent, layer_paths)
        (output_dir / "exposure_summary.json").write_text(
            json.dumps(exposure_summary, indent=2) + "\n", encoding="utf-8"
        )

    report = {
        "schema": "fflood-nep/detection-report/v1",
        "status": "complete",
        "pre_event_item": pre_item.id,
        "post_event_item": post_item.id,
        "polarization": polarization,
        "threshold_db": threshold_db,
        "flood_polygons": int(len(flood_extent)),
        "flood_area_m2": float(flood_extent["area_m2"].sum()) if len(flood_extent) else 0.0,
        "preview": _preview_section(pre_item, post_item, config.bbox),
        "river_gauges": river_gauges,
        "assumptions": ASSUMPTIONS,
    }
    (output_dir / "detection_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _reproject_geom(geom, src_crs: str, dst_crs: str):
    from pyproj import Transformer
    from shapely.ops import transform as shapely_transform

    if src_crs == dst_crs:
        return geom
    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    return shapely_transform(transformer.transform, geom)


def _write_mask(mask, transform, crs, path: Path) -> None:
    import numpy as np
    import rasterio

    with rasterio.open(
        path,
        "w",
        driver="COG",
        height=mask.shape[0],
        width=mask.shape[1],
        count=1,
        dtype="uint8",
        crs=crs,
        transform=transform,
        nodata=0,
    ) as dst:
        dst.write(mask.astype(np.uint8), 1)
