# Claude Code handoff — RTTR Operations Course Map

Paste this whole file as your opening message to Claude Code, with
`rttr_course_map.html` and `RTTR-10k-course.gpx` in the working directory.

---

## Context

I'm a committee member of the Felton Business & Community Association (FBCA),
organizing the 56th Annual Race Thru The Redwoods — a 10K trail run on
**Sunday, August 16, 2026**, starting and finishing at Roaring Camp Railroads
and running through Henry Cowell Redwoods State Park.

I need an operations course map in two forms from **one file**:

1. **Volunteer handout** — 8.5×11, ~20 copies, likely printed black-and-white.
   Must be legible at 7am in dappled redwood light, on paper, by someone who
   has never seen the course.
2. **Poster** — 24×36, one copy, displayed at the start/finish area. Colour.

`rttr_course_map.html` is a working single-file build. Read it first before
changing anything.

## How the file is built (do not restructure this)

- **No Leaflet, no map tiles.** The map is inline SVG drawn from a Web Mercator
  projection of the GPX track. This was a deliberate choice: raster tiles print
  badly at poster size and carry licensing and attribution problems. Keep it
  vector.
- **Everything editable lives in a single `DATA` object** at the top of the
  `<script>` block. Coordinates, marker lists, trail names, the brief panel,
  emoji glyphs. I maintain this file by editing `DATA` and nothing else — please
  preserve that property. If you add a feature, its knobs go in `DATA`.
- **Layers are `<g class="layer-*">` groups**, toggled by adding `off-*` classes
  to the SVG root from sidebar checkboxes. Print CSS hides `#controls`, so what
  is on screen is exactly what prints.
- `@page` size is rewritten by JS when the sheet dropdown changes. One file
  drives Letter and 24×36.
- Output presets (`PRESETS` object) set sheet size + theme + symbol style +
  layer visibility in one move. `volunteer` and `poster` exist.

## Verified facts about the course (already computed — don't re-derive)

- 450 track points, **6.28 mi / 10.11 km**, **907 ft gain**, high point 797 ft.
- Track and per-point elevation are **already baked into `DATA.track`
  and `DATA.ele`**. The GPX is only needed if we re-import.
- Start and finish are **105 m apart**, not coincident — two flags, not one.
  Labels auto-offset to opposite sides.
- Course bbox aspect is 0.765, near-perfect for portrait sheets.
- At Letter size the scale is ~3.0 m per viewBox unit; at 24×36, ~2.6.
- Legend is bottom-left, verified to contain **0 route points**. Bottom-right
  had 104, which is why it moved. If you reposition the legend, re-run that
  check rather than eyeballing it.

## Tasks, in priority order

### 1. Park trail network (highest value)
`DATA.trails` is empty. Pull the Henry Cowell Redwoods State Park trail network
from OpenStreetMap via Overpass, clipped to a small buffer around the course
bbox, and populate `DATA.trails` as `{name, path:[[lat,lon],...]}`.

- Filter to `highway=path|footway|track` plus named fire roads.
- Simplify each way so the file stays manageable.
- **Include only trails near the course.** A full park dump will bury the route.
  Judgment call: enough context that a volunteer can orient themselves at a
  junction, not so much that the route stops being the obvious hero of the map.
- Write a small reusable script for this rather than pasting a one-off blob, so
  I can re-run it.

### 2. Trail name labels
Populate `DATA.trailNames` from the OSM names. Each entry is
`{text, at:[lat,lon], rotate, to:[lat,lon]}` where `to` draws a leader arrow.
Prefer labels set along the trail's own bearing. These are what let a volunteer
say "you're at the Pipeline Road junction" over the radio.

### 3. Label collision pass
This is the real work and it needs your eyes.

- **Known conflict:** Water 1 sits near mile 2 and Water 2 near mile 4, so the
  water emoji and mile-marker squares will likely overlap.
- Marker text labels are currently hard-coded to `x+19, y-3`. They need
  per-marker placement, or automatic displacement away from the route.
- Add an optional `offset:[dx,dy]` on each marker in `DATA` so I can nudge
  individual labels by hand without touching code.
- **Render to PNG and actually look at it** (headless Chrome or Playwright) at
  both sheet sizes. Iterate against the image, not against the source.

### 4. Marker placement
I'm still collecting coordinates for volunteer posts, musicians, and Bigfoot.
Two water stations are already in. I'll paste the rest as `DATA.markers` entries
— captured with the built-in coordinate picker, so they'll arrive pre-formatted.
Expect roughly 20 volunteer posts.

When they land, sanity-check each one's distance from the route and flag
anything more than ~30 m off, which usually means a mis-click.

### 5. Print QA
- Render both presets to PDF and inspect.
- **Convert the volunteer PDF to true grayscale and check legibility.** Colour
  is a secondary channel only — every feature must be distinguishable by shape
  or number alone. The `theme-mono` + `shapes` combination exists for this.
- Confirm nothing important falls in the outer 0.25" (printer margin).
- Verify emoji actually rasterize into the PDF rather than dropping out.
  Note: I already had to abandon U+1FAC8 (the new "hairy creature" glyph)
  because it rendered as a hollow box; Bigfoot is now U+1F463 footprints.

### 6. Attribution
The Strava GPX metadata credits OpenStreetMap contributors under ODbL, and the
trail data will too. Add a small line near the legend:
`Route and trail data © OpenStreetMap contributors`.

### 7. Nice-to-have, only if the above is done
A fantasy / illustrated map theme as a fourth entry in the theme dropdown —
hand-lettered feel, illustrated redwoods, aged paper. This is a **poster-only**
idea; volunteers get the plain legible version. Since geometry and styling are
already separated, this should be a theme plus a decorative layer, not a rewrite.

## Constraints

- **Don't touch the live website.** This is a standalone file. Separately, the
  RTTR site (github.com/ferdgren/RTTR) has an existing Leaflet course map on
  `course_info.html` that stays as it is. Any website work goes on a branch with
  a PR — never pushed directly to the live site, especially this close to race day.
- Keep it a **single self-contained HTML file** with no build step and no runtime
  network dependency. It has to open reliably from a laptop with no wifi.
- Race is **August 16**. Prioritize the volunteer handout being correct and
  readable over the poster being beautiful.

## How I work

- I'm direct about visual defects and will point at specific things that look
  wrong. Give me concrete fixes rather than general revisions.
- Show me a rendered image when you change anything visual.
- If something I've asked for is a bad idea, say so and tell me why.
