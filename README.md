# RTTR Operations Course Map

Single-file operations course map for **Race Thru The Redwoods**, a 10K trail
run starting and finishing at Roaring Camp Railroads and running through Henry
Cowell Redwoods State Park.

The sheet deliberately carries no year and no date, so the same file can be
reused next year by updating markers alone. Set `DATA.meta.date` if a dated
edition is ever wanted; the title block draws it only when it is non-empty.

One file produces two outputs:

| Preset | Sheet | Theme | Purpose |
| --- | --- | --- | --- |
| `volunteer` | 8.5 × 11 | mono + outlined shapes | ~20 black-and-white handouts, legible at 7am in dappled light |
| `poster` | 24 × 36 | forest + emoji | one colour copy at the start/finish area |

## Using it

Open `rttr_course_map.html` in a browser. No build step, no server, no network
needed at runtime — it opens from a laptop with no wifi.

Pick a preset in the sidebar, adjust layers if you need to, then
**Print / Save as PDF** with margins set to *None* and *Background graphics* on.

## Editing it

Everything you edit lives in the `DATA` object at the top of the `<script>`
block — course track, markers, trail names, the volunteer brief panel, emoji
glyphs. The rendering engine below it should not need touching.

To place a marker, tick **Click map to capture lat/lon** in the sidebar and
click the map; the sidebar emits a pre-formatted `DATA.markers` line.

## Course facts

Verified against the baked-in track — don't re-derive:

- 450 track points, **6.28 mi / 10.11 km**, **907 ft gain**, high point 797 ft
- Start and finish are **105 m apart**, not coincident — two flags, not one
- Track and per-point elevation are baked into `DATA.track` / `DATA.ele`;
  `RTTR-10k-course.gpx` is kept only for re-import

## Layout

| Path | What |
| --- | --- |
| `rttr_course_map.html` | the deliverable — self-contained, no dependencies |
| `RTTR-10k-course.gpx` | source Strava export, for re-import only |
| `CLAUDE_CODE_PROMPT.md` | design constraints and task backlog |
| `scripts/` | re-runnable helpers (OSM trail pull, render proofs) |
| `render/` | rendered PNG/PDF proofs — build output, not committed |

## Constraints

- Stays a **single self-contained HTML file**. No build step, no runtime network
  dependency, no map tiles — the map is inline SVG from a Web Mercator
  projection of the GPX track.
- **Separate from the live race website.** The RTTR site keeps its existing
  Leaflet map on `course_info.html`; nothing here touches it.

## Data sources

- **Trails** — the [California State Parks trail layer][csp] for unit 418
  (Henry Cowell Redwoods), the same data behind the official park map viewer.
  Pulled by `scripts/fetch_trails.py --source csp`. Authoritative, and it
  carries a use class so parking aisles and service roads can be filtered out.
- **Viewpoints** — OpenStreetMap, cross-checked against the State Parks
  facility points where both carry the feature.
- **Route and elevation** — the Strava GPX in this repo, baked into `DATA`.

`--source osm` still works and pulls OpenStreetMap via Overpass, kept as a
fallback and for comparing the two.

[csp]: https://csparks.maps.arcgis.com/apps/instant/basic/index.html?appid=065b067caa204e8da48d4b53c9483ab0&UNITNBR=418

Trail data © California State Parks · Route and viewpoints © OpenStreetMap
contributors.
