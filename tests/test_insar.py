import requests

from fflood_nep import insar

REAL_STYLE_SCENE_PRE = {
    "granuleName": "S1D_IW_SLC__1SDV_20260824T001843_20260824T001910_004260_007D5D_98CC",
    "sceneId": "S1D_IW_SLC__1SDV_20260824T001843_20260824T001910_004260_007D5D_98CC",
    "startTime": "2026-08-24T00:18:43Z",
    "flightDirection": "DESCENDING",
    "track": 19,
    "relativeOrbit": 19,
}
REAL_STYLE_SCENE_OTHER_TRACK = {
    "granuleName": "S1D_IW_SLC__1SDV_20260819T001036_20260819T001101_004187_007ABD_1234",
    "sceneId": "S1D_IW_SLC__1SDV_20260819T001036_20260819T001101_004187_007ABD_1234",
    "startTime": "2026-08-19T00:10:36Z",
    "flightDirection": "DESCENDING",
    "track": 121,
    "relativeOrbit": 121,
}
REAL_STYLE_SCENE_POST_SAME_TRACK = {
    "granuleName": "S1D_IW_SLC__1SDV_20260905T001843_20260905T001910_004435_008ABC_5678",
    "sceneId": "S1D_IW_SLC__1SDV_20260905T001843_20260905T001910_004435_008ABC_5678",
    "startTime": "2026-09-05T00:18:43Z",
    "flightDirection": "DESCENDING",
    "track": 19,
    "relativeOrbit": 19,
}


def _fake_response(rows):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return [rows]

    return FakeResponse()


def test_find_slc_scenes_sorts_newest_first(monkeypatch):
    unsorted_rows = [REAL_STYLE_SCENE_OTHER_TRACK, REAL_STYLE_SCENE_POST_SAME_TRACK, REAL_STYLE_SCENE_PRE]
    monkeypatch.setattr(requests, "get", lambda *a, **k: _fake_response(unsorted_rows))

    scenes = insar.find_slc_scenes((85.02, 27.81, 85.42, 28.32), "2026-08-01T00:00:00Z", "2026-09-10T00:00:00Z")

    assert [s["sceneId"] for s in scenes] == [
        REAL_STYLE_SCENE_POST_SAME_TRACK["sceneId"],
        REAL_STYLE_SCENE_PRE["sceneId"],
        REAL_STYLE_SCENE_OTHER_TRACK["sceneId"],
    ]


def test_latest_pre_event_scene_returns_newest(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _fake_response([REAL_STYLE_SCENE_OTHER_TRACK, REAL_STYLE_SCENE_PRE]))

    scene = insar.latest_pre_event_scene((85.02, 27.81, 85.42, 28.32), "2026-08-26T00:00:00Z")

    assert scene["sceneId"] == REAL_STYLE_SCENE_PRE["sceneId"]


def test_latest_pre_event_scene_returns_none_when_empty(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _fake_response([]))
    assert insar.latest_pre_event_scene((85.02, 27.81, 85.42, 28.32), "2026-08-26T00:00:00Z") is None


def test_find_post_event_scene_requires_same_track_and_direction(monkeypatch):
    # search would return scenes from multiple tracks -- only the same-track one should match
    monkeypatch.setattr(
        requests, "get",
        lambda *a, **k: _fake_response([REAL_STYLE_SCENE_OTHER_TRACK, REAL_STYLE_SCENE_POST_SAME_TRACK]),
    )

    post = insar.find_post_event_scene((85.02, 27.81, 85.42, 28.32), REAL_STYLE_SCENE_PRE, "2026-08-26T00:00:00Z")

    assert post["sceneId"] == REAL_STYLE_SCENE_POST_SAME_TRACK["sceneId"]


def test_find_post_event_scene_returns_none_when_track_not_revisited_yet(monkeypatch):
    # satellite has revisited other tracks but not the reference scene's own track
    monkeypatch.setattr(requests, "get", lambda *a, **k: _fake_response([REAL_STYLE_SCENE_OTHER_TRACK]))

    post = insar.find_post_event_scene((85.02, 27.81, 85.42, 28.32), REAL_STYLE_SCENE_PRE, "2026-08-26T00:00:00Z")

    assert post is None


class FakeJob:
    def __init__(self, job_id, status_code, files=None):
        self.job_id = job_id
        self.status_code = status_code
        self.files = files
        self.browse_images = []

    def succeeded(self):
        return self.status_code == "SUCCEEDED"

    def failed(self):
        return self.status_code == "FAILED"


class FakeBatch:
    def __init__(self, jobs):
        self.jobs = jobs


class FakeHyP3:
    def __init__(self, submitted_status="PENDING"):
        self.submitted_status = submitted_status
        self.submit_calls = []
        self._jobs_by_id = {}

    def submit_insar_job(self, granule1, granule2, name=None):
        self.submit_calls.append((granule1, granule2, name))
        job = FakeJob("job-123", self.submitted_status)
        self._jobs_by_id["job-123"] = job
        return FakeBatch([job])

    def get_job_by_id(self, job_id):
        return self._jobs_by_id[job_id]

    def refresh(self, job):
        return job


def test_check_and_advance_stops_at_pre_event_when_no_post_event_yet(tmp_path, monkeypatch):
    # a real ASF search scoped to "after the event" would never return a scene from before it --
    # mock needs to respect that date-range distinction, not return the same fixture regardless.
    def fake_get(*args, **kwargs):
        start = kwargs["params"]["start"]
        return _fake_response([REAL_STYLE_SCENE_PRE] if start < "2026-08-26" else [])

    monkeypatch.setattr(requests, "get", fake_get)
    state_path = tmp_path / "insar_status.json"

    state = insar.check_and_advance(state_path, (85.02, 27.81, 85.42, 28.32), "2026-08-26T00:00:00Z", hyp3=FakeHyP3())

    assert state["pre_event_scene"]["sceneId"] == REAL_STYLE_SCENE_PRE["sceneId"]
    assert state["post_event_scene"] is None
    assert state["job"] is None


def test_check_and_advance_submits_job_once_post_event_scene_appears(tmp_path, monkeypatch):
    state_path = tmp_path / "insar_status.json"
    state_path.write_text(__import__("json").dumps({"pre_event_scene": REAL_STYLE_SCENE_PRE, "post_event_scene": None, "job": None}))
    monkeypatch.setattr(requests, "get", lambda *a, **k: _fake_response([REAL_STYLE_SCENE_POST_SAME_TRACK]))
    fake_hyp3 = FakeHyP3()

    state = insar.check_and_advance(state_path, (85.02, 27.81, 85.42, 28.32), "2026-08-26T00:00:00Z", hyp3=fake_hyp3)

    assert state["post_event_scene"]["sceneId"] == REAL_STYLE_SCENE_POST_SAME_TRACK["sceneId"]
    assert state["job"]["job_id"] == "job-123"
    assert fake_hyp3.submit_calls == [(REAL_STYLE_SCENE_PRE["granuleName"], REAL_STYLE_SCENE_POST_SAME_TRACK["granuleName"], "rasuwa-2026-08-26-coherence")]


def test_check_and_advance_does_not_resubmit_once_job_exists(tmp_path, monkeypatch):
    import json

    state_path = tmp_path / "insar_status.json"
    state_path.write_text(json.dumps({
        "pre_event_scene": REAL_STYLE_SCENE_PRE,
        "post_event_scene": REAL_STYLE_SCENE_POST_SAME_TRACK,
        "job": {"job_id": "job-123", "status": "RUNNING", "files": None},
    }))
    fake_hyp3 = FakeHyP3()
    fake_hyp3._jobs_by_id["job-123"] = FakeJob("job-123", "SUCCEEDED", files=[{"url": "https://example.test/coherence.tif"}])

    state = insar.check_and_advance(state_path, (85.02, 27.81, 85.42, 28.32), "2026-08-26T00:00:00Z", hyp3=fake_hyp3)

    assert fake_hyp3.submit_calls == []  # never resubmitted
    assert state["job"]["status"] == "SUCCEEDED"
    assert state["job"]["files"] == [{"url": "https://example.test/coherence.tif"}]


def test_find_post_event_scene_picks_earliest_not_newest_match(monkeypatch):
    later_same_track = {**REAL_STYLE_SCENE_POST_SAME_TRACK, "sceneId": "later-one", "startTime": "2026-09-17T00:18:43Z"}
    monkeypatch.setattr(
        requests, "get",
        lambda *a, **k: _fake_response([later_same_track, REAL_STYLE_SCENE_POST_SAME_TRACK]),
    )

    post = insar.find_post_event_scene((85.02, 27.81, 85.42, 28.32), REAL_STYLE_SCENE_PRE, "2026-08-26T00:00:00Z")

    assert post["sceneId"] == REAL_STYLE_SCENE_POST_SAME_TRACK["sceneId"]
