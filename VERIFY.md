# Open items to verify before race day

Run `python3 scripts/check_markers.py` to regenerate the distance column.

## Course monitor coordinates to check on the ground

Three of the eight monitor positions sit further off the route than a
hand-clicked coordinate normally lands. They are **kept exactly as recorded**
in the planning sheet — the numbers below are what the map data says, not
corrections that have been applied.

| Post | Recorded | Off route | Renders at | Note |
| --- | --- | --- | --- | --- |
| Rincon (4) | 37.043600, -122.069740 | **664 m** | mile 0.25 | Renders well outside the course |
| Indian (2) | 37.035856, -122.057746 | 81 m | mile 5.89 | |
| Eagle (1) | 37.030157, -122.054764 | 56 m | mile 5.36 | |

The other five (Junction, Powder, Observation, Pine, Last mile) and both water
stations are within 20 m of the route and need no attention.

### What OpenStreetMap says about those junctions

Cross-checked against the named trail network, for whoever walks these:

- **Rincon Fire Rd × Ridge Fire Rd** — the two ways share a node at
  `37.025934, -122.055312`. That is 5 m off the route at **mile 1.54**. The
  recorded coordinate would place the post at mile 0.25, near the start.
- **River Trail × Eagle Creek Trail** — junction at `37.030297, -122.055916`,
  21 m off the route at **mile 1.12**.
- **Redwood Grove Trail** does not exist under that name in OSM here, so the
  Indian post cannot be cross-checked against the trail network. Worth
  confirming the trail name as well as the coordinate.

Note the route passes some of this ground twice, so a coordinate can be
genuinely correct while the "renders at" mile looks surprising — the nearest
track point may be on the return leg.

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
- **Course_Monitor_8** — descriptive location is still the placeholder
  "Last mile".
- **Radio channel and course-lead phone** — deliberately blank rules on the
  printed sheet, to be filled in by hand on race morning.

## Known cosmetic issues

- Mile marker 4 sits close to the brief panel rule on the volunteer sheet.
- The page loads Anton and Barlow Semi Condensed from Google Fonts. Opened
  offline it falls back to Arial/Impact and type metrics shift slightly.
  Inlining the fonts as base64 would fix it, at roughly 100–200 KB.
