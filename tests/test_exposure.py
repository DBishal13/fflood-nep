from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point, Polygon

from fflood_nep import exposure

DATA_DIR = Path(__file__).parents[1] / "data"


def _flood_extent():
    # A 100m x 100m square flood polygon in the project's UTM zone.
    square = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    return gpd.GeoDataFrame({"area_m2": [10000.0]}, geometry=[square], crs=exposure.EXPOSURE_CRS)


def test_summarize_exposure_counts_features_inside_the_flood_polygon(tmp_path):
    buildings = gpd.GeoDataFrame(
        {"adm3_name": ["Bidur", "Kalika"]},
        geometry=[Polygon([(10, 10), (20, 10), (20, 20), (10, 20)]), Polygon([(500, 500), (510, 500), (510, 510), (500, 510)])],
        crs=exposure.EXPOSURE_CRS,
    )
    roads = gpd.GeoDataFrame(
        {"adm3_name": ["Bidur"], "highway": ["secondary"]},
        geometry=[LineString([(0, 50), (100, 50)])],
        crs=exposure.EXPOSURE_CRS,
    )
    bridges = gpd.GeoDataFrame(
        {"adm3_name": ["Bidur"], "name": ["Bidur Suspension Bridge"]},
        geometry=[Point(50, 50)],
        crs=exposure.EXPOSURE_CRS,
    )

    buildings_path = tmp_path / "buildings.gpkg"
    roads_path = tmp_path / "roads.gpkg"
    bridges_path = tmp_path / "bridges.gpkg"
    buildings.to_file(buildings_path, driver="GPKG")
    roads.to_file(roads_path, driver="GPKG")
    bridges.to_file(bridges_path, driver="GPKG")

    summary = exposure.summarize_exposure(
        _flood_extent(),
        {"buildings": buildings_path, "roads": roads_path, "bridges": bridges_path},
    )

    assert summary["total"]["buildings_affected"] == 1
    assert summary["total"]["roads_affected_km"] == pytest.approx(0.1)
    assert summary["total"]["roads_affected_by_highway_km"]["secondary"] == pytest.approx(0.1)
    assert summary["total"]["bridges_affected"] == 1
    assert summary["total"]["bridges_affected_names"] == ["Bidur Suspension Bridge"]
    assert summary["by_municipality"]["Bidur"]["buildings_affected"] == 1
    assert "Kalika" not in summary["by_municipality"]


def test_summarize_exposure_handles_empty_flood_extent():
    empty = gpd.GeoDataFrame({"area_m2": []}, geometry=[], crs=exposure.EXPOSURE_CRS)
    summary = exposure.summarize_exposure(empty, {})
    assert summary == {"total": {}, "by_municipality": {}}


@pytest.mark.skipif(not DATA_DIR.exists(), reason="local data/ folder (gitignored) not present")
def test_load_hot_layer_and_aoi_read_the_real_downloaded_dataset():
    path = exposure.load_hot_layer("bridges", DATA_DIR)
    assert path.exists()
    gdf = gpd.read_file(path)
    assert len(gdf) > 0

    aoi = exposure.load_hot_aoi(DATA_DIR)
    assert aoi.is_valid
    assert aoi.area > 0
