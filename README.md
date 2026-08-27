# fflood-nep

A reproducible starting point for mapping the 26 August 2026 Nepal flash flood using open Earth-observation data.

This slice does two things: builds an auditable STAC acquisition plan, and runs an actual Sentinel-1 SAR change-detection pass that produces a flood-extent mask, vector polygons, and an exposure summary (buildings/roads/facilities affected, by municipality). It is a "quick response" MVP, not rescue intelligence — see Safety and interpretation below.

## Quick start

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
fflood-nep plan --config config/rasuwa-2026-08-26.toml --output outputs/acquisition-plan.json
```

The generated JSON contains separate pre-event and post-event Sentinel-1 searches, the event AOI, and the assumptions used. The default STAC endpoint is Microsoft Planetary Computer.

### Prerequisites for `detect`

- **The HOT exposure dataset in `data/`.** Download the `hot_flood_npl` dataset from HDX (https://data.humdata.org/dataset/hot_flood_npl) and extract it into `data/` at the repo root (gitignored — it's third-party ODC-ODbL data, not source). It provides the precise flood-corridor AOI polygon and the buildings/roads/bridges/health/education/populated-places layers used for the exposure summary. It is rebuilt daily, so re-download for fresher OSM coverage on later runs.
- **A Planetary Computer subscription key is *not* required.** `sentinel-1-rtc` is flagged `msft:requires_account: true` in its own STAC metadata, but that's not enforced for search/read access in practice: confirmed live on 2026-08-26 that the collection's STAC search returns items acquired the same day with no key or `Authorization` header at all, and the SAS-token signing step (`planetary_computer.sign`) works unauthenticated too — a key only raises Planetary Computer's rate limits, it isn't a precondition for this project to function. `pc_client.find_best_item` and `read_aoi`/`read_worldcover` also retry automatically on `429`/`5xx` (STAC search via an explicit `urllib3.Retry(status_forcelist=[429,500,502,503,504])` — pystac-client's own default `max_retries=5` looks like it covers this but doesn't, since a bare int only retries connection failures, not HTTP status codes; raster reads via `GDAL_HTTP_MAX_RETRY`/`GDAL_HTTP_RETRY_DELAY`, Microsoft's own documented fix for the same gap in GDAL's VSICURL layer), so transient rate-limiting resolves on its own before it becomes your problem. Only get a key (https://planetarycomputer.developer.azure-api.net/, then `export PC_SDK_SUBSCRIPTION_KEY=...`) if `429`s are still frequent enough after that to slow you down.

```bash
fflood-nep detect --config config/rasuwa-2026-08-26.toml --output-dir outputs/detect
```

If no post-event Sentinel-1 scene exists yet for the corridor (likely for the first hours/days after the event, given Sentinel-1 revisit time), `detect` writes a `detection_report.json` with `status: "waiting_for_post_event_scene"` instead of failing — just re-run it later. Once both scenes are available, it writes:

- `flood_mask.tif` — a COG flood/no-flood raster, clipped to the HOT AOI and masked against permanent water.
- `flood_extent.gpkg` — flood polygons with `area_m2` and a per-polygon `confidence` score (mean backscatter drop).
- `exposure_summary.json` — buildings/roads/bridges/health/education facilities affected, in total and broken down by municipality (`--no-exposure` to skip; ward-level breakdown isn't available since HOT's export leaves that field empty for this AOI).
- `detection_report.json` — scenes used, parameters, a `preview` section (browser-viewable PNG/tile links for the raw pre/post SAR scenes, hosted by Planetary Computer's `/data` API — open `preview.pre_event.png` in any browser, no GIS software needed), a `river_gauges` snapshot (see below), and the caveats below. `preview` is populated as soon as a scene is found, even before both pre/post are available.

`detection_report.json` also embeds the latest DHM river-gauge readings for the corridor, pulled from a community-maintained mirror (https://github.com/nirajbhusal/rasuwa-flood-bulletin) rather than SAR imagery, so it's available even while `detect` is still waiting on a post-event scene (`--no-gauge` to skip). **Check each station's `washed`/`silent` flags before treating `level_m` as current** — a washed-out gauge keeps reporting its last reading before failing, which can look like an active alert when it isn't.

It also embeds a snapshot of the Copernicus EMS Rapid Mapping activation for this event (EMSR927, `--no-ems` to skip) — a real, independent EU-authorised activation, not something this project runs itself. Its own products may not be delivered yet; check each row's `status`/`expected_delivery`. Refresh just this snapshot with `fflood-nep ems --output docs/data/ems_activation.json` (its API isn't CORS-open, so the web UI reads that committed file rather than fetching it live).

### InSAR coherence (separate from `detect`)

`detect`'s SAR pipeline uses amplitude/backscatter (RTC/GRD) to map flood *extent*. It cannot say anything about *deformation* at the avalanche/landslide source, because RTC/GRD products discard phase. `fflood-nep insar` is a separate pipeline for that:

```bash
fflood-nep insar --bbox 85.02 27.81 85.42 28.32 --event-start 2026-08-26T00:00:00Z --output docs/data/insar_status.json
```

It's an idempotent state machine, safe to re-run: it pins the most recent pre-event Sentinel-1 **SLC** scene (phase-preserving, unlike RTC/GRD — sourced from ASF's public catalog, no auth needed for search), watches for the next SLC pass on the *same relative orbit/track* (InSAR needs a same-track pair to co-register), and once one appears, submits a coherence job to [ASF's HyP3 on-demand processing service](https://hyp3-docs.asf.alaska.edu/) and tracks it to completion.

**Requires a free NASA Earthdata Login** in `~/.netrc`:

```
machine urs.earthdata.nasa.gov
    login YOUR_USERNAME
    password YOUR_PASSWORD
```

Then `chmod 600 ~/.netrc`. Register at https://urs.earthdata.nasa.gov/users/new, then sign in once at https://search.asf.alaska.edu/ to authorize the HyP3 application on your account. `hyp3_sdk` reads the file automatically — this project never handles the credentials itself.

Expect coherence, not a clean displacement map: a mass-wasting event this violent will likely fully decorrelate the interferogram right at the rupture (the ground surface itself changed too much between passes for phase to stay coherent). That decorrelation is itself the useful signal here — a coherence-loss map delineates the disturbed source area, which plain amplitude backscatter can't.

## Web UI

**Live at https://dbishal13.github.io/fflood-nep/** — an interactive map dashboard ("Corridor Watch") built from this project's data sources, served as a static site from `docs/` via GitHub Pages.

It's a single static HTML/CSS/JS page (MapLibre GL JS + the PMTiles protocol plugin, both from CDN — no build step) with **no backend**. Most sources are fetched live because they turned out to be CORS-open; the rest are periodically-refreshed static snapshots committed to `docs/data/`, refreshed by hand (or by a scheduled check-in) rather than a server:

- The map itself: HOT's live `hot_flood_npl.pmtiles` (one combined vector layer, 47k+ features, filterable by a `category` attribute into 11 toggleable layers — buildings, roads, waterways, bridges, health/education facilities, populated places, financial services, points of interest, cultural places, airports) and its AOI boundary, fetched directly from HOT's S3 bucket on every page load.
- River gauges: fetched live from the same DHM community mirror `detect` uses.
- The SAR panel: runs the same STAC search as `pc_client.find_best_item` client-side against Planetary Computer, so it always reflects the actual latest scene, not a snapshot.
- Planet imagery: a client-side mosaic of Planet Crisis Response's open PlanetScope catalog for this event ([source.coop/planet/disasterdata/nepal-flash-flood-2026-08-26](https://source.coop/planet/disasterdata/nepal-flash-flood-2026-08-26), CC-BY-NC-4.0) — pre-event (27 May 2026) and post-event (26 Aug 2026, heavily cloud-obscured) scenes, with nodata/cloud padding keyed transparent client-side so the mosaic doesn't show hard white seams.
- Flood extent: fetches `docs/data/flood_extent.geojson`. That file doesn't exist yet (no post-event scene has landed) — once a real `fflood-nep detect` run produces `flood_extent.gpkg`, convert it to GeoJSON and commit it to that path; the map picks it up automatically, no code change needed.
- Independent confirmation: fetches `docs/data/ems_activation.json`, a static snapshot of the Copernicus EMS EMSR927 activation (its API isn't CORS-open, unlike the other sources above) refreshed by re-running `fflood-nep ems`; the NRSC/ISRO and Planet cards next to it are static citations, not fetched at all.
- Event timeline: fetches `docs/data/timeline.json`, a dated, sourced log of new developments about the event. Unlike EMS, there's no single API to poll for "what's new" — entries are drafted by hand (usually a scheduled Claude session check-in that re-checks the sources above and searches for fresh reporting) and appended with `fflood-nep timeline add --date ... --category {casualty,cause,imagery,activation,recovery,gauge,other} --headline "..." --body "..." --source "Label|https://..."` (repeatable `--source`). Each session's scheduled check-in is bounded by that session's lifetime and a 7-day cron auto-expiry, so this isn't a durable always-on pipeline — re-run the command by hand any time to keep it current.

Clicking any map feature opens a selection panel with its real attributes (category, name, OSM/Overture source). Basemap is [OpenFreeMap](https://openfreemap.org) (no API key). Everything is theme-aware (light/dark, including the basemap style itself), and the masthead has a manual Bright/Dark toggle alongside the OS-default behavior.

## Scope

- Area: Bhote Koshi and Trishuli corridor in Rasuwa, Nuwakot, and Dhading; `detect` clips to HOT's precise 1 km river-corridor buffer.
- Event date: 2026-08-26.
- Sensor: Sentinel-1 RTC (radiometrically calibrated, terrain-corrected gamma-naught), VV/VH.
- Method: backscatter drop between pre- and post-event passes (threshold configurable via `--threshold-db`), permanent water masked out via ESA WorldCover.
- Next stage (out of scope here): a standing supraglacial-lake monitoring/early-warning pass — the systemic gap this event exposed upstream of the flood itself.

## Safety and interpretation

Outputs are for situational mapping and research until independently validated. SAR shadow, layover, steep terrain, sediment, vegetation, and river morphology can create false positives. The exposure summary depends on OpenStreetMap coverage, which reflects volunteer mapping activity and is not exhaustive. Do not use this project as the sole basis for evacuation or rescue decisions.

Flood inundation near Rasuwa has already been independently confirmed by optical satellite imagery — India's NRSC/ISRO published a pre/post comparison (Sentinel-2, 24 Aug vs. Resourcesat-2A AWiFS, 26 Aug) showing visible inundation along the Trishuli River. This project's own SAR-based flood extent is complementary to that, not the first evidence of the event. As of 26 Aug 2026 the triggering mechanism is still actively disputed: an ice/snow-rock avalanche blocking the Lhende River (possibly set off by a M4.4 earthquake at 08:37 local time, ~47 km north of Gosainkunda) and a glacial lake outburst from the Puripu Glacier are both live hypotheses — treat either as preliminary until a detailed assessment is published.
