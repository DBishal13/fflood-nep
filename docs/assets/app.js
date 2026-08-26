"use strict";

// ---- constants (mirror config/rasuwa-2026-08-26.toml) ----
const AOI_BBOX = [85.10, 27.85, 85.75, 28.45];
const PRE_WINDOW = ["2026-08-01T00:00:00Z", "2026-08-25T23:59:59Z"];
const POST_WINDOW = ["2026-08-26T00:00:00Z", "2026-09-05T23:59:59Z"];

const HOT_PMTILES_URL = "https://production-raw-data-api.s3.amazonaws.com/ISO3/NPL/combined/hot_flood_npl.pmtiles";
const HOT_AOI_URL = "https://production-raw-data-api.s3.amazonaws.com/ISO3/NPL/combined/hot_flood_npl_aoi.geojson";
const GAUGE_URL = "https://raw.githubusercontent.com/nirajbhusal/rasuwa-flood-bulletin/main/dhm-rivers.json";
const PC_STAC_SEARCH_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search";

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
}
buildLegend();

function applyLegendVisibility() {
  document.querySelectorAll("#legendList .legend-item").forEach((item, i) => {
    if (item.querySelector("input").checked) return;
    const cat = CATEGORIES[i];
    ["fill-" + cat.key, "line-" + cat.key, "circle-" + cat.key].forEach((id) => {
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", "none");
    });
  });
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

document.getElementById("sarReset").addEventListener("click", () => {
  sarMap.fitBounds(sarImageBounds || AOI_BBOX, { padding: 24, duration: 400 });
});

function showScene(item, label, bbox) {
  const caption = document.getElementById("radarCaption");
  const loading = document.getElementById("radarLoading");
  const url = previewUrl(item, bbox, 1024);

  if (!url) {
    loading.textContent = "No preview asset on this item.";
    loading.style.display = "flex";
    return;
  }
  loading.style.display = "none";

  // image source coordinates: top-left, top-right, bottom-right, bottom-left, in [lon, lat]
  const [minx, miny, maxx, maxy] = bbox;
  const coords = [[minx, maxy], [maxx, maxy], [maxx, miny], [minx, miny]];

  const applySource = () => {
    if (sarMap.getSource("sar-image")) {
      sarMap.getSource("sar-image").updateImage({ url, coordinates: coords });
    } else {
      sarMap.addSource("sar-image", { type: "image", url, coordinates: coords });
      sarMap.addLayer({ id: "sar-image-layer", type: "raster", source: "sar-image" });
      sarMap.addSource("sar-aoi", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      sarMap.addLayer({
        id: "sar-aoi-line", type: "line", source: "sar-aoi",
        paint: { "line-color": cssVar("--select"), "line-width": 2.5 },
      });
      loadAoiGeojsonOnce().then((geojson) => { if (geojson) sarMap.getSource("sar-aoi").setData(geojson); });
    }
    if (!sarMapFitted) {
      sarMap.fitBounds(bbox, { padding: 24, duration: 0 });
      sarMapFitted = true;
    }
  };
  if (sarMap.isStyleLoaded()) applySource();
  else sarMap.once("load", applySource);
  sarImageBounds = bbox;

  const dt = item.properties && item.properties.datetime;
  caption.innerHTML =
    "Sentinel‑1 RTC composite (" + label.replace("_", "-") + ") — scroll or drag to inspect; outline shows the exact HOT AOI boundary · " +
    '<span class="mono">' + item.id + (dt ? " · " + dt : "") + "</span>";
}

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

function loadConfirmations() {
  const grid = document.getElementById("confirmationGrid");
  grid.innerHTML = "";
  grid.appendChild(nrscCard());
  fetch("data/ems_activation.json")
    .then((r) => (r.ok ? r.json() : null))
    .catch(() => null)
    .then((snapshot) => grid.appendChild(emsCard(snapshot)));
}

// ==================== INIT ====================

loadGauges();
loadSar();
loadConfirmations();
checkFloodExtent();
