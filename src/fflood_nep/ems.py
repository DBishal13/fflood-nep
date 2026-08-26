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
