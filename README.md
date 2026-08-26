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
- **A Planetary Computer subscription key is *not* required to start.** `sentinel-1-rtc` is flagged `msft:requires_account: true` in its own STAC metadata, but empirically this project's live runs work fine with no key set at all — a key only raises Planetary Computer's rate limits. Only chase one (https://planetarycomputer.developer.azure-api.net/, then `export PC_SDK_SUBSCRIPTION_KEY=...`) if repeated runs start hitting `429` errors; as of late 2025 the self-service key portal has reportedly been unreliable, possibly shifting toward a paid "Planetary Computer Pro" tier, so don't block on it.

```bash
fflood-nep detect --config config/rasuwa-2026-08-26.toml --output-dir outputs/detect
```

If no post-event Sentinel-1 scene exists yet for the corridor (likely for the first hours/days after the event, given Sentinel-1 revisit time), `detect` writes a `detection_report.json` with `status: "waiting_for_post_event_scene"` instead of failing — just re-run it later. Once both scenes are available, it writes:

- `flood_mask.tif` — a COG flood/no-flood raster, clipped to the HOT AOI and masked against permanent water.
- `flood_extent.gpkg` — flood polygons with `area_m2` and a per-polygon `confidence` score (mean backscatter drop).
- `exposure_summary.json` — buildings/roads/bridges/health/education facilities affected, in total and broken down by municipality (`--no-exposure` to skip; ward-level breakdown isn't available since HOT's export leaves that field empty for this AOI).
- `detection_report.json` — scenes used, parameters, a `preview` section (browser-viewable PNG/tile links for the raw pre/post SAR scenes, hosted by Planetary Computer's `/data` API — open `preview.pre_event.png` in any browser, no GIS software needed), a `river_gauges` snapshot (see below), and the caveats below. `preview` is populated as soon as a scene is found, even before both pre/post are available.

`detection_report.json` also embeds the latest DHM river-gauge readings for the corridor, pulled from a community-maintained mirror (https://github.com/nirajbhusal/rasuwa-flood-bulletin) rather than SAR imagery, so it's available even while `detect` is still waiting on a post-event scene (`--no-gauge` to skip). **Check each station's `washed`/`silent` flags before treating `level_m` as current** — a washed-out gauge keeps reporting its last reading before failing, which can look like an active alert when it isn't.

## Web UI

**Live at https://dbishal13.github.io/fflood-nep/** — an interactive map dashboard ("Corridor Watch") built from this project's data sources, served as a static site from `docs/` via GitHub Pages.

It's a single static HTML/CSS/JS page (MapLibre GL JS + the PMTiles protocol plugin, both from CDN — no build step) with **no backend and no scheduled refresh job**, because every data source it uses turned out to be CORS-open and directly fetchable from the browser:

- The map itself: HOT's live `hot_flood_npl.pmtiles` (one combined vector layer, 47k+ features, filterable by a `category` attribute into 11 toggleable layers — buildings, roads, waterways, bridges, health/education facilities, populated places, financial services, points of interest, cultural places, airports) and its AOI boundary, fetched directly from HOT's S3 bucket on every page load.
- River gauges: fetched live from the same DHM community mirror `detect` uses.
- The SAR panel: runs the same STAC search as `pc_client.find_best_item` client-side against Planetary Computer, so it always reflects the actual latest scene, not a snapshot.
- Flood extent: fetches `docs/data/flood_extent.geojson`. That file doesn't exist yet (no post-event scene has landed) — once a real `fflood-nep detect` run produces `flood_extent.gpkg`, convert it to GeoJSON and commit it to that path; the map picks it up automatically, no code change needed.

Clicking any map feature opens a selection panel with its real attributes (category, name, OSM/Overture source). Basemap is [OpenFreeMap](https://openfreemap.org) (no API key). Everything is theme-aware (light/dark, including the basemap style itself).

## Scope

- Area: Bhote Koshi and Trishuli corridor in Rasuwa, Nuwakot, and Dhading; `detect` clips to HOT's precise 1 km river-corridor buffer.
- Event date: 2026-08-26.
- Sensor: Sentinel-1 RTC (radiometrically calibrated, terrain-corrected gamma-naught), VV/VH.
- Method: backscatter drop between pre- and post-event passes (threshold configurable via `--threshold-db`), permanent water masked out via ESA WorldCover.
- Next stage (out of scope here): a standing supraglacial-lake monitoring/early-warning pass — the systemic gap this event exposed upstream of the flood itself.

## Safety and interpretation

Outputs are for situational mapping and research until independently validated. SAR shadow, layover, steep terrain, sediment, vegetation, and river morphology can create false positives. The exposure summary depends on OpenStreetMap coverage, which reflects volunteer mapping activity and is not exhaustive. Do not use this project as the sole basis for evacuation or rescue decisions.

Flood inundation near Rasuwa has already been independently confirmed by optical satellite imagery — India's NRSC/ISRO published a pre/post comparison (Sentinel-2, 24 Aug vs. Resourcesat-2A AWiFS, 26 Aug) showing visible inundation along the Trishuli River. This project's own SAR-based flood extent is complementary to that, not the first evidence of the event. As of 26 Aug 2026 the triggering mechanism is still actively disputed: an ice/snow-rock avalanche blocking the Lhende River (possibly set off by a M4.4 earthquake at 08:37 local time, ~47 km north of Gosainkunda) and a glacial lake outburst from the Puripu Glacier are both live hypotheses — treat either as preliminary until a detailed assessment is published.
