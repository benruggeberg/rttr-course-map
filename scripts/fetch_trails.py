#!/usr/bin/env python3
"""
Pull the Henry Cowell trail network from OpenStreetMap and bake it into
rttr_course_map.html as DATA.trails / DATA.trailNames.

Re-runnable and idempotent: it rewrites the two DATA blocks in place, so you
can run it again after OSM improves or after you retune the filters.

    python3 scripts/fetch_trails.py                 # preview, writes nothing
    python3 scripts/fetch_trails.py --write         # patch the HTML
    python3 scripts/fetch_trails.py --buffer 220 --write

The judgement call this script encodes: show enough trail that a volunteer can
name the junction they are standing at, and no more. Two filters do that work
 - `--buffer`   drop anything further than this from the course
 - `--drop-coincident` drop trail that the course itself runs along, since the
   route line already draws it and a dashed twin underneath just muddies it

Stdlib only. No install step, so it still runs on a laptop in a year.
"""

import argparse
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HTML = Path(__file__).resolve().parent.parent / "rttr_course_map.html"

MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# California State Parks' own trail layer, the one behind the official park
# map viewer. Authoritative where OSM is volunteer-contributed, and it carries
# a use class (TRLDES) so service roads can be told from trail. Unit 418 is
# Henry Cowell Redwoods SP.
CSP_TRAILS = ("https://services2.arcgis.com/AhxrK3F6WM8ECvDi/arcgis/rest/"
              "services/Click_able_Layers/FeatureServer/4/query")
CSP_UNIT = 418

# State Parks abbreviates on the map face; spell it out for a printed label.
# "Road" is abbreviated rather than expanded: these names are long, and the
# sheet has more use for the width than the reader has for the extra three
# letters. "Fire Rd" is what the park signs say anyway.
NAME_FIXES = [
    (r"\bTrl\b", "Trail"), (r"\bCrk\b", "Creek"), (r"\bMtn\b", "Mountain"),
    (r"\bFR\b", "Fire Rd"), (r"\bAccs\b", "Access"), (r"\bRoad\b", "Rd"),
]

# Dropped outright -- geometry and label both. Trail that adds nothing at this
# scale or that the committee has asked not to show.
DEFAULT_DROP = ["Ox Trail Path", "Ox Trail", "Ox Connector Trail",
                "Residence Service Road", "Meadow Trail"]

# Trails kept at their full extent inside the bbox rather than clipped to the
# course buffer. Ridge Fire Road is here because the stretch between Pipeline
# Road and the Observation Deck is NOT part of the race, and a runner needs to
# see the whole of it to understand that it is the wrong way.
# Eagle Creek Trail is here so it does not stop dead at the buffer edge --
# a trail that ends abruptly reads as a dead end rather than a clip.
FULL_EXTENT = ["Ridge Fire Road", "Eagle Creek Trail"]

# Ways we consider "trail". Henry Cowell tags its fire roads as track/service
# and its singletrack as path/footway.
HIGHWAY_TYPES = ["path", "footway", "track", "bridleway", "cycleway"]

# Unofficial / rider-invented names OSM carries inside the park. They are real
# OSM data but they are not what a volunteer will hear on the radio or read on
# a park signpost, so they are dropped by default rather than labelled.
DEFAULT_EXCLUDE = ["Your Sister", "Bottom of the Low Road",
                   # crowds the spot Ridge Fire Road needs
                   "Big Rock Hole Trail"]

# The trails the 10K actually runs on. Their names are the ones a volunteer
# says on the radio, so they get the prominent label style and everything else
# is set smaller and grey to keep the two apart at a glance.
COURSE_TRAILS = [
    "River Trail", "Ridge Fire Road", "Powder Mill Fire Road",
    "Pipeline Road", "Indian Creek Trail",
]

R_EARTH = 6378137.0


# ---------------------------------------------------------------- geometry

def local_proj(lat0):
    """Equirectangular metres about lat0. Accurate enough over a 3 km park."""
    kx = math.radians(1.0) * R_EARTH * math.cos(math.radians(lat0))
    ky = math.radians(1.0) * R_EARTH
    return lambda lat, lon: (lon * kx, lat * ky)


def seg_dist(px, py, ax, ay, bx, by):
    """Distance from point p to segment ab, all in metres."""
    dx, dy = bx - ax, by - ay
    d2 = dx * dx + dy * dy
    if d2 <= 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / d2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def dist_to_route(pt, route_xy):
    """Min distance from a projected point to the projected route polyline."""
    px, py = pt
    best = float("inf")
    for i in range(1, len(route_xy)):
        ax, ay = route_xy[i - 1]
        bx, by = route_xy[i]
        # cheap reject: skip segments whose endpoints are both far away
        if min(abs(px - ax), abs(px - bx)) > best and min(abs(py - ay), abs(py - by)) > best:
            continue
        d = seg_dist(px, py, ax, ay, bx, by)
        if d < best:
            best = d
    return best


def simplify(pts, tol):
    """Douglas-Peucker. pts are projected metres; tol in metres."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        s, e = stack.pop()
        ax, ay = pts[s]
        bx, by = pts[e]
        worst, idx = 0.0, -1
        for i in range(s + 1, e):
            d = seg_dist(pts[i][0], pts[i][1], ax, ay, bx, by)
            if d > worst:
                worst, idx = d, i
        if worst > tol and idx > 0:
            keep[idx] = True
            stack.append((s, idx))
            stack.append((idx, e))
    return [p for p, k in zip(pts, keep) if k]


def path_length(xy):
    return sum(math.dist(xy[i - 1], xy[i]) for i in range(1, len(xy)))


# ---------------------------------------------------------------- inputs

def read_track(html_text):
    m = re.search(r"\n  track: (\[\[.*?\]\]),\n", html_text, re.S)
    if not m:
        sys.exit("Could not find DATA.track in the HTML.")
    return json.loads(m.group(1))


def tidy_name(n):
    if not n:
        return None
    for pat, rep in NAME_FIXES:
        n = re.sub(pat, rep, n)
    return re.sub(r"\s+", " ", n).strip()


def fetch_csp(bbox):
    """California State Parks trail layer -> [{name, coords:[(lat,lon)]}]."""
    params = {
        "where": f"Unit_Nbr={CSP_UNIT}",
        "geometry": f"{bbox[1]:.6f},{bbox[0]:.6f},{bbox[3]:.6f},{bbox[2]:.6f}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326", "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "ROUTENAME,TRLDES",  # TRLDES is the use class
        "returnGeometry": "true",
        "f": "json",
    }
    url = CSP_TRAILS + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "rttr-course-map/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode())
    if "error" in data:
        sys.exit(f"State Parks service error: {data['error']}")

    out = []
    for f in data.get("features", []):
        attrs = f.get("attributes") or {}
        # "Not Designated" is how the layer marks parking aisles, entrance
        # roads and residence service roads. Real to the park, noise to a
        # runner, so they never reach the sheet.
        if (attrs.get("TRLDES") or "").strip() == "Not Designated":
            continue
        name = tidy_name(attrs.get("ROUTENAME"))
        for path in (f.get("geometry") or {}).get("paths", []):
            # Esri gives [x, y] i.e. [lon, lat]
            coords = [(pt[1], pt[0]) for pt in path if len(pt) >= 2]
            if len(coords) >= 2:
                out.append({"name": name, "coords": coords})
    return out


def fetch_osm(bbox):
    """OpenStreetMap via Overpass -> [{name, coords:[(lat,lon)]}]."""
    regex = "|".join(HIGHWAY_TYPES)
    query = f"""[out:json][timeout:180];
(
  way["highway"~"^({regex})$"]({bbox[0]:.6f},{bbox[1]:.6f},{bbox[2]:.6f},{bbox[3]:.6f});
  way["highway"]["name"~"[Ff]ire [Rr](oa)?d"]({bbox[0]:.6f},{bbox[1]:.6f},{bbox[2]:.6f},{bbox[3]:.6f});
);
out body geom;
"""
    data = overpass(query)
    out = []
    for e in data.get("elements", []):
        if e.get("type") != "way" or not e.get("geometry"):
            continue
        out.append({
            "name": tidy_name((e.get("tags") or {}).get("name")),
            "coords": [(g["lat"], g["lon"]) for g in e["geometry"]],
        })
    return out


def overpass(query):
    body = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for url in MIRRORS:
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    url, data=body,
                    headers={"User-Agent": "rttr-course-map/1.0 (race ops map; contact FBCA)"},
                )
                with urllib.request.urlopen(req, timeout=120) as r:
                    return json.loads(r.read().decode())
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
                last = e
                print(f"  {url} attempt {attempt + 1} failed: {e}", file=sys.stderr)
                time.sleep(4 * (attempt + 1))
    sys.exit(f"Overpass unreachable: {last}")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--buffer", type=float, default=180.0,
                    help="metres from the course to keep trail (default 180)")
    ap.add_argument("--min-length", type=float, default=70.0,
                    help="drop trail fragments shorter than this, metres")
    ap.add_argument("--drop-coincident", type=float, default=12.0,
                    help="drop trail running within this many metres of the "
                         "course for most of its length; 0 disables")
    ap.add_argument("--tolerance", type=float, default=4.0,
                    help="Douglas-Peucker tolerance, metres")
    ap.add_argument("--exclude", default=",".join(DEFAULT_EXCLUDE),
                    help="comma-separated trail names to drop entirely; OSM "
                         "carries some unofficial names that only confuse a "
                         "volunteer reading this at 7am")
    ap.add_argument("--on-course", default=",".join(COURSE_TRAILS),
                    help="comma-separated trails the course runs on. These get "
                         "the prominent label style. Detection is automatic; "
                         "this list is a safety net for uneven OSM coverage")
    ap.add_argument("--source", choices=["csp", "osm"], default="csp",
                    help="csp = California State Parks' own trail layer, the "
                         "one behind the official park map (default). "
                         "osm = OpenStreetMap via Overpass")
    ap.add_argument("--repeat", default="Pipeline Road",
                    help="comma-separated trails to label twice. For a trail "
                         "the course follows a long way, one label leaves a "
                         "reader tracing the line to find out where they are")
    ap.add_argument("--repeat-gap", type=float, default=400.0,
                    help="minimum metres between two labels of the same trail")
    ap.add_argument("--drop", default=",".join(DEFAULT_DROP),
                    help="comma-separated trails to remove entirely, geometry "
                         "and label both")
    ap.add_argument("--label-clearance", type=float, default=32.0,
                    help="metres a background trail name keeps from the race "
                         "route, so it never reads as labelling the course")
    ap.add_argument("--full-extent", default=",".join(FULL_EXTENT),
                    help="trails drawn at full extent instead of clipped to the "
                         "course buffer, so a wrong turn is visible end to end")
    ap.add_argument("--write", action="store_true", help="patch the HTML in place")
    args = ap.parse_args()

    tidy_set = lambda v: {(tidy_name(n.strip()) or "").lower() for n in v.split(",") if n.strip()}
    excluded = tidy_set(args.exclude)
    dropped = tidy_set(args.drop)
    full_extent = tidy_set(args.full_extent)

    html_text = HTML.read_text(encoding="utf-8")
    track = read_track(html_text)

    lat0 = sum(p[0] for p in track) / len(track)
    proj = local_proj(lat0)
    route_xy = [proj(la, lo) for la, lo in track]

    lats = [p[0] for p in track]
    lons = [p[1] for p in track]
    pad = args.buffer / 111320.0
    bbox = (min(lats) - pad, min(lons) - pad * 1.25,
            max(lats) + pad, max(lons) + pad * 1.25)

    src = "California State Parks (unit 418)" if args.source == "csp" else "OpenStreetMap"
    print(f"Querying {src}, bbox "
          f"{bbox[0]:.4f},{bbox[1]:.4f},{bbox[2]:.4f},{bbox[3]:.4f} ...")
    ways = fetch_csp(bbox) if args.source == "csp" else fetch_osm(bbox)
    print(f"  {len(ways)} candidate ways returned")

    kept = []
    for w in ways:
        name = w["name"]
        # Dropped names take their geometry with them.
        if name and name.lower() in dropped:
            continue
        # Excluded names keep their geometry but lose their label: the trail is
        # still real tread a runner could wrongly turn onto, it just should not
        # be captioned with a name nobody uses.
        if name and name.lower() in excluded:
            name = None
        # Same treatment for connector stubs and access spurs. The tread stays
        # on the map; the name is a mouthful nobody says out loud, and at this
        # scale it crowds out the trail names that matter.
        if name and re.search(r"\b(Connector|Connectors|Access|Spur)\b", name, re.I):
            name = None
        geom = w["coords"]
        if len(geom) < 2:
            continue

        # Clip to the buffer: keep contiguous runs of points near the course.
        # Full-extent trails skip the clip entirely.
        limit = 1e9 if (name and name.lower() in full_extent) else args.buffer
        runs, cur = [], []
        for la, lo in geom:
            if dist_to_route(proj(la, lo), route_xy) <= limit:
                cur.append((la, lo))
            else:
                if len(cur) >= 2:
                    runs.append(cur)
                cur = []
        if len(cur) >= 2:
            runs.append(cur)

        for run in runs:
            xy = [proj(la, lo) for la, lo in run]
            length = path_length(xy)

            # Is this stretch the course itself? Its geometry is redundant --
            # the route line already draws it -- but its NAME is the most
            # valuable label on the sheet, so the run is kept and tagged.
            near = 0.0
            if args.drop_coincident > 0:
                near = sum(1 for p in xy
                           if dist_to_route(p, route_xy) <= args.drop_coincident) / len(xy)
            on_course = near > 0.8

            # On-course runs only have to be long enough to anchor a label.
            if length < (40.0 if on_course else args.min_length):
                continue

            simp = simplify(xy, args.tolerance)
            idx = {id(p): i for i, p in enumerate(xy)}
            keep_ll = [run[idx[id(p)]] for p in simp]
            kept.append({
                "name": name,
                "path": [[round(la, 6), round(lo, 6)] for la, lo in keep_ll],
                "length": length,
                "xy": simp,
                "on_course": on_course,
            })

    kept.sort(key=lambda t: -t["length"])
    named = [t for t in kept if t["name"]]

    # A trail counts as a course trail if the route measurably runs along it,
    # or if it is named on --on-course. The explicit list exists because OSM
    # coverage is uneven and a course trail missing from the map is the one
    # error a volunteer cannot recover from.
    forced = tidy_set(args.on_course)
    detected = {t["name"].lower() for t in named if t["on_course"]}
    course_names = detected | forced

    # Geometry for the course's own trails is dropped -- the route line is
    # already there -- but their names survive into the label pass.
    #
    # Stray non-coincident fragments of a course trail go too. The route
    # already shows where River Trail runs, so a disconnected dashed stub of it
    # off to one side reads as a separate trail and is simply noise. Trails
    # named on --full-extent are exempt: Ridge Fire Road's unraced stretch is
    # shown precisely so a runner can see it is the wrong way.
    geom = [t for t in kept
            if not t["on_course"]
            and not (t["name"] and t["name"].lower() in course_names
                     and t["name"].lower() not in full_extent)]
    print(f"  {len(geom)} segments drawn ({len([t for t in geom if t['name']])} named), "
          f"{sum(len(t['path']) for t in geom)} points total")
    print(f"  course trails detected: {sorted(detected) or 'none'}")
    missing = sorted(n for n in forced if n not in {t['name'].lower() for t in named})
    if missing:
        print(f"  !! named on --on-course but absent from OSM here: {missing}")

    # One label per trail name. For a course trail, prefer to anchor it on the
    # stretch the course actually follows; otherwise take its longest segment.
    by_name = {}
    for t in named:
        key = t["name"]
        cur = by_name.get(key)
        if cur is None:
            by_name[key] = t
        elif key.lower() in course_names:
            if t["on_course"] and not cur["on_course"]:
                by_name[key] = t
            elif t["on_course"] == cur["on_course"] and t["length"] > cur["length"]:
                by_name[key] = t
        elif t["length"] > cur["length"]:
            by_name[key] = t

    def label_path(t):
        """The stretch of a trail its name should sit on.

        A background trail that crosses the course must not be captioned at the
        crossing: the name lands across the race line and reads as if it named
        the race. So its label runs along the longest stretch that stays well
        clear of the route. Course trails keep their full path -- the route is
        what they name.
        """
        if t["on_course"]:
            return t["path"]
        runs, cur = [], []
        for la, lo in t["path"]:
            if dist_to_route(proj(la, lo), route_xy) > args.label_clearance:
                cur.append((la, lo))
            else:
                if len(cur) >= 2:
                    runs.append(cur)
                cur = []
        if len(cur) >= 2:
            runs.append(cur)
        if not runs:
            return t["path"]
        best = max(runs, key=lambda r: path_length([proj(la, lo) for la, lo in r]))
        return [[round(la, 6), round(lo, 6)] for la, lo in best]

    def anchor(t):
        """Label anchor and on-sheet bearing for one segment."""
        xy, ll = t["xy"], t["path"]
        mid = len(ll) // 2
        a, b = max(0, mid - 1), min(len(ll) - 1, mid + 1)
        dx = xy[b][0] - xy[a][0]
        dy = xy[b][1] - xy[a][1]
        # screen Y grows downward, so negate dy to get the on-sheet bearing
        rot = math.degrees(math.atan2(-dy, dx))
        if rot > 90:
            rot -= 180
        elif rot < -90:
            rot += 180
        return ll[mid], round(rot, 1)

    repeat = {n: 1 for n in tidy_set(args.repeat)}

    labels = []
    # Course trails first so the collision pass hands them the best positions.
    for name, t in sorted(by_name.items(),
                          key=lambda kv: (kv[0].lower() not in course_names, -kv[1]["length"])):
        at, rot = anchor(t)
        on = name.lower() in course_names
        labels.append({"text": name.upper(), "at": at, "rotate": rot,
                       "onCourse": on, "path": label_path(t)})

        # A long trail the course follows for miles reads better labelled more
        # than once -- a reader should not have to trace the line back to find
        # out what they are standing on.
        if name.lower() in repeat:
            others = [o for o in named
                      if o["name"] == name and o is not t and o["on_course"] == t["on_course"]]
            for o in sorted(others, key=lambda o: -o["length"]):
                at2, rot2 = anchor(o)
                # far enough from every label already placed for this trail
                if all(math.dist(proj(*at2), proj(*l["at"])) > args.repeat_gap
                       for l in labels if l["text"] == name.upper()):
                    labels.append({"text": name.upper(), "at": at2,
                                   "rotate": rot2, "onCourse": on,
                                   "path": label_path(o)})
                    break

    trails_src = ",\n".join(
        "    { name:%s, path:%s }" % (
            json.dumps(t["name"]) if t["name"] else "null",
            "[" + ",".join("[%s,%s]" % (p[0], p[1]) for p in t["path"]) + "]",
        )
        for t in geom
    )
    names_src = ",\n".join(
        '    { text:%s, at:[%s,%s], rotate:%s%s, path:%s }' % (
            json.dumps(l["text"]), l["at"][0], l["at"][1], l["rotate"],
            ", onCourse:true" if l["onCourse"] else "",
            "[" + ",".join("[%s,%s]" % (p[0], p[1]) for p in l["path"]) + "]")
        for l in labels
    )

    print("\nTrails drawn, by length:")
    for t in geom[:40]:
        print(f"  {t['length']:7.0f} m  {len(t['path']):3d} pts  {t['name'] or '(unnamed)'}")

    on = [l for l in labels if l["onCourse"]]
    off = [l for l in labels if not l["onCourse"]]
    print(f"\nCourse trail labels ({len(on)}):")
    for l in on:
        print(f"  {l['text']:<28} rotate {l['rotate']:>6.1f}  at {l['at']}")
    print(f"\nOther trail labels ({len(off)}):")
    for l in off:
        print(f"  {l['text']:<28} rotate {l['rotate']:>6.1f}  at {l['at']}")

    if not args.write:
        print("\nPreview only. Re-run with --write to patch the HTML.")
        return

    new = re.sub(
        r"(\n  trails: \[)(.*?)(\n  \],)",
        lambda m: "\n  trails: [\n" + trails_src + "\n  ],",
        html_text, count=1, flags=re.S,
    )
    new = re.sub(
        r"(\n  trailNames: \[)(.*?)(\n  \],)",
        lambda m: "\n  trailNames: [\n" + names_src + "\n  ],",
        new, count=1, flags=re.S,
    )
    if new == html_text:
        sys.exit("Nothing was replaced -- the DATA block markers moved?")
    HTML.write_text(new, encoding="utf-8")
    print(f"\nPatched {HTML.name}: {len(geom)} trails drawn, {len(labels)} labels "
          f"({len(on)} course, {len(off)} other).")


if __name__ == "__main__":
    main()
