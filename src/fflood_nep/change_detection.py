import numpy as np
from scipy.ndimage import median_filter

NODATA_DB = -50.0


def to_db(gamma0: np.ndarray, nodata: float = -32768.0) -> np.ndarray:
    """Convert linear-power gamma-naught backscatter to dB."""
    valid = (gamma0 != nodata) & (gamma0 > 0)
    db = np.full(gamma0.shape, NODATA_DB, dtype=np.float32)
    db[valid] = 10.0 * np.log10(gamma0[valid])
    return db


def speckle_filter(db: np.ndarray, size: int = 5) -> np.ndarray:
    """Reduce SAR speckle with a median filter."""
    return median_filter(db, size=size)


def flood_mask(pre_db: np.ndarray, post_db: np.ndarray, threshold_db: float = -3.0) -> np.ndarray:
    """Flag pixels where backscatter dropped enough to suggest new open water."""
    return (post_db - pre_db) <= threshold_db


def remove_permanent_water(mask: np.ndarray, worldcover: np.ndarray, water_code: int = 80) -> np.ndarray:
    """Drop pixels that were already permanent water before the event."""
    return mask & (worldcover != water_code)


def polygonize(mask: np.ndarray, transform, crs, pre_db: np.ndarray, post_db: np.ndarray):
    """Turn a boolean flood mask into polygons with area (crs must be projected, e.g. a UTM zone) and a confidence score.

    Confidence (mean backscatter drop) is computed per connected region in one vectorized pass via
    scipy.ndimage, rather than re-scanning the whole raster once per polygon -- important since a noisy
    real-world mask over a large AOI can produce thousands of small regions.
    """
    import geopandas as gpd
    from rasterio.features import shapes
    from scipy.ndimage import label as ndi_label
    from scipy.ndimage import mean as ndi_mean
    from shapely.geometry import shape

    drop_db = pre_db - post_db
    labeled, num_labels = ndi_label(mask)  # 4-connectivity by default, matching rasterio.features.shapes below

    if num_labels == 0:
        return gpd.GeoDataFrame({"area_m2": [], "confidence": []}, geometry=[], crs=crs)

    mean_drop_by_label = np.atleast_1d(ndi_mean(drop_db, labeled, index=np.arange(1, num_labels + 1)))

    geometries = []
    confidences = []
    for geom, value in shapes(labeled, mask=mask, transform=transform):
        geometries.append(shape(geom))
        confidences.append(float(mean_drop_by_label[int(value) - 1]))

    gdf = gpd.GeoDataFrame({"geometry": geometries, "confidence": confidences}, crs=crs)
    gdf["area_m2"] = gdf.geometry.area
    return gdf
