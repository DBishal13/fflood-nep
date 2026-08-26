from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class EventConfig:
    name: str
    description: str
    event_date: str
    bbox: tuple[float, float, float, float]
    stac_url: str
    collection: str
    platform: str
    polarizations: tuple[str, ...]
    pre_start: str
    pre_end: str
    post_start: str
    post_end: str

    @classmethod
    def from_toml(cls, path: Path) -> "EventConfig":
        with path.open("rb") as stream:
            raw = tomllib.load(stream)
        event = raw["event"]
        aoi = raw["aoi"]
        data = raw["data"]
        windows = raw["windows"]
        bbox = tuple(float(value) for value in aoi["bbox"])
        if len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            raise ValueError("aoi.bbox must be [min_lon, min_lat, max_lon, max_lat]")
        for value in (windows["pre_start"], windows["pre_end"], windows["post_start"], windows["post_end"]):
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return cls(
            name=event["name"],
            description=event["description"],
            event_date=event["event_date"],
            bbox=bbox,
            stac_url=data["stac_url"],
            collection=data["collection"],
            platform=data["platform"],
            polarizations=tuple(data["polarizations"]),
            pre_start=windows["pre_start"],
            pre_end=windows["pre_end"],
            post_start=windows["post_start"],
            post_end=windows["post_end"],
        )
