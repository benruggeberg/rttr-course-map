# Open items to verify before race day

Run `python3 scripts/check_markers.py` to regenerate the distance column.

## Course monitor coordinates — resolved

Three of the eight monitor positions sat further off the route than a
hand-clicked coordinate normally lands. All three have been corrected; the
originals are recorded here so the change is reversible.

| Post | Recorded | Now | Why |
| --- | --- | --- | --- |
| Rincon (4) | 37.043600, -122.069740 (**664 m** off) | 37.025948, -122.055330 (6 m off, mile 1.54) | Corrected to the real junction |
| Indian (2) | 37.035856, -122.057746 (81 m off) | 37.036280, -122.058480 (on route, mile 5.89) | Snapped to the course |
| Eagle (1) | 37.030157, -122.054764 (56 m off) | 37.030250, -122.054140 (on route, mile 5.36) | Snapped to the course |

**Rincon** was not a judgement call. Two independent authorities put the
Rincon Fire Rd x Ridge Fire Rd junction within 2 m of each other — California
State Parks at `37.025948,-122.055330` and OSM at `37.025934,-122.055312` —
and the recorded coordinate was 664 m away, plotting clear off the sheet.

**Eagle and Indian could not be verified from any trail source**, because no
single source carries both trails of either junction: State Parks has Eagle
Creek Trail but no River Trail, and Redwood Grove Loop but no Indian Creek;
OSM has the mirror-image gaps. So the route itself was used as the authority —
a course monitor stands on the course. Only the perpendicular error was
removed; the along-course position of each is unchanged.

Worth a glance on the ground, but nothing here now plots off the course.

## Trail source disagreements

Trails now come from California State Parks (unit 418) rather than OSM. The
two sources do not agree everywhere:

- **Indian Creek Trail** is in OSM but **absent from the State Parks layer**,
  so it no longer carries a label. It is named on the course-trail list, and
  `fetch_trails.py` prints a warning about it on every run.
- **Redwood Grove Loop Trail** is in the State Parks layer but was missing
  from OSM. This one is good news: it corroborates the Indian post's
  description, "Redwood Grove Trail to Indian Creek".
- **Rincon Fire Road** reads as on-course in OSM but not in the State Parks
  geometry, so it is currently styled as a background trail.

## Still missing

- **Musician** — no coordinates yet.
- **Big Foot Actor** — no coordinates yet.
- **Radio channel and course-lead phone** — deliberately blank rules on the
  printed sheet, to be filled in by hand on race morning.

## Data sources added later

- **Water** — USGS National Hydrography Dataset (NHDPlus HR), via
  `scripts/fetch_water.py`. San Lorenzo River plus Eagle, Powder Mill and
  Gold Gulch creeks. Strahler stream order drives line weight.
- **Terrain** — USGS 10 m NED sampled on a 45 m grid and traced to 20 m
  contours by `scripts/fetch_terrain.py`.

## Print QA — done

Checked against the generated PDFs, not the screen.

| Check | Result |
| --- | --- |
| Page size | 8.50 x 11.00 in and 24.00 x 36.00 in exactly |
| Page count | one page each, including when printed while zoomed to 300% |
| 0.25" printer margin | clear; title and credit were inside it and were moved |
| Grayscale legibility | every feature distinguishable by shape or number alone |
| Emoji rasterise | yes — 16 embedded images in the poster PDF, 0 in the volunteer sheet, which uses drawn shapes |
| Fonts | Anton and Barlow embedded and subsetted into both PDFs |
| All mile squares visible | yes — mile 4 was hidden under post 5 and is nudged clear |

Fixed during QA:
- The San Lorenzo ran straight down through the volunteer brief panel. Terrain,
  water and trails are now clipped to the map area.
- The river was too heavy in mono and competed with the route. Lightened and
  thinned; it now reads as clearly subordinate.
- Pine Trail's label ran past the right edge of the sheet.
- Rincon's label collided with the Observation post after Rincon was corrected.

One loose end: the volunteer PDF embeds Arial Bold alongside Barlow. The
musician glyph is a music note that Barlow does not carry, so it falls back.
It renders correctly here but would differ on a machine without Arial.

## Known cosmetic issues

- Mile marker 4 sits close to the brief panel rule on the volunteer sheet.
- The page loads Anton and Barlow Semi Condensed from Google Fonts. Opened
  offline it falls back to Arial/Impact and type metrics shift slightly.
  Inlining the fonts as base64 would fix it, at roughly 100–200 KB.
