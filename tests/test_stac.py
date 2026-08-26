import json
from pathlib import Path

from fflood_nep.config import EventConfig
from fflood_nep.stac import acquisition_plan, search_query


CONFIG = Path(__file__).parents[1] / "config" / "rasuwa-2026-08-26.toml"


def test_event_config_loads_and_validates():
    config = EventConfig.from_toml(CONFIG)
    assert config.name == "rasuwa-2026-08-26"
    assert config.bbox == (85.02, 27.81, 85.42, 28.32)


def test_stac_query_is_cql2_json():
    config = EventConfig.from_toml(CONFIG)
    query = search_query(config, config.pre_start, config.pre_end)
    assert query["collections"] == ["sentinel-1-rtc"]
    assert query["datetime"] == "2026-08-01T00:00:00Z/2026-08-25T23:59:59Z"
    assert query["filter-lang"] == "cql2-json"


def test_plan_is_json_serializable():
    config = EventConfig.from_toml(CONFIG)
    json.dumps(acquisition_plan(config))
