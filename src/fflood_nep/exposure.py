import json
import zipfile
from pathlib import Path

HOT_LAYERS = ("buildings", "roads", "bridges", "health_facilities", "education_facilities", "populated_places")
HOT_BASE_URL = "https://production-raw-data-api.s3.amazonaws.com/ISO3/NPL"
EXPOSURE_CRS = "EPSG:32645"  # UTM zone for the Bhote Koshi / Trishuli corridor


def _zip_path(name: str, data_dir: Path) -> Path:
    return data_dir / f"hot_flood_npl_{name}_osm_gpkg.zip"


def _extracted_path(name: str, data_dir: Path) -> Path:
    return data_dir / "extracted" / name / f"{name}.gpkg"


def download_hot_layer(name: str, dest_dir: Path) -> Path:
    """Download one HOT exposure layer (OSM variant) from HDX's fixed S3 path."""
    import requests

    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / f"hot_flood_npl_{name}_osm_gpkg.zip"
    url = f"{HOT_BASE_URL}/{name}/hot_flood_npl_{name}_osm_gpkg.zip"
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    zip_path.write_bytes(response.content)
    return zip_path


def load_hot_layer(name: str, data_dir: Path = Path("data"), refresh: bool = False) -> Path:
    """Return the path to an extracted HOT layer GeoPackage, extracting or downloading as needed."""
    extracted = _extracted_path(name, data_dir)
    if extracted.exists() and not refresh:
        return extracted

    zip_path = _zip_path(name, data_dir)
    if not zip_path.exists() or refresh:
        zip_path = download_hot_layer(name, data_dir)

    extract_dir = extracted.parent
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(extract_dir)

    if not extracted.exists():
        raise FileNotFoundError(f"expected {extracted} after extracting {zip_path}")
    return extracted


def load_hot_aoi(data_dir: Path = Path("data")):
    """Load the precise HOT flood-corridor AOI polygon (WGS84)."""
    from shapely.geometry import shape

    path = data_dir / "hot_flood_npl_aoi.geojson"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return shape(raw["features"][0]["geometry"])


def summarize_exposure(flood_extent, layer_paths: dict[str, Path]) -> dict:
    """Spatially join flood polygons against HOT exposure layers, broken down by municipality (adm3).

    HOT's export leaves ward-level (adm4_name) empty for this AOI, so adm3_name (municipality /
    rural municipality) is the finest administrative breakdown actually populated in the data.
    """
    import geopandas as gpd

    if flood_extent.empty:
        return {"total": {}, "by_municipality": {}}

    flood_utm = flood_extent.to_crs(EXPOSURE_CRS)
    flood_union = gpd.GeoDataFrame(geometry=[flood_utm.geometry.union_all()], crs=EXPOSURE_CRS)

    total: dict = {}
    by_municipality: dict[str, dict] = {}

    if "buildings" in layer_paths:
        buildings = gpd.read_file(layer_paths["buildings"]).to_crs(EXPOSURE_CRS)
        hit = gpd.sjoin(buildings, flood_union, how="inner", predicate="intersects")
        total["buildings_affected"] = int(len(hit))
        total["buildings_footprint_m2"] = float(hit.geometry.area.sum())
        for name, group in hit.groupby("adm3_name"):
            by_municipality.setdefault(name, {})["buildings_affected"] = int(len(group))

    if "roads" in layer_paths:
        roads = gpd.read_file(layer_paths["roads"]).to_crs(EXPOSURE_CRS)
        # HOT's roads export also includes point features (e.g. traffic signals); overlay needs one geometry type.
        roads = roads[roads.geometry.geom_type.isin(["LineString", "MultiLineString"])]
        hit = gpd.overlay(roads, flood_union, how="intersection")
        total["roads_affected_km"] = float(hit.geometry.length.sum() / 1000.0)
        total["roads_affected_by_highway_km"] = {
            str(highway): float(group.geometry.length.sum() / 1000.0)
            for highway, group in hit.groupby("highway")
        }
        for name, group in hit.groupby("adm3_name"):
            by_municipality.setdefault(name, {})["roads_affected_km"] = float(group.geometry.length.sum() / 1000.0)

    if "bridges" in layer_paths:
        bridges = gpd.read_file(layer_paths["bridges"]).to_crs(EXPOSURE_CRS)
        hit = gpd.sjoin(bridges, flood_union, how="inner", predicate="intersects")
        total["bridges_affected"] = int(len(hit))
        total["bridges_affected_names"] = sorted(name for name in hit["name"].dropna().unique().tolist())
        for name, group in hit.groupby("adm3_name"):
            by_municipality.setdefault(name, {})["bridges_affected"] = int(len(group))

    for layer_name, key in (
        ("health_facilities", "health_facilities_affected"),
        ("education_facilities", "education_facilities_affected"),
        ("populated_places", "populated_places_affected"),
    ):
        if layer_name not in layer_paths:
            continue
        gdf = gpd.read_file(layer_paths[layer_name]).to_crs(EXPOSURE_CRS)
        hit = gpd.sjoin(gdf, flood_union, how="inner", predicate="intersects")
        total[key] = int(len(hit))
        for name, group in hit.groupby("adm3_name"):
            by_municipality.setdefault(name, {})[key] = int(len(group))

    return {"total": total, "by_municipality": by_municipality}
