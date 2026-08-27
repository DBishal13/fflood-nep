"""Sentinel-1 InSAR coherence via ASF's HyP3 on-demand processing service.

A separate pipeline from pc_client.py: Planetary Computer only hosts RTC/GRD (amplitude,
phase-discarded), and coherence/deformation needs SLC pairs, which HyP3 processes on request.
Requires a NASA Earthdata Login in ~/.netrc -- hyp3_sdk reads it automatically; this module never
handles credentials directly.
"""

ASF_SEARCH_URL = "https://api.daac.asf.alaska.edu/services/search/param"

INSAR_CAVEAT = (
    "Sentinel-1 InSAR coherence maps the extent of surface disturbance at the avalanche/landslide "
    "source -- it does not give phase-unwrapped ground displacement. A mass-wasting event this "
    "violent will likely fully decorrelate the interferogram right at the rupture, so coherence "
    "loss (not displacement retrieval) is the practical, robust product here."
)


def find_slc_scenes(bbox: tuple, start: str, end: str) -> list[dict]:
    """Search ASF's public catalog (no auth needed -- this is metadata search, not data download)
    for Sentinel-1 SLC scenes intersecting bbox within [start, end] (ISO 8601). Newest first."""
    import requests

    minx, miny, maxx, maxy = bbox
    polygon = f"POLYGON(({minx} {miny},{maxx} {miny},{maxx} {maxy},{minx} {maxy},{minx} {miny}))"
    response = requests.get(
        ASF_SEARCH_URL,
        params={
            "intersectsWith": polygon,
            "platform": "Sentinel-1",
            "processingLevel": "SLC",
            "start": start,
            "end": end,
            "output": "json",
        },
        timeout=30,
    )
    response.raise_for_status()
    rows = response.json()[0]
    return sorted(rows, key=lambda r: r["startTime"], reverse=True)


def latest_pre_event_scene(bbox: tuple, before: str) -> dict | None:
    """The most recent SLC scene over bbox before `before` (ISO 8601) -- the reference pass an
    InSAR pair gets built against."""
    scenes = find_slc_scenes(bbox, "2014-01-01T00:00:00Z", before)
    return scenes[0] if scenes else None


def find_post_event_scene(bbox: tuple, reference_scene: dict, after: str) -> dict | None:
    """The earliest SLC scene over bbox after `after`, on the SAME relative orbit/track and flight
    direction as `reference_scene` -- InSAR needs a same-track pair, not just any two passes, or
    the geometry won't co-register. None if the satellite hasn't revisited that track yet."""
    scenes = find_slc_scenes(bbox, after, "2100-01-01T00:00:00Z")
    track = reference_scene.get("track") or reference_scene.get("relativeOrbit")
    direction = reference_scene.get("flightDirection")
    candidates = [
        s for s in scenes
        if s.get("flightDirection") == direction and (s.get("track") or s.get("relativeOrbit")) == track
    ]
    return candidates[-1] if candidates else None  # earliest matching pass, not the newest


def submit_coherence_job(hyp3, pre_granule: str, post_granule: str, name: str):
    """Submit a HyP3 InSAR job for the given granule pair. Default settings (no extra flags) are
    enough for a coherence-loss map -- the base product always includes coherence, unwrapped
    phase, and amplitude; the optional flags (DEM, displacement maps, look vectors) are for full
    deformation retrieval, which isn't the goal here (see INSAR_CAVEAT)."""
    return hyp3.submit_insar_job(pre_granule, post_granule, name=name)


def job_status(hyp3, job) -> dict:
    """Refresh and summarize a submitted job's status."""
    refreshed = hyp3.refresh(job)
    return {
        "job_id": refreshed.job_id,
        "status": refreshed.status_code,
        "succeeded": refreshed.succeeded(),
        "failed": refreshed.failed(),
        "browse_images": refreshed.browse_images,
        "files": refreshed.files,
    }


def load_state(path) -> dict:
    import json

    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"pre_event_scene": None, "post_event_scene": None, "job": None}


def save_state(path, state: dict) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, default=str) + "\n", encoding="utf-8")


def check_and_advance(state_path, bbox: tuple, event_start: str, hyp3=None) -> dict:
    """Idempotent state-machine step: pins a pre-event reference scene, watches for a matching
    post-event pass, and submits a HyP3 coherence job the moment one appears -- then tracks that
    job to completion. Safe to call repeatedly (e.g. from a scheduled check); each call only
    advances whatever hasn't been resolved yet."""
    state = load_state(state_path)

    if state["pre_event_scene"] is None:
        state["pre_event_scene"] = latest_pre_event_scene(bbox, event_start)

    if state["pre_event_scene"] and state["post_event_scene"] is None:
        state["post_event_scene"] = find_post_event_scene(bbox, state["pre_event_scene"], event_start)

    if state["post_event_scene"] and state["job"] is None:
        if hyp3 is None:
            import hyp3_sdk

            hyp3 = hyp3_sdk.HyP3()
        batch = submit_coherence_job(
            hyp3,
            state["pre_event_scene"]["granuleName"],
            state["post_event_scene"]["granuleName"],
            name="rasuwa-2026-08-26-coherence",
        )
        submitted = batch.jobs[0]
        state["job"] = {"job_id": submitted.job_id, "status": submitted.status_code, "files": None}
    elif state["job"] and state["job"]["status"] not in ("SUCCEEDED", "FAILED"):
        if hyp3 is None:
            import hyp3_sdk

            hyp3 = hyp3_sdk.HyP3()
        info = job_status(hyp3, hyp3.get_job_by_id(state["job"]["job_id"]))
        state["job"]["status"] = info["status"]
        if info["succeeded"]:
            state["job"]["files"] = info["files"]

    state["caveat"] = INSAR_CAVEAT
    save_state(state_path, state)
    return state
