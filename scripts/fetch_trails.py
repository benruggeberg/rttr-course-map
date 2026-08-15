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

# Ways we consider "trail". Henry Cowell tags its fire roads as track/service
# and its singletrack as path/footway.
HIGHWAY_TYPES = ["path", "footway", "track", "bridleway", "cycleway"]

# Unofficial / rider-invented names OSM carries inside the park. They are real
# OSM data but they are not what a volunteer will hear on the radio or read on
# a park signpost, so they are dropped by default rather than labelled.
DEFAULT_EXCLUDE = ["Your Sister", "Bottom of the Low Road"]

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
    ap.add_argument("--write", action="store_true", help="patch the HTML in place")
    args = ap.parse_args()

    excluded = {n.strip().lower() for n in args.exclude.split(",") if n.strip()}

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

    regex = "|".join(HIGHWAY_TYPES)
    query = f"""[out:json][timeout:180];
(
  way["highway"~"^({regex})$"]({bbox[0]:.6f},{bbox[1]:.6f},{bbox[2]:.6f},{bbox[3]:.6f});
  way["highway"]["name"~"[Ff]ire [Rr](oa)?d"]({bbox[0]:.6f},{bbox[1]:.6f},{bbox[2]:.6f},{bbox[3]:.6f});
);
out body geom;
"""
    print(f"Querying Overpass, bbox {bbox[0]:.4f},{bbox[1]:.4f},{bbox[2]:.4f},{bbox[3]:.4f} ...")
    data = overpass(query)
    ways = [e for e in data.get("elements", []) if e.get("type") == "way" and e.get("geometry")]
    print(f"  {len(ways)} candidate ways returned")

    kept = []
    for w in ways:
        name = (w.get("tags") or {}).get("name")
        # Excluded names keep their geometry but lose their label: the trail is
        # still real tread a runner could wrongly turn onto, it just should not
        # be captioned with a name nobody uses.
        if name and name.lower() in excluded:
            name = None
        geom = [(g["lat"], g["lon"]) for g in w["geometry"]]
        if len(geom) < 2:
            continue

        # Clip to the buffer: keep contiguous runs of points near the course.
        runs, cur = [], []
        for la, lo in geom:
            if dist_to_route(proj(la, lo), route_xy) <= args.buffer:
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
    forced = {n.strip().lower() for n in args.on_course.split(",") if n.strip()}
    detected = {t["name"].lower() for t in named if t["on_course"]}
    course_names = detected | forced

    # Geometry for the course's own trails is dropped -- the route line is
    # already there -- but their names survive into the label pass.
    geom = [t for t in kept if not t["on_course"]]
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

    labels = []
    # Course trails first so the collision pass hands them the best positions.
    for name, t in sorted(by_name.items(),
                          key=lambda kv: (kv[0].lower() not in course_names, -kv[1]["length"])):
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
        labels.append({
            "text": name.upper(),
            "at": ll[mid],
            "rotate": round(rot, 1),
            "onCourse": name.lower() in course_names,
        })

    trails_src = ",\n".join(
        "    { name:%s, path:%s }" % (
            json.dumps(t["name"]) if t["name"] else "null",
            "[" + ",".join("[%s,%s]" % (p[0], p[1]) for p in t["path"]) + "]",
        )
        for t in geom
    )
    names_src = ",\n".join(
        '    { text:%s, at:[%s,%s], rotate:%s%s }' % (
            json.dumps(l["text"]), l["at"][0], l["at"][1], l["rotate"],
            ", onCourse:true" if l["onCourse"] else "")
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
