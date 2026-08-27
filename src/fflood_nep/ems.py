EMS_ACTIVATION_URL = "https://mapping.emergency.copernicus.eu/backend/dashboard-api/public-activations/?code=EMSR927"
EMS_ACTIVATION_PAGE = "https://mapping.emergency.copernicus.eu/activations/EMSR927/"

EMS_CAVEAT = (
    "Copernicus EMS Rapid Mapping activation EMSR927 ('Flood in Nepal') is a real, EU-authorised "
    "independent activation for this exact event, requested by DG ECHO on 26 Aug 2026 -- but its own "
    "flood-extent/damage-assessment products are not necessarily delivered yet; check each row's status "
    "and expected_delivery before treating it as a finished dataset. Its backend API is not CORS-open, "
    "so the web UI reads a periodically-refreshed static snapshot (docs/data/ems_activation.json), not a "
    "live fetch -- re-run `fflood-nep ems` to refresh it."
)


def fetch_ems_activation(url: str = EMS_ACTIVATION_URL) -> dict | None:
    """Fetch the Copernicus EMS Rapid Mapping activation record for this event (EMSR927). Returns None
    (not raises) on any failure -- optional enrichment, shouldn't break the core detection pipeline."""
    import requests

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        results = response.json().get("results", [])
        return results[0] if results else None
    except (requests.RequestException, ValueError, IndexError, KeyError):
        return None


# Vector layers inside a delivered EMS "GRA" (grading/damage-assessment) product ZIP worth pulling
# onto the map: the observed event footprint (e.g. the landslide source itself) plus per-feature
# damage grades for buildings, facilities, and transportation infrastructure.
DAMAGE_LAYER_SUFFIXES = [
    "observedEventA", "builtUpP", "facilitiesA", "transportationA", "transportationL", "transportationP",
]

DAMAGE_CAVEAT = (
    "Copernicus EMS damage-grading layers, where delivered -- photo-interpreted building/facility/"
    "transportation damage grades (typically Destroyed/Damaged/Possibly damaged/No visible damage) plus "
    "the observed event footprint (e.g. the landslide source itself). A real, professionally-produced "
    "assessment, but photo-interpretation from post-event imagery, not a ground survey -- treat grades "
    "as indicative, not definitive. Extracted from EMS's delivered product ZIPs (not CORS-open, hence "
    "the same periodically-refreshed static snapshot pattern as ems_activation.json)."
)


def _download_zip_geojson_layers(url: str) -> dict:
    """Download a delivered EMS product ZIP and return {layer_suffix: geojson} for whichever
    DAMAGE_LAYER_SUFFIXES files it contains. Returns {} on any failure -- optional enrichment,
    shouldn't break the core activation snapshot."""
    import io
    import json
    import re
    import zipfile

    import requests

    try:
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        archive = zipfile.ZipFile(io.BytesIO(response.content))
    except (requests.RequestException, zipfile.BadZipFile):
        return {}

    suffix_pattern = re.compile(r"_(" + "|".join(DAMAGE_LAYER_SUFFIXES) + r")_v\d+\.json$")
    layers = {}
    for name in archive.namelist():
        match = suffix_pattern.search(name)
        if not match:
            continue
        try:
            layers[match.group(1)] = json.loads(archive.read(name))
        except (ValueError, KeyError):
            continue
    return layers


def merge_damage_layers(products: list[dict]) -> dict:
    """For every product with a download_path, fetch its delivered ZIP and merge every damage
    layer across every AOI into one combined FeatureCollection -- mirrors this project's existing
    "one layer, filterable by an attribute" schema (see the HOT pmtiles `category` field) so the
    web UI can toggle by aoi_name/ems_layer/damage_gra with one style block, not per-AOI plumbing.
    """
    features = []
    aois_included = []
    for product in products:
        url = product.get("download_path")
        if not url:
            continue
        layers = _download_zip_geojson_layers(url)
        if layers:
            aois_included.append(product.get("aoi_name"))
        for layer_name, geojson in layers.items():
            for feature in geojson.get("features", []):
                if not feature.get("geometry"):
                    continue  # a handful of EMS features are attribute-only records with no mapped geometry
                feature = dict(feature)
                props = dict(feature.get("properties") or {})
                props["aoi_name"] = product.get("aoi_name")
                props["ems_layer"] = layer_name
                feature["properties"] = props
                features.append(feature)

    return {"type": "FeatureCollection", "features": features, "aois_included": aois_included}


def summarize_activation(activation: dict) -> dict:
    """Reduce the full EMS API payload to the fields worth surfacing to a reader."""
    products = []
    for aoi in activation.get("aois", []):
        for product in aoi.get("products", []):
            version = product.get("version") or {}
            products.append(
                {
                    "aoi_name": aoi.get("name"),
                    "aoi_number": aoi.get("number"),
                    "product_type": product.get("type"),
                    "status": version.get("statusCode"),
                    "expected_delivery": product.get("expectedDelivery"),
                    "delivery_time": version.get("deliveryTime"),
                    "download_path": product.get("downloadPath") or None,
                    "sensors": [img.get("sensorName") for img in product.get("images", [])],
                }
            )
    return {
        "code": activation.get("code"),
        "name": activation.get("name"),
        "reason": activation.get("reason"),
        "category": activation.get("category"),
        "sub_category": activation.get("subCategory"),
        "event_time": activation.get("eventTime"),
        "activation_time": activation.get("activationTime"),
        "closed": activation.get("closed"),
        "report_link": activation.get("reportLink"),
        "activation_page": EMS_ACTIVATION_PAGE,
        "products_zip": activation.get("productsPath"),
        "products": products,
    }
