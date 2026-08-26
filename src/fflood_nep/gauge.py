DHM_BULLETIN_URL = "https://raw.githubusercontent.com/nirajbhusal/rasuwa-flood-bulletin/main/dhm-rivers.json"

GAUGE_CAVEAT = (
    "River gauge readings are from a community-maintained mirror of DHM data "
    "(https://www.dhm.gov.np/hydrology/river-watch), not an official feed. A station can be "
    "'silent' (not currently reporting) or 'washed' (gauge destroyed); its level_m is then a stale "
    "last reading, not a live measurement -- check washed/silent before treating a reading as current."
)


def fetch_gauge_status(url: str = DHM_BULLETIN_URL) -> dict | None:
    """Fetch the latest DHM river-gauge bulletin. Returns None (not raises) on any failure, since this
    is an optional enrichment and shouldn't break the core detection pipeline."""
    import requests

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError):
        return None
