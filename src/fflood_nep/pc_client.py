import os

from .config import EventConfig
from .exposure import EXPOSURE_CRS
from .stac import search_query

WORLDCOVER_COLLECTION = "esa-worldcover"
WORLDCOVER_ASSET = "map"

# GDAL's VSICURL layer (used by rasterio for the actual COG reads in _read_signed_asset below)
# does not retry on transient HTTP errors -- including 429s from Planetary Computer's rate
# limiting -- unless told to. This is Microsoft's own documented fix for that failure mode:
# https://planetarycomputer.microsoft.com/docs/quickstarts/reading-stac-data/
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "5")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "1")


def _client():
    from pystac_client import Client
    from pystac_client.stac_api_io import StacApiIO
    from urllib3.util.retry import Retry

    # pystac-client's own default (max_retries=5, an int) only retries on connection-level
    # failures -- HTTPAdapter(max_retries=<int>) leaves status_forcelist empty, so a 429 response
    # is returned as-is, not retried. An explicit Retry with status_forcelist is what actually
    # protects find_best_item/read_worldcover's searches against Planetary Computer rate limiting.
    retry = Retry(total=5, backoff_factor=1.0, status_forcelist=[429, 500, 502, 503, 504])
    return Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        stac_io=StacApiIO(max_retries=retry),
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


def preview_url(item, bbox: tuple, max_size: int = 1024) -> str | None:
    """A rendered preview PNG cropped to the AOI bbox, not the whole scene footprint.

    item.assets["rendered_preview"].href points at the PC /data API's whole-scene preview
    endpoint (/item/preview.png), which renders the entire Sentinel-1 swath -- mostly
    irrelevant terrain far outside a 132 km^2 flood corridor. Reuses that URL's own render
    params (expression/rescale/assets, chosen by PC for this collection) but swaps the
    endpoint for /item/bbox/{bbox}.png, which crops server-side to just the AOI.
    """
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    asset = item.assets.get("rendered_preview")
    if asset is None:
        return None
    parts = urlsplit(asset.href)
    # parse_qsl + urlencode(pairs) round-trips repeated keys (assets=vv&assets=vh, three
    # rescale=... entries) correctly; dict(parse_qsl(...)) would silently drop all but the
    # last occurrence of each repeated key.
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "tile_format"]
    query.append(("max_size", str(max_size)))
    new_path = "/api/data/v1/item/bbox/{},{},{},{}.png".format(*bbox)
    return urlunsplit((parts.scheme, parts.netloc, new_path, urlencode(query), ""))


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
