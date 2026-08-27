"use strict";

// ---- constants (mirror config/rasuwa-2026-08-26.toml) ----
const AOI_BBOX = [85.02, 27.81, 85.42, 28.32];
const PRE_WINDOW = ["2026-08-01T00:00:00Z", "2026-08-25T23:59:59Z"];
const POST_WINDOW = ["2026-08-26T00:00:00Z", "2026-09-05T23:59:59Z"];

const HOT_PMTILES_URL = "https://production-raw-data-api.s3.amazonaws.com/ISO3/NPL/combined/hot_flood_npl.pmtiles";
const HOT_AOI_URL = "https://production-raw-data-api.s3.amazonaws.com/ISO3/NPL/combined/hot_flood_npl_aoi.geojson";
const GAUGE_URL = "https://raw.githubusercontent.com/nirajbhusal/rasuwa-flood-bulletin/main/dhm-rivers.json";
const PC_STAC_SEARCH_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search";
const WORLDCOVER_COLLECTION = "esa-worldcover";

// Planet Crisis Response's open STAC catalog for this exact event (CC-BY-NC-4.0, CORS-open):
// https://source.coop/planet/disasterdata/nepal-flash-flood-2026-08-26 -- PlanetScope strips
// (3.8m) that together mosaic the whole corridor. Hardcoded (not a live search) since this is a
// fixed, one-time archive for this specific event, not a growing collection like Planetary
// Computer's. Post-event coverage is 62-93% cloud -- shown anyway (chroma-keyed transparent, see
// planetThumbTransparent()) since even the gaps between clouds are informative, but it's exactly
// why this project's actual flood-extent detection relies on SAR, not this.
const PLANET_CATALOG_URL = "https://source.coop/planet/disasterdata/nepal-flash-flood-2026-08-26";
function planetThumbUrl(datePath, id) {
  return "https://data.source.coop/planet/disasterdata/nepal-flash-flood-2026-08-26/" + datePath + "/items/" + id + "/" + id + "_thumbnail.png";
}
const PLANET_PRE_ITEMS = [
  { id: "20260527_053217_72_254a", bbox: [85.137258, 28.358813, 85.502374, 28.591129] },
  { id: "20260527_053219_95_254a", bbox: [85.104325, 28.218406, 85.471358, 28.450563] },
  { id: "20260527_053221_96_254a", bbox: [85.071481, 28.076754, 85.437198, 28.308877] },
  { id: "20260527_053224_18_254a", bbox: [85.038954, 27.935221, 85.404155, 28.168685] },
  { id: "20260527_053226_41_254a", bbox: [85.006582, 27.794806, 85.373119, 28.028221] },
].map((it) => ({ ...it, thumb: planetThumbUrl("pre-event/2026-05-27", it.id) }));
const PLANET_POST_ITEMS = [
  { id: "20260826_050125_99_255f", bbox: [85.032198, 28.418252, 85.412170, 28.659454] },
  { id: "20260826_050128_33_255f", bbox: [84.997158, 28.271094, 85.377746, 28.512441] },
  { id: "20260826_050130_66_255f", bbox: [84.963054, 28.123263, 85.345506, 28.365422] },
  { id: "20260826_050133_00_255f", bbox: [84.929006, 27.976294, 85.310602, 28.218324] },
  { id: "20260826_050135_34_255f", bbox: [84.894307, 27.829256, 85.275845, 28.071583] },
].map((it) => ({ ...it, thumb: planetThumbUrl("post-event/2026-08-26", it.id) }));

const CATEGORIES = [
  { key: "buildings", label: "Buildings" },
  { key: "roads", label: "Roads" },
  { key: "waterways", label: "Waterways" },
  { key: "bridges", label: "Bridges" },
  { key: "populated_places", label: "Populated places" },
  { key: "health_facilities", label: "Health facilities" },
  { key: "education_facilities", label: "Education facilities" },
  { key: "financial_services", label: "Financial services" },
  { key: "points_of_interest", label: "Points of interest" },
  { key: "cultural_places", label: "Cultural places" },
  { key: "airports", label: "Airports" },
];

const cs = getComputedStyle(document.documentElement);
const cssVar = (name) => cs.getPropertyValue(name).trim();
const catColor = (key) => cssVar("--cat-" + key) || cssVar("--text-dim");

const liveStatusEl = document.getElementById("liveStatus");
const statusParts = { map: "loading", gauges: "loading", sar: "loading" };
function updateLiveStatus() {
  const failed = Object.values(statusParts).filter((s) => s === "error").length;
  const loading = Object.values(statusParts).filter((s) => s === "loading").length;
  if (loading > 0) liveStatusEl.textContent = "Loading live data…";
  else if (failed === 0) liveStatusEl.textContent = "All live sources connected";
  else liveStatusEl.textContent = failed + " of 3 live sources unavailable";
}

// ==================== THEME ====================

const THEME_KEY = "fflood-theme";

const isDarkTheme = () =>
  document.documentElement.getAttribute("data-theme") === "dark" ||
  (document.documentElement.getAttribute("data-theme") !== "light" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches);
const basemapStyle = () => "https://tiles.openfreemap.org/styles/" + (isDarkTheme() ? "dark" : "liberty");

function setThemeToggleActive() {
  const dark = isDarkTheme();
  document.getElementById("lightBtn").classList.toggle("active", !dark);
  document.getElementById("darkBtn").classList.toggle("active", dark);
}

function setTheme(pref) {
  document.documentElement.setAttribute("data-theme", pref);
  try { localStorage.setItem(THEME_KEY, pref); } catch (e) {}
  setThemeToggleActive();
  restyleMap();
  if (sarMap.getLayer("sar-aoi-line")) sarMap.setPaintProperty("sar-aoi-line", "line-color", cssVar("--select"));
}

document.getElementById("lightBtn").addEventListener("click", () => setTheme("light"));
document.getElementById("darkBtn").addEventListener("click", () => setTheme("dark"));
setThemeToggleActive();

// ==================== MAP ====================

let protocol = new pmtiles.Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);

const map = new maplibregl.Map({
  container: "map",
  style: basemapStyle(),
  center: [(AOI_BBOX[0] + AOI_BBOX[2]) / 2, (AOI_BBOX[1] + AOI_BBOX[3]) / 2],
  zoom: 10.2,
  attributionControl: { compact: true },
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
window.map = map; // for console/devtools inspection

document.getElementById("mapReset").addEventListener("click", () => {
  map.fitBounds(AOI_BBOX, { padding: 30, duration: 500 });
});

const interactiveLayerIds = [];

function addCategoryLayers(map, catKey) {
  const color = catColor(catKey);
  const src = "hot";
  const layer = "hot_flood_npl";

  const fillId = "fill-" + catKey;
  const lineId = "line-" + catKey;
  const circleId = "circle-" + catKey;

  map.addLayer({
    id: fillId, type: "fill", source: src, "source-layer": layer,
    filter: ["all", ["==", ["get", "category"], catKey], ["==", ["geometry-type"], "Polygon"]],
    paint: { "fill-color": color, "fill-opacity": catKey === "buildings" ? 0.55 : catKey === "waterways" ? 0.35 : 0.16 },
  });
  map.addLayer({
    id: lineId, type: "line", source: src, "source-layer": layer,
    filter: ["all", ["==", ["get", "category"], catKey], ["==", ["geometry-type"], "LineString"]],
    paint: {
      "line-color": color,
      "line-width": catKey === "bridges" ? 3 : catKey === "waterways" ? 2 : catKey === "roads" ? 1.2 : 1,
      "line-dasharray": catKey === "bridges" ? [1, 1] : [1, 0],
    },
  });
  map.addLayer({
    id: circleId, type: "circle", source: src, "source-layer": layer,
    filter: ["all", ["==", ["get", "category"], catKey], ["==", ["geometry-type"], "Point"]],
    paint: {
      "circle-color": color,
      "circle-radius": catKey === "buildings" ? 2 : 4,
      "circle-stroke-width": 1,
      "circle-stroke-color": cssVar("--surface"),
    },
  });

  interactiveLayerIds.push(fillId, lineId, circleId);
  return [fillId, lineId, circleId];
}

let lastAoiGeojson = null;
let lastSelectedFeature = null;
let lastFloodExtentGeojson = null;

function buildLegend() {
  const legendList = document.getElementById("legendList");
  CATEGORIES.forEach((cat) => {
    const ids = ["fill-" + cat.key, "line-" + cat.key, "circle-" + cat.key];
    const item = document.createElement("label");
    item.className = "legend-item";
    item.dataset.cat = cat.key;
    item.innerHTML =
      '<input type="checkbox" checked>' +
      '<span class="legend-swatch" style="background:var(--cat-' + cat.key + ');"></span>' +
      "<span>" + cat.label + "</span>" +
      '<span class="legend-count"></span>';
    const checkbox = item.querySelector("input");
    checkbox.addEventListener("change", () => {
      const vis = checkbox.checked ? "visible" : "none";
      ids.forEach((id) => { if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", vis); });
      item.classList.toggle("off", !checkbox.checked);
    });
    legendList.appendChild(item);
  });

  const aoiItem = document.createElement("label");
  aoiItem.className = "legend-item";
  aoiItem.innerHTML =
    '<input type="checkbox" id="aoiToggle" checked>' +
    '<span class="legend-swatch" style="background:var(--text-dim);"></span>' +
    "<span>AOI boundary</span>" +
    '<span class="legend-count"></span>';
  const aoiCheckbox = aoiItem.querySelector("input");
  aoiCheckbox.addEventListener("change", () => {
    const vis = aoiCheckbox.checked ? "visible" : "none";
    ["aoi-fill", "aoi-line"].forEach((id) => { if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", vis); });
    aoiItem.classList.toggle("off", !aoiCheckbox.checked);
  });
  legendList.appendChild(aoiItem);
}
buildLegend();

function applyLegendVisibility() {
  document.querySelectorAll("#legendList .legend-item[data-cat]").forEach((item) => {
    if (item.querySelector("input").checked) return;
    const cat = item.dataset.cat;
    ["fill-" + cat, "line-" + cat, "circle-" + cat].forEach((id) => {
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", "none");
    });
  });
  const aoiCheckbox = document.getElementById("aoiToggle");
  if (aoiCheckbox && !aoiCheckbox.checked) {
    ["aoi-fill", "aoi-line"].forEach((id) => { if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", "none"); });
  }
}

// (Re-)adds every data-driven source/layer, restoring selection/AOI/flood-extent state. Called on
// initial load AND after every restyleMap() theme switch, since map.setStyle() wipes all custom
// sources/layers (the camera position survives setStyle() on its own).
function setupMapLayers() {
  interactiveLayerIds.length = 0;

  map.addSource("hot", { type: "vector", url: "pmtiles://" + HOT_PMTILES_URL });
  map.addSource("aoi", { type: "geojson", data: lastAoiGeojson || { type: "FeatureCollection", features: [] } });
  map.addLayer({ id: "aoi-fill", type: "fill", source: "aoi", paint: { "fill-color": cssVar("--text-dim"), "fill-opacity": 0.04 } });
  map.addLayer({
    id: "aoi-line", type: "line", source: "aoi",
    paint: { "line-color": cssVar("--text-dim"), "line-width": 1.5, "line-dasharray": [3, 2] },
  });

  CATEGORIES.forEach((cat) => addCategoryLayers(map, cat.key));
  applyLegendVisibility();

  ensureHighlightLayer();
  if (lastSelectedFeature) map.getSource("selected").setData({ type: "FeatureCollection", features: [lastSelectedFeature] });

  if (lastFloodExtentGeojson) addFloodExtentLayer(lastFloodExtentGeojson);
}

function restyleMap() {
  // "style.load" doesn't re-fire on setStyle() in this MapLibre build -- "idle" reliably does,
  // once the new base style has finished loading.
  map.setStyle(basemapStyle());
  map.once("idle", setupMapLayers);
}

map.on("load", () => {
  setupMapLayers();

  loadAoiGeojsonOnce()
    .then((geojson) => {
      if (!geojson) throw new Error("aoi fetch failed");
      lastAoiGeojson = geojson;
      map.getSource("aoi").setData(geojson);
      statusParts.map = "ok";
      updateLiveStatus();
    })
    .catch(() => { statusParts.map = "error"; updateLiveStatus(); });

  map.fitBounds(AOI_BBOX, { padding: 30, duration: 0 });

  map.on("mousemove", (e) => {
    const feats = map.queryRenderedFeatures(e.point, { layers: interactiveLayerIds });
    map.getCanvas().style.cursor = feats.length ? "pointer" : "";
  });

  map.on("click", (e) => {
    const features = map.queryRenderedFeatures(e.point, { layers: interactiveLayerIds });
    if (!features.length) {
      clearSelection();
      return;
    }
    selectFeature(features[0]);
  });
});

// selection highlight via a dedicated geojson source.
// Uses a light halo + a saturated --select color (distinct from every category color) rather than
// --accent, since --accent equals the waterways category color and would be invisible selecting a river.
function ensureHighlightLayer() {
  if (map.getSource("selected")) return;
  map.addSource("selected", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  const isPoly = ["==", ["geometry-type"], "Polygon"];
  const isLineOrPoly = ["in", ["geometry-type"], ["literal", ["Polygon", "LineString"]]];
  const isPoint = ["==", ["geometry-type"], "Point"];

  map.addLayer({ id: "selected-fill", type: "fill", source: "selected", filter: isPoly, paint: { "fill-color": cssVar("--select"), "fill-opacity": 0.16 } });
  map.addLayer({ id: "selected-halo", type: "line", source: "selected", filter: isLineOrPoly, paint: { "line-color": cssVar("--surface"), "line-width": 6, "line-opacity": 0.9 } });
  map.addLayer({ id: "selected-line", type: "line", source: "selected", filter: isLineOrPoly, paint: { "line-color": cssVar("--select"), "line-width": 3 } });
  map.addLayer({ id: "selected-circle-halo", type: "circle", source: "selected", filter: isPoint, paint: { "circle-radius": 10, "circle-color": "transparent", "circle-stroke-color": cssVar("--surface"), "circle-stroke-width": 5 } });
  map.addLayer({ id: "selected-circle", type: "circle", source: "selected", filter: isPoint, paint: { "circle-radius": 7, "circle-color": "transparent", "circle-stroke-color": cssVar("--select"), "circle-stroke-width": 3 } });
}

function selectFeature(feature) {
  lastSelectedFeature = feature;
  ensureHighlightLayer();
  map.getSource("selected").setData({ type: "FeatureCollection", features: [feature] });

  const p = feature.properties || {};
  const cat = CATEGORIES.find((c) => c.key === p.category);
  const label = cat ? cat.label : (p.category || "Unknown");
  const rows = [
    ["Category", '<span class="inspector-cat-badge"><span class="inspector-cat-dot" style="background:' + catColor(p.category) + ';"></span>' + label + "</span>"],
    ["Name", p.name && p.name !== "nan" ? p.name : "—"],
    ["Source", p.source ? p.source.toUpperCase() : "—"],
    ["Geometry", feature.geometry.type],
  ];
  document.getElementById("inspector").innerHTML =
    '<dl style="margin:0;">' +
    rows.map(([k, v]) => '<div class="inspector-row"><dt>' + k + "</dt><dd>" + v + "</dd></div>").join("") +
    "</dl>";
}

function clearSelection() {
  lastSelectedFeature = null;
  if (map.getSource("selected")) map.getSource("selected").setData({ type: "FeatureCollection", features: [] });
  document.getElementById("inspector").innerHTML = '<p class="inspector-empty">Click a building, road, waterway, or facility on the map to see its details here.</p>';
}

// ==================== RIVER GAUGES ====================

function loadGauges() {
  fetch(GAUGE_URL)
    .then((r) => { if (!r.ok) throw new Error("gauge fetch failed"); return r.json(); })
    .then((bulletin) => {
      renderGauges(bulletin);
      statusParts.gauges = "ok";
      updateLiveStatus();
    })
    .catch(() => {
      document.getElementById("gaugeGrid").innerHTML = '<div class="gauge-error">Could not reach the DHM gauge mirror right now — try refreshing.</div>';
      statusParts.gauges = "error";
      updateLiveStatus();
    });
}

function trendGlyph(steady) {
  if (steady === "RISING") return "▲ Rising";
  if (steady === "FALLING") return "▼ Falling";
  return "▬ Steady";
}

function renderGauges(bulletin) {
  const grid = document.getElementById("gaugeGrid");
  grid.innerHTML = "";
  (bulletin.stations || []).forEach((s) => {
    const danger = s.danger_m;
    const warning = s.warning_m;
    const scaleMax = Math.max((danger || warning * 1.5) * 1.15, s.level_m * 1.05);
    const levelPct = Math.min(100, (s.level_m / scaleMax) * 100);
    const warnPct = warning ? Math.min(100, (warning / scaleMax) * 100) : null;
    const dangerPct = danger ? Math.min(100, (danger / scaleMax) * 100) : null;

    const statusClass = s.status === "DANGER" ? "chip-danger" : (s.status || "").includes("WARNING") && s.status !== "BELOW WARNING LEVEL" ? "chip-warn" : "chip-ok";
    const isDanger = s.status === "DANGER";

    const card = document.createElement("div");
    card.className = "gcard";
    card.innerHTML =
      '<div class="gcard-top">' +
        '<div>' +
          '<div class="gcard-name">' + s.name + "</div>" +
          (s.name_np ? '<div class="gcard-np">' + s.name_np + "</div>" : "") +
          '<div class="gcard-district">' + (s.district_np || "") + "</div>" +
        "</div>" +
        '<span class="chip ' + statusClass + '">' + (s.status || "").replace("BELOW WARNING LEVEL", "Below warning").toLowerCase().replace(/^./, (c) => c.toUpperCase()) + "</span>" +
      "</div>" +
      '<div class="level-row">' +
        '<span><span class="level-value mono"' + (s.washed ? ' style="color:var(--text-faint);"' : "") + ">" + s.level_m.toFixed(2) + '</span><span class="level-unit">m</span></span>' +
        '<span class="trend">' + trendGlyph(s.steady) + "</span>" +
      "</div>" +
      '<div class="bar-track">' +
        '<div class="bar-fill' + (isDanger ? " is-danger" : "") + '" style="width:' + levelPct.toFixed(1) + '%;"></div>' +
        (warnPct !== null ? '<div class="bar-tick" style="left:' + warnPct.toFixed(1) + '%;"></div>' : "") +
        (dangerPct !== null ? '<div class="bar-tick danger-tick" style="left:' + dangerPct.toFixed(1) + '%;"></div>' : "") +
      "</div>" +
      '<div class="bar-labels"><span>0 m</span><span>' + (danger ? "Danger " + danger.toFixed(1) + " m" : "Warning " + warning.toFixed(1) + " m") + "</span></div>" +
      (s.washed
        ? '<div class="washed-flag"><span>⚠</span><span><strong>Gauge washed away</strong> — this reading is the last value before the sensor failed, not a live measurement.</span></div>'
        : "") +
      '<div class="gcard-foot">' +
        "<span>Observed <span class=\"mono\">" + (s.observed_npt || "") + " NPT</span></span>" +
        '<a href="' + s.source + '" target="_blank" rel="noopener">DHM source →</a>' +
      "</div>";
    grid.appendChild(card);
  });
}

// ==================== SAR PREVIEW (live STAC search) ====================

function stacFilter() {
  return {
    op: "and",
    args: [
      { op: "like", args: [{ property: "platform" }, "sentinel-1%"] },
      { op: "a_contains", args: [{ property: "sar:polarizations" }, ["VV", "VH"]] },
    ],
  };
}

// Retries on 429 (Planetary Computer rate limiting) and 5xx, honoring Retry-After when the
// server sends one, otherwise exponential backoff. A single transient failure shouldn't turn
// into a user-facing "SAR status unavailable".
async function fetchWithRetry(url, options, retries) {
  const statusForcelist = [429, 500, 502, 503, 504];
  for (let attempt = 0; ; attempt++) {
    const res = await fetch(url, options);
    if (res.ok || !statusForcelist.includes(res.status) || attempt >= retries) return res;
    const retryAfter = Number(res.headers.get("Retry-After"));
    const delayMs = retryAfter > 0 ? retryAfter * 1000 : 500 * Math.pow(2, attempt);
    await new Promise((resolve) => setTimeout(resolve, delayMs));
  }
}

async function searchBestItem(start, end) {
  const body = {
    collections: ["sentinel-1-rtc"],
    bbox: AOI_BBOX,
    datetime: start + "/" + end,
    limit: 20,
    "filter-lang": "cql2-json",
    filter: stacFilter(),
  };
  const res = await fetchWithRetry(PC_STAC_SEARCH_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }, 4);
  if (!res.ok) throw new Error("STAC search failed: " + res.status);
  const data = await res.json();
  const items = data.features || [];
  if (!items.length) return null;
  items.sort((a, b) => new Date(b.properties.datetime) - new Date(a.properties.datetime));
  return items[0];
}

let preItem = null, postItem = null;

async function loadSar() {
  const caption = document.getElementById("radarCaption");
  const headline = document.getElementById("detectionHeadline");
  const body = document.getElementById("detectionBody");

  try {
    [preItem, postItem] = await Promise.all([
      searchBestItem(PRE_WINDOW[0], PRE_WINDOW[1]),
      searchBestItem(POST_WINDOW[0], POST_WINDOW[1]),
    ]);

    if (preItem) showScene(preItem, "pre_event", AOI_BBOX);

    if (postItem) {
      document.getElementById("postBtn").disabled = false;
      document.getElementById("postBtn").addEventListener("click", () => {
        setActiveToggle("postBtn"); showScene(postItem, "post_event", AOI_BBOX);
      });
      document.getElementById("preBtn").addEventListener("click", () => {
        setActiveToggle("preBtn"); showScene(preItem, "pre_event", AOI_BBOX);
      });
      headline.textContent = "Post-event scene available";
      headline.style.color = "var(--accent)";
      body.textContent = "Both pre- and post-event Sentinel-1 passes are now available. Run fflood-nep detect locally to generate the flood-extent layer below.";
    } else if (preItem) {
      headline.textContent = "Awaiting post-event pass";
      body.textContent = "The event is confirmed by river gauges below, but no Sentinel-1 scene has been captured over this corridor since 26 Aug yet. This page rechecks Planetary Computer live on every load.";
    } else {
      headline.textContent = "No recent Sentinel-1 coverage found";
      body.textContent = "The live STAC search returned no scenes for the configured window — this may mean Planetary Computer is unreachable, or the search window needs adjusting.";
    }
    statusParts.sar = "ok";
  } catch (err) {
    const loading = document.getElementById("radarLoading");
    loading.textContent = "Could not reach Planetary Computer right now.";
    loading.style.display = "flex";
    headline.textContent = "SAR status unavailable";
    body.textContent = "Live search against Planetary Computer failed — try refreshing.";
    statusParts.sar = "error";
  }
  updateLiveStatus();
}

function setActiveToggle(id) {
  ["preBtn", "postBtn"].forEach((b) => document.getElementById(b).classList.toggle("active", b === id));
}

// Mirrors pc_client.preview_url: the item's rendered_preview asset points at PC's whole-scene
// /item/preview.png endpoint (mostly irrelevant terrain outside the AOI) -- swap it for the
// /item/bbox/{bbox}.png endpoint, which crops server-side, reusing the same render params.
function previewUrl(item, bbox, maxSize) {
  const preview = item.assets && item.assets.rendered_preview;
  if (!preview) return null;
  const u = new URL(preview.href);
  u.searchParams.delete("tile_format");
  u.searchParams.set("max_size", String(maxSize || 1024));
  u.pathname = "/api/data/v1/item/bbox/" + bbox.join(",") + ".png";
  return u.toString();
}

let aoiGeojsonPromise = null;
function loadAoiGeojsonOnce() {
  if (!aoiGeojsonPromise) aoiGeojsonPromise = fetch(HOT_AOI_URL).then((r) => (r.ok ? r.json() : null)).catch(() => null);
  return aoiGeojsonPromise;
}

// The SAR panel is a real (small) MapLibre map, not a static <img> -- the pre/post-event composite
// is loaded as a georeferenced `image` source pinned to its exact bbox corners, so scroll-zoom,
// drag-pan and pinch all work natively, and the AOI outline is a real vector layer instead of
// hand-projected SVG points.
const sarMap = new maplibregl.Map({
  container: "sarMap",
  style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#0a0805" } }] },
  center: [(AOI_BBOX[0] + AOI_BBOX[2]) / 2, (AOI_BBOX[1] + AOI_BBOX[3]) / 2],
  zoom: 9,
  attributionControl: false,
});
sarMap.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
window.sarMap = sarMap;

let sarImageBounds = null;
let sarMapFitted = false;
let currentSarUrl = null;
let currentLandcoverUrl = null;
let sarBaseMode = "sar";

document.getElementById("sarReset").addEventListener("click", () => {
  sarMap.fitBounds(sarImageBounds || AOI_BBOX, { padding: 24, duration: 400 });
});

// ESA WorldCover -- the same land-cover classification this project's own detect pipeline uses
// to mask permanent water (see pc_client.read_worldcover) -- as an alternative base image to the
// raw SAR backscatter composite. Backscatter alone doesn't read as terrain to most people; a real
// land-cover map (forest/grass/built-up/water) does, and it's already part of this project's logic.
let worldcoverPreviewPromise = null;
function worldcoverPreviewUrl() {
  if (!worldcoverPreviewPromise) {
    worldcoverPreviewPromise = fetch(PC_STAC_SEARCH_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ collections: [WORLDCOVER_COLLECTION], bbox: AOI_BBOX, limit: 1 }),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        const item = data && data.features && data.features[0];
        return item ? previewUrl(item, AOI_BBOX, 1024) : null;
      })
      .catch(() => null);
  }
  return worldcoverPreviewPromise;
}

// Shared by sarMap/planetMap and by each panel's swipe "back" map: the actual mapped river
// channel (HOT/OSM waterways) and the AOI corridor outline, both toggleable from the toolbar.
function addCorridorRiverLayers(targetMap, prefix) {
  targetMap.addSource(prefix + "-hot", { type: "vector", url: "pmtiles://" + HOT_PMTILES_URL });
  targetMap.addLayer({
    id: prefix + "-river-line", type: "line", source: prefix + "-hot", "source-layer": "hot_flood_npl",
    filter: ["all", ["==", ["get", "category"], "waterways"], ["==", ["geometry-type"], "LineString"]],
    paint: { "line-color": "#00E5FF", "line-width": 1.4, "line-opacity": 0.9 },
  });
  targetMap.addSource(prefix + "-aoi", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  targetMap.addLayer({
    id: prefix + "-aoi-line", type: "line", source: prefix + "-aoi",
    paint: { "line-color": cssVar("--select"), "line-width": 2.5 },
  });
  loadAoiGeojsonOnce().then((geojson) => { if (geojson) targetMap.getSource(prefix + "-aoi").setData(geojson); });
}

// Applies the panel's current Corridor/River checkbox state to a map that just had those layers
// added -- new layers default to visible regardless of what the toolbar already says.
function applyCorridorRiverToggles(targetMap, prefix, corridorCheckboxId, riverCheckboxId) {
  const corridorOn = document.getElementById(corridorCheckboxId).checked;
  const riverOn = document.getElementById(riverCheckboxId).checked;
  if (targetMap.getLayer(prefix + "-aoi-line")) targetMap.setLayoutProperty(prefix + "-aoi-line", "visibility", corridorOn ? "visible" : "none");
  if (targetMap.getLayer(prefix + "-river-line")) targetMap.setLayoutProperty(prefix + "-river-line", "visibility", riverOn ? "visible" : "none");
}

function wireCorridorRiverToggle(checkboxId, layerId, getMaps) {
  document.getElementById(checkboxId).addEventListener("change", (e) => {
    const vis = e.target.checked ? "visible" : "none";
    getMaps().forEach((m) => { if (m.getLayer(layerId)) m.setLayoutProperty(layerId, "visibility", vis); });
  });
}

const RADAR_BG_STYLE = { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#0a0805" } }] };

// Generic swipe/compare: MapLibre has no per-layer clipping (one canvas per map), so a real swipe
// needs the standard two-synced-maps technique (as in mapbox-gl-compare) -- a second "back" map
// instance, camera-synced to `frontMap`, revealed via a draggable clip-path handle on the front
// map's own container. `buildBack(backMap)` adds whatever layers represent "the other side".
function createSwipeCompare(frontMap, containerEl, buildBack) {
  const backEl = document.createElement("div");
  backEl.className = "sar-map swipe-back";
  containerEl.insertBefore(backEl, containerEl.firstChild);

  const backMap = new maplibregl.Map({
    container: backEl,
    style: RADAR_BG_STYLE,
    center: frontMap.getCenter(),
    zoom: frontMap.getZoom(),
    attributionControl: false,
    interactive: false,
  });
  backMap.once("load", () => buildBack(backMap));

  let syncing = false;
  const syncBack = () => {
    if (syncing) return;
    syncing = true;
    backMap.jumpTo({ center: frontMap.getCenter(), zoom: frontMap.getZoom(), bearing: frontMap.getBearing(), pitch: frontMap.getPitch() });
    syncing = false;
  };
  frontMap.on("move", syncBack);

  const handle = document.createElement("div");
  handle.className = "swipe-handle";
  handle.innerHTML = '<span class="swipe-handle-grip"></span>';
  containerEl.appendChild(handle);

  function setPct(pct) {
    pct = Math.max(2, Math.min(98, pct));
    handle.style.left = pct + "%";
    frontMap.getContainer().style.clipPath = "inset(0 " + (100 - pct) + "% 0 0)";
  }
  setPct(50);

  let dragging = false;
  const onDown = (e) => { dragging = true; handle.setPointerCapture(e.pointerId); };
  const onUp = () => { dragging = false; };
  const onMove = (e) => {
    if (!dragging) return;
    const rect = containerEl.getBoundingClientRect();
    setPct(((e.clientX - rect.left) / rect.width) * 100);
  };
  handle.addEventListener("pointerdown", onDown);
  window.addEventListener("pointerup", onUp);
  window.addEventListener("pointermove", onMove);

  return {
    backMap,
    destroy() {
      frontMap.off("move", syncBack);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointermove", onMove);
      frontMap.getContainer().style.clipPath = "";
      handle.remove();
      backEl.remove();
      backMap.remove();
    },
  };
}

function ensureSarLayers(url, coords) {
  sarMap.addSource("sar-image", { type: "image", url, coordinates: coords });
  sarMap.addLayer({ id: "sar-image-layer", type: "raster", source: "sar-image" });
  addCorridorRiverLayers(sarMap, "sar");
  applyCorridorRiverToggles(sarMap, "sar", "sarCorridorToggle", "sarRiverToggle");
}

function applyBaseImage() {
  const url = sarBaseMode === "sar" ? currentSarUrl : currentLandcoverUrl;
  if (!url || !sarImageBounds) return;
  const [minx, miny, maxx, maxy] = sarImageBounds;
  const coords = [[minx, maxy], [maxx, maxy], [maxx, miny], [minx, miny]];

  const apply = () => {
    if (sarMap.getSource("sar-image")) sarMap.getSource("sar-image").updateImage({ url, coordinates: coords });
    else ensureSarLayers(url, coords);
    if (!sarMapFitted) {
      sarMap.fitBounds(sarImageBounds, { padding: 24, duration: 0 });
      sarMapFitted = true;
    }
  };
  if (sarMap.isStyleLoaded()) apply();
  else sarMap.once("load", apply);
}

function setSarBaseMode(mode) {
  sarBaseMode = mode;
  document.getElementById("sarLayerBtn").classList.toggle("active", mode === "sar");
  document.getElementById("landcoverLayerBtn").classList.toggle("active", mode === "landcover");

  const legend = document.getElementById("sarLegend");
  if (mode === "sar") {
    legend.textContent = "VV+VH · 10m · sentinel-1-rtc";
    legend.title = "";
  } else {
    legend.textContent = "ESA WorldCover 10m 2021";
    legend.title = "green = tree · yellow = grass/crop · pink = built-up · blue = water · gray = bare";
  }
  applyBaseImage();
}
document.getElementById("sarLayerBtn").addEventListener("click", () => setSarBaseMode("sar"));
document.getElementById("landcoverLayerBtn").addEventListener("click", () => setSarBaseMode("landcover"));

let preSarUrl = null, postSarUrl = null;

function showScene(item, label, bbox) {
  const loading = document.getElementById("radarLoading");
  const url = previewUrl(item, bbox, 1024);

  if (!url) {
    loading.textContent = "No preview asset on this item.";
    loading.style.display = "flex";
    return;
  }
  loading.style.display = "none";

  if (label === "pre_event") preSarUrl = url; else postSarUrl = url;
  document.getElementById("sarCompareBtn").disabled = !(preSarUrl && postSarUrl);

  currentSarUrl = url;
  sarImageBounds = bbox;
  applyBaseImage();
  worldcoverPreviewUrl().then((wcUrl) => {
    currentLandcoverUrl = wcUrl;
    if (sarBaseMode === "landcover") applyBaseImage();
  });

  const dt = item.properties && item.properties.datetime;
  document.getElementById("radarCaption").innerHTML =
    "Sentinel‑1 RTC composite (" + label.replace("_", "-") + ") — scroll or drag to inspect; cyan traces the mapped " +
    "river channel, outline shows the exact HOT AOI boundary · " +
    '<span class="mono">' + item.id + (dt ? " · " + dt : "") + "</span>";
}

// ---- SAR corridor/river toggles + pre/post swipe compare ----

let sarActiveMaps = [sarMap];
wireCorridorRiverToggle("sarCorridorToggle", "sar-aoi-line", () => sarActiveMaps);
wireCorridorRiverToggle("sarRiverToggle", "sar-river-line", () => sarActiveMaps);

let sarSwipe = null;
document.getElementById("sarCompareBtn").addEventListener("click", () => {
  const btn = document.getElementById("sarCompareBtn");
  if (sarSwipe) {
    sarSwipe.destroy();
    sarSwipe = null;
    sarActiveMaps = [sarMap];
    btn.classList.remove("active");
    applyBaseImage();
    return;
  }
  if (!preSarUrl || !postSarUrl || !sarImageBounds) return;

  setSarBaseMode("sar"); // comparing land cover pre vs post is meaningless -- it's the same raster both times
  currentSarUrl = preSarUrl;
  applyBaseImage();

  const [minx, miny, maxx, maxy] = sarImageBounds;
  const coords = [[minx, maxy], [maxx, maxy], [maxx, miny], [minx, miny]];
  sarSwipe = createSwipeCompare(sarMap, document.getElementById("radarFrame"), (backMap) => {
    backMap.addSource("sar-image", { type: "image", url: postSarUrl, coordinates: coords });
    backMap.addLayer({ id: "sar-image-layer", type: "raster", source: "sar-image" });
    addCorridorRiverLayers(backMap, "sar");
    applyCorridorRiverToggles(backMap, "sar", "sarCorridorToggle", "sarRiverToggle");
    sarActiveMaps = [sarMap, backMap];
  });
  btn.classList.add("active");
});

// ==================== PLANET IMAGERY (separate panel, separate map) ====================

const planetMap = new maplibregl.Map({
  container: "planetMap",
  style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#0a0805" } }] },
  center: [(AOI_BBOX[0] + AOI_BBOX[2]) / 2, (AOI_BBOX[1] + AOI_BBOX[3]) / 2],
  zoom: 9,
  attributionControl: false,
});
planetMap.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
window.planetMap = planetMap;

document.getElementById("planetReset").addEventListener("click", () => {
  planetMap.fitBounds(AOI_BBOX, { padding: 24, duration: 400 });
});

// Each PlanetScope thumbnail carries an opaque white nodata/cloud fill that, drawn straight onto
// a MapLibre image source, shows up as ugly rectangular seams between adjacent scenes (an actual
// user-reported problem: the raw mosaic looked like stacked white index cards). Fetching as a
// blob and re-drawing through a canvas keeps the canvas untainted regardless of the source's CORS
// headers, so near-white pixels (nodata padding AND cloud, which are visually indistinguishable
// in this product) can be keyed to transparent -- neighboring tiles show through instead of a
// hard white edge, and it's a reasonable bonus that heavy post-event cloud gets "seen through"
// wherever there's a gap.
const planetTransparentCache = new Map();
async function planetThumbTransparent(url) {
  if (planetTransparentCache.has(url)) return planetTransparentCache.get(url);
  const p = (async () => {
    try {
      const resp = await fetch(url);
      const blob = await resp.blob();
      const bitmap = await createImageBitmap(blob);
      const canvas = document.createElement("canvas");
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(bitmap, 0, 0);
      const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const d = imgData.data;
      for (let i = 0; i < d.length; i += 4) {
        if (d[i] > 248 && d[i + 1] > 248 && d[i + 2] > 248) d[i + 3] = 0;
      }
      ctx.putImageData(imgData, 0, 0);
      return canvas.toDataURL("image/png");
    } catch (e) {
      return url; // fall back to the raw (opaque) thumbnail rather than showing nothing
    }
  })();
  planetTransparentCache.set(url, p);
  return p;
}

// Fetches+transparency-processes a set of Planet items and adds them as image layers on
// `targetMap`, inserted below `beforeId` if it already exists. Returns a promise of the new layer
// ids. Shared between the main phase toggle and each swipe "back" map's opposite-phase mosaic.
function buildPlanetMosaic(targetMap, items, idPrefix, beforeId) {
  return Promise.all(items.map((it) => planetThumbTransparent(it.thumb))).then((urls) => {
    const ids = items.map((it, i) => {
      const [minx, miny, maxx, maxy] = it.bbox;
      const coords = [[minx, maxy], [maxx, maxy], [maxx, miny], [minx, miny]];
      const id = idPrefix + "-" + i;
      targetMap.addSource(id, { type: "image", url: urls[i], coordinates: coords });
      targetMap.addLayer({ id, type: "raster", source: id }, targetMap.getLayer(beforeId) ? beforeId : undefined);
      return id;
    });
    return ids;
  });
}

let planetPhase = "pre";
let planetLayerIds = [];
let planetFitted = false;

async function showPlanetPhase(phase) {
  planetPhase = phase;
  document.getElementById("planetPreBtn").classList.toggle("active", phase === "pre");
  document.getElementById("planetPostBtn").classList.toggle("active", phase === "post");

  const loading = document.getElementById("planetLoading");
  loading.style.display = "flex";

  const items = phase === "pre" ? PLANET_PRE_ITEMS : PLANET_POST_ITEMS;
  const legend = document.getElementById("planetLegend");
  legend.textContent = phase === "pre" ? "27 May 2026 · 3.8m" : "26 Aug 2026 · 3.8m · heavy cloud";

  const ready = () => {
    // remove the previous phase's layers/sources before adding the new phase's
    planetLayerIds.forEach((id) => { if (planetMap.getLayer(id)) planetMap.removeLayer(id); if (planetMap.getSource(id)) planetMap.removeSource(id); });

    buildPlanetMosaic(planetMap, items, "planet-" + phase, "planet-river-line").then((ids) => {
      planetLayerIds = ids;
      loading.style.display = "none";
    });

    if (!planetMap.getSource("planet-hot")) {
      addCorridorRiverLayers(planetMap, "planet");
      applyCorridorRiverToggles(planetMap, "planet", "planetCorridorToggle", "planetRiverToggle");
    }
    if (!planetFitted) {
      planetMap.fitBounds(AOI_BBOX, { padding: 24, duration: 0 });
      planetFitted = true;
    }
  };
  if (planetMap.isStyleLoaded()) ready();
  else planetMap.once("load", ready);

  document.getElementById("planetCaption").innerHTML =
    (phase === "pre"
      ? "PlanetScope pre-event mosaic (27 May 2026, pre-monsoon baseline, 5 scenes) — terrain context, not post-event evidence."
      : "PlanetScope post-event mosaic (26 Aug 2026, 5 scenes) — 62–93% cloud cover; transparent gaps are cloud/nodata, " +
        "not flood water. This near-total cloud cover is exactly why this project's flood-extent detection uses SAR.") +
    " Cyan traces the mapped river channel, outline shows the HOT AOI boundary. Courtesy " +
    '<a href="' + PLANET_CATALOG_URL + '" target="_blank" rel="noopener">Planet Labs PBC / Planet Crisis Response Program</a>, CC-BY-NC-4.0.';
}
document.getElementById("planetPreBtn").addEventListener("click", () => showPlanetPhase("pre"));
document.getElementById("planetPostBtn").addEventListener("click", () => showPlanetPhase("post"));

// ---- Planet corridor/river toggles + pre/post swipe compare ----

let planetActiveMaps = [planetMap];
wireCorridorRiverToggle("planetCorridorToggle", "planet-aoi-line", () => planetActiveMaps);
wireCorridorRiverToggle("planetRiverToggle", "planet-river-line", () => planetActiveMaps);

let planetSwipe = null;
document.getElementById("planetCompareBtn").addEventListener("click", () => {
  const btn = document.getElementById("planetCompareBtn");
  if (planetSwipe) {
    planetSwipe.destroy();
    planetSwipe = null;
    planetActiveMaps = [planetMap];
    btn.classList.remove("active");
    return;
  }
  showPlanetPhase("pre"); // compare is always pre (front/left) vs post (back/right)
  planetSwipe = createSwipeCompare(planetMap, document.getElementById("planetFrame"), (backMap) => {
    buildPlanetMosaic(backMap, PLANET_POST_ITEMS, "planet-swipe-post", "planet-river-line");
    addCorridorRiverLayers(backMap, "planet");
    applyCorridorRiverToggles(backMap, "planet", "planetCorridorToggle", "planetRiverToggle");
    planetActiveMaps = [planetMap, backMap];
  });
  btn.classList.add("active");
});

// ==================== FLOOD EXTENT ====================

function checkFloodExtent() {
  fetch("data/flood_extent.geojson")
    .then((r) => { if (!r.ok) throw new Error("not found"); return r.json(); })
    .then((geojson) => {
      lastFloodExtentGeojson = geojson;
      document.getElementById("extentStatus").outerHTML =
        '<div class="extent-pending" style="border-style:solid; background:var(--accent-soft); border-color:var(--accent);">' +
        "<span>✓</span><span>Flood-extent layer published — " + geojson.features.length + " polygons. Rendered on the map above.</span></div>";
      map.on("load", () => addFloodExtentLayer(geojson));
      if (map.loaded()) addFloodExtentLayer(geojson);
    })
    .catch(() => {
      document.getElementById("extentStatus").innerHTML =
        '<span>⏳</span><span>Not yet published — Sentinel‑1 hasn\'t revisited the corridor since the event. Run <code class="mono">fflood-nep detect</code> and commit its output to <code class="mono">docs/data/flood_extent.geojson</code> once available.</span>';
    });
}

function addFloodExtentLayer(geojson) {
  if (map.getSource("flood-extent")) { map.getSource("flood-extent").setData(geojson); return; }
  map.addSource("flood-extent", { type: "geojson", data: geojson });
  map.addLayer({ id: "flood-extent-fill", type: "fill", source: "flood-extent", paint: { "fill-color": cssVar("--danger"), "fill-opacity": 0.35 } });
  map.addLayer({ id: "flood-extent-line", type: "line", source: "flood-extent", paint: { "line-color": cssVar("--danger"), "line-width": 1.5 } });
}

// ==================== INDEPENDENT CONFIRMATION ====================

function fmtUtc(iso) {
  if (!iso) return "unknown";
  const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  return d.toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC";
}

function nrscCard() {
  const card = document.createElement("div");
  card.className = "gcard";
  card.innerHTML =
    '<div class="gcard-top">' +
      '<div>' +
        '<div class="gcard-name">NRSC/ISRO · Resourcesat-2A AWiFS</div>' +
        '<div class="gcard-district">Optical satellite, India</div>' +
      "</div>" +
      '<span class="chip chip-ok">Confirmed inundation</span>' +
    "</div>" +
    '<div style="font-size:.8rem; color:var(--text-dim); margin:8px 0 12px; line-height:1.45;">' +
      "India's NRSC published a pre/post comparison (Sentinel‑2, 24 Aug vs. Resourcesat‑2A AWiFS, 26 Aug) showing " +
      "visible inundation along the Trishuli River — independent confirmation, outside this project's own SAR pipeline. " +
      "No stable public URL for that specific product was found; linked below is NRSC's general disaster-mapping portal." +
    "</div>" +
    '<div class="gcard-foot">' +
      "<span>Cited 26 Aug 2026</span>" +
      '<a href="https://bhuvan-app1.nrsc.gov.in/bhuvandisaster/" target="_blank" rel="noopener">NRSC DMSG portal →</a>' +
    "</div>";
  return card;
}

function emsCard(snapshot) {
  const card = document.createElement("div");
  card.className = "gcard";
  if (!snapshot || !snapshot.activation) {
    card.innerHTML =
      '<div class="gcard-top"><div><div class="gcard-name">Copernicus EMS · EMSR927</div>' +
      '<div class="gcard-district">Flood in Nepal</div></div><span class="chip chip-warn">Snapshot unavailable</span></div>' +
      '<div style="font-size:.8rem; color:var(--text-dim); margin-top:8px;">' +
      "This project reads a periodically-refreshed static snapshot of the activation (its backend API isn't " +
      "CORS-open for a live browser fetch) — <code class=\"mono\">docs/data/ems_activation.json</code> hasn't been generated yet. " +
      'Run <code class="mono">fflood-nep ems</code> to publish it.</div>';
    return card;
  }
  const a = snapshot.activation;
  const delivered = a.products.some((p) => p.download_path);
  const statusChip = delivered ? '<span class="chip chip-ok">Products delivered</span>' : '<span class="chip chip-warn">Awaiting delivery</span>';
  const rows = a.products
    .map((p) => "<dt>" + p.aoi_name + "</dt><dd class=\"mono\">" + (p.sensors || []).join("/") + " · " + (p.download_path ? "Delivered" : "Waiting") + " · exp. " + fmtUtc(p.expected_delivery) + "</dd>")
    .join("");
  card.innerHTML =
    '<div class="gcard-top">' +
      '<div>' +
        '<div class="gcard-name">Copernicus EMS · ' + a.code + "</div>" +
        '<div class="gcard-district">' + a.name + " · " + (a.sub_category || a.category) + "</div>" +
      "</div>" + statusChip +
    "</div>" +
    '<div style="font-size:.8rem; color:var(--text-dim); margin:8px 0 12px; line-height:1.45;">' +
      "EU-authorised rapid-mapping activation, requested " + fmtUtc(a.activation_time) + ". Its own activation reason " +
      'cites a GLOF as the trigger — one more input to the still-disputed cause debate.' +
    "</div>" +
    '<dl class="kv-grid" style="border-top:none; padding-top:0; font-size:.74rem;">' + rows + "</dl>" +
    '<div class="gcard-foot">' +
      "<span>" + (delivered ? "Products available" : "Not yet delivered") + "</span>" +
      '<a href="' + a.activation_page + '" target="_blank" rel="noopener">Activation page →</a>' +
    "</div>";
  return card;
}

function planetCard() {
  const card = document.createElement("div");
  card.className = "gcard";
  card.innerHTML =
    '<div class="gcard-top">' +
      '<div>' +
        '<div class="gcard-name">Planet Crisis Response · PlanetScope</div>' +
        '<div class="gcard-district">3.8m optical, 14 scenes · CC-BY-NC-4.0</div>' +
      "</div>" +
      '<span class="chip chip-ok">Open STAC catalog</span>' +
    "</div>" +
    '<div style="font-size:.8rem; color:var(--text-dim); margin:8px 0 12px; line-height:1.45;">' +
      "Planet published a dedicated STAC catalog for this event: 5 pre-event scenes (27 May 2026, pre-monsoon " +
      "baseline) and 9 post-event scenes (26 Aug 2026), both mosaicked in the Planet imagery section below -- " +
      "though the post-event imagery is 62–93% cloud-obscured, which is itself why this project relies on radar. Its own " +
      "catalog description cites an ice/rock avalanche from an upper-catchment glacier as the preliminary trigger, " +
      "with the cause still under investigation and casualty figures still provisional at time of release." +
    "</div>" +
    '<div class="gcard-foot">' +
      "<span>Cited 26 Aug 2026</span>" +
      '<a href="' + PLANET_CATALOG_URL + '" target="_blank" rel="noopener">Source Cooperative catalog →</a>' +
    "</div>";
  return card;
}

function loadConfirmations() {
  const grid = document.getElementById("confirmationGrid");
  grid.innerHTML = "";
  grid.appendChild(nrscCard());
  grid.appendChild(planetCard());
  fetch("data/ems_activation.json")
    .then((r) => (r.ok ? r.json() : null))
    .catch(() => null)
    .then((snapshot) => grid.appendChild(emsCard(snapshot)));
}

// ==================== EVENT TIMELINE ====================
// Reads docs/data/timeline.json -- entries drafted by hand (usually a scheduled research check-in,
// see fflood_nep.timeline.add_entry) as new developments about the event surface, not a live feed.

const TIMELINE_CHIP = {
  casualty: ["chip-danger", "Casualty"],
  cause: ["chip-warn", "Cause"],
  imagery: ["chip-accent", "Imagery"],
  activation: ["chip-accent", "Activation"],
  recovery: ["chip-ok", "Recovery"],
  gauge: ["chip-neutral", "Gauge"],
  other: ["chip-neutral", "Update"],
};

function timelineItem(entry) {
  const [chipClass, chipLabel] = TIMELINE_CHIP[entry.category] || TIMELINE_CHIP.other;
  const sources = (entry.sources || [])
    .map((s) => '<a href="' + s.url + '" target="_blank" rel="noopener">' + s.label + " →</a>")
    .join("");
  const div = document.createElement("div");
  div.className = "timeline-item";
  div.innerHTML =
    '<span class="timeline-dot"></span>' +
    '<div class="timeline-meta">' +
      '<span class="mono timeline-date">' + fmtUtc(entry.date) + "</span>" +
      '<span class="chip ' + chipClass + '">' + chipLabel + "</span>" +
    "</div>" +
    '<div class="timeline-headline">' + entry.headline + "</div>" +
    '<p class="timeline-body">' + entry.body + "</p>" +
    '<div class="timeline-sources">' + sources + "</div>";
  return div;
}

function loadTimeline() {
  const list = document.getElementById("timelineList");
  fetch("data/timeline.json")
    .then((r) => (r.ok ? r.json() : null))
    .then((payload) => {
      const entries = (payload && payload.entries) || [];
      list.innerHTML = "";
      if (!entries.length) {
        list.innerHTML = '<p class="inspector-empty">No timeline entries yet.</p>';
        return;
      }
      entries.forEach((entry) => list.appendChild(timelineItem(entry)));
    })
    .catch(() => {
      list.innerHTML = '<p class="inspector-empty">Could not load the timeline right now — try refreshing.</p>';
    });
}

// ==================== INIT ====================

loadGauges();
loadSar();
loadConfirmations();
loadTimeline();
checkFloodExtent();
showPlanetPhase("pre");
