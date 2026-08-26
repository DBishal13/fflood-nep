from dataclasses import asdict

from .config import EventConfig


def search_query(config: EventConfig, start: str, end: str) -> dict:
    """Build a STAC API query without making a network call."""
    return {
        "collections": [config.collection],
        "bbox": list(config.bbox),
        "datetime": f"{start}/{end}",
        "limit": 100,
        "filter-lang": "cql2-json",
        "filter": {
            "op": "and",
            "args": [
                {"op": "like", "args": [{"property": "platform"}, f"{config.platform.lower()}%"]},
                {"op": "a_contains", "args": [{"property": "sar:polarizations"}, list(config.polarizations)]},
            ],
        },
    }


def acquisition_plan(config: EventConfig) -> dict:
    return {
        "schema": "fflood-nep/acquisition-plan/v1",
        "event": {
            "name": config.name,
            "description": config.description,
            "event_date": config.event_date,
            "bbox": list(config.bbox),
        },
        "source": {"stac_url": config.stac_url, "collection": config.collection},
        "searches": {
            "pre_event": search_query(config, config.pre_start, config.pre_end),
            "post_event": search_query(config, config.post_start, config.post_end),
        },
        "assumptions": [
            "AOI is an approximate corridor envelope and must be refined against official AOIs.",
            "Sentinel-1 GRD is selected for cloud-independent first-pass mapping.",
            "The event trigger and flood extent remain subject to validation.",
        ],
    }
