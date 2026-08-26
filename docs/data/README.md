Reserved for `flood_extent.geojson` — the web UI (`docs/index.html`) fetches this path directly.

It doesn't exist yet: no post-event Sentinel-1 scene has landed, so no real flood-extent output exists. Once one does, convert `outputs/detect/flood_extent.gpkg` to GeoJSON (e.g. `ogr2ogr -f GeoJSON docs/data/flood_extent.geojson outputs/detect/flood_extent.gpkg`) and commit it here — the map picks it up automatically.
