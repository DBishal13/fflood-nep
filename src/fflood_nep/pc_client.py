from .config import EventConfig
from .exposure import EXPOSURE_CRS
from .stac import search_query

WORLDCOVER_COLLECTION = "esa-worldcover"
WORLDCOVER_ASSET = "map"


def _client():
    from pystac_client import Client

    return Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
    )


def find_best_item(config: EventConfig, start: str, end: str):
    """Search sentinel-1-rtc for the item covering the AOI best within [start, end]. None if nothing matches."""
    import planetary_computer
    from shapely.geometry import box, shape

    query = search_query(config, start, end)
    search = _client().search(
        collections=query["collections"],
        bbox=query["bbox"],
        datetime=query["datetime"],
        filter=query["filter"],
        filter_lang=query["filter-lang"],
    )
    items = list(search.items())
    if not items:
        return None

    aoi = box(*config.bbox)

    def overlap(item):
        return shape(item.geometry).intersection(aoi).area

    best = max(items, key=overlap)
    return planetary_computer.sign(best)


def target_grid(bbox: tuple, bbox_crs: str = "EPSG:4326", dst_crs: str = EXPOSURE_CRS, resolution: float = 10.0):
    """A single pixel grid (transform, width, height) that every AOI read is resampled onto, so pre/post/worldcover arrays align exactly."""
    import rasterio
    from rasterio.warp import transform_bounds

    left, bottom, right, top = transform_bounds(bbox_crs, dst_crs, *bbox)
    width = max(1, round((right - left) / resolution))
    height = max(1, round((top - bottom) / resolution))
    transform = rasterio.transform.from_origin(left, top, resolution, resolution)
    return transform, width, height


def _read_signed_asset(href: str, transform, width: int, height: int, dst_crs: str = EXPOSURE_CRS, resampling=None):
    import numpy as np
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT

    with rasterio.open(href) as src:
        with WarpedVRT(
            src,
            crs=dst_crs,
            transform=transform,
            width=width,
            height=height,
            resampling=resampling or Resampling.bilinear,
        ) as vrt:
            data = vrt.read(1)
    return np.asarray(data), transform, dst_crs


def read_aoi(item, asset_key: str, transform, width: int, height: int):
    """Read one band (continuous gamma0 backscatter) of a signed STAC item, warped onto the given target grid."""
    href = item.assets[asset_key].href
    return _read_signed_asset(href, transform, width, height)


def read_worldcover(bbox: tuple, transform, width: int, height: int):
    """Read the ESA WorldCover land-cover map, warped onto the given target grid with nearest-neighbor resampling (the values are categorical class codes, not continuous)."""
    import planetary_computer
    from rasterio.enums import Resampling

    search = _client().search(collections=[WORLDCOVER_COLLECTION], bbox=bbox)
    items = list(search.items())
    if not items:
        raise RuntimeError("no esa-worldcover item found for this AOI")
    item = planetary_computer.sign(items[0])
    href = item.assets[WORLDCOVER_ASSET].href
    return _read_signed_asset(href, transform, width, height, resampling=Resampling.nearest)
