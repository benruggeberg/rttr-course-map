#!/usr/bin/env python3
"""
Build vector contour lines for the course area and bake them into
rttr_course_map.html as DATA.contours.

Contours rather than a hillshade image on purpose: the sheet has to stay a
single self-contained file that prints cleanly at 24x36, and a raster shade
would both bloat it and go muddy on a photocopier. Lines scale forever.

    python3 scripts/fetch_terrain.py                  # preview
    python3 scripts/fetch_terrain.py --write
    python3 scripts/fetch_terrain.py --interval 10 --write

Elevation comes from USGS 10 m NED via the public Open Topo Data API, sampled
on a grid and traced with marching squares. Stdlib only.
"""

import argparse
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HTML = Path(__file__).resolve().parent.parent / "rttr_course_map.html"
API = "https://api.opentopodata.org/v1/ned10m"
BATCH = 100          # API caps locations per request
R_EARTH = 6378137.0


def read_track(text):
    m = re.search(r"\n  track: (\[\[.*?\]\]),\n", text, re.S)
    if not m:
        sys.exit("Could not find DATA.track in the HTML.")
    return json.loads(m.group(1))


def fetch_grid(lats, lons):
    """Elevation for every (lat, lon) pair, row-major."""
    pts = [(la, lo) for la in lats for lo in lons]
    out = []
    for i in range(0, len(pts), BATCH):
        chunk = pts[i:i + BATCH]
        locs = "|".join(f"{la:.6f},{lo:.6f}" for la, lo in chunk)
        url = f"{API}?locations={urllib.parse.quote(locs)}"
        for attempt in range(4):
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "rttr-course-map/1.0"})
                with urllib.request.urlopen(req, timeout=90) as r:
                    data = json.loads(r.read().decode())
                if data.get("status") != "OK":
                    raise RuntimeError(data.get("error", "bad status"))
                out.extend(None if x["elevation"] is None else float(x["elevation"])
                           for x in data["results"])
                break
            except Exception as e:                       # noqa: BLE001
                if attempt == 3:
                    sys.exit(f"Elevation API failed: {e}")
                time.sleep(2 * (attempt + 1))
        print(f"\r  {min(i+BATCH, len(pts))}/{len(pts)} samples", end="", flush=True)
        time.sleep(1.05)                                  # respect 1 call/sec
    print()
    return out


def marching_squares(grid, lats, lons, level):
    """Trace one contour level. Returns a list of [[lat,lon], ...] polylines."""
    ny, nx = len(lats), len(lons)

    def val(iy, ix):
        return grid[iy * nx + ix]

    def interp(a, b, va, vb):
        # position of `level` between the two samples
        if vb == va:
            return a
        t = (level - va) / (vb - va)
        return a + (b - a) * t

    segs = []
    for iy in range(ny - 1):
        for ix in range(nx - 1):
            v = [val(iy, ix), val(iy, ix + 1), val(iy + 1, ix + 1), val(iy + 1, ix)]
            if any(q is None for q in v):
                continue
            # corner coordinates: 0=TL 1=TR 2=BR 3=BL
            y0, y1 = lats[iy], lats[iy + 1]
            x0, x1 = lons[ix], lons[ix + 1]
            idx = sum((1 << k) for k, q in enumerate(v) if q >= level)
            if idx in (0, 15):
                continue

            # midpoints on each edge, in (lat, lon)
            top    = (y0, interp(x0, x1, v[0], v[1]))
            right  = (interp(y0, y1, v[1], v[2]), x1)
            bottom = (y1, interp(x0, x1, v[3], v[2]))
            left   = (interp(y0, y1, v[0], v[3]), x0)

            table = {
                1:  [(left, top)],      2:  [(top, right)],
                3:  [(left, right)],    4:  [(right, bottom)],
                5:  [(left, top), (right, bottom)],
                6:  [(top, bottom)],    7:  [(left, bottom)],
                8:  [(bottom, left)],   9:  [(bottom, top)],
                10: [(top, right), (bottom, left)],
                11: [(bottom, right)],  12: [(right, left)],
                13: [(right, top)],     14: [(top, left)],
            }
            segs.extend(table.get(idx, []))

    # stitch segments into polylines by matching endpoints
    key = lambda p: (round(p[0], 7), round(p[1], 7))
    starts = {}
    for a, b in segs:
        starts.setdefault(key(a), []).append((a, b))

    used = set()
    lines = []
    for i, (a, b) in enumerate(segs):
        if i in used:
            continue
        used.add(i)
        line = [a, b]
        # walk forward
        while True:
            nxt = None
            for j, (c, d) in enumerate(segs):
                if j in used:
                    continue
                if key(c) == key(line[-1]):
                    nxt = (j, d)
                    break
            if nxt is None:
                break
            used.add(nxt[0])
            line.append(nxt[1])
            if key(line[-1]) == key(line[0]):
                break
        lines.append(line)
    return lines


def simplify(pts, tol):
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
            px, py = pts[i]
            dx, dy = bx - ax, by - ay
            L = math.hypot(dx, dy) or 1e-12
            d = abs(dy * px - dx * py + bx * ay - by * ax) / L
            if d > worst:
                worst, idx = d, i
        if worst > tol and idx > 0:
            keep[idx] = True
            stack.append((s, idx))
            stack.append((idx, e))
    return [p for p, k in zip(pts, keep) if k]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=20.0,
                    help="contour interval in metres (default 20)")
    ap.add_argument("--index-every", type=int, default=5,
                    help="every Nth contour is an index line, drawn heavier")
    ap.add_argument("--spacing", type=float, default=45.0,
                    help="DEM sample spacing in metres")
    ap.add_argument("--pad", type=float, default=180.0,
                    help="metres of terrain beyond the course bbox")
    ap.add_argument("--tolerance", type=float, default=0.00002,
                    help="simplification tolerance in degrees")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    text = HTML.read_text(encoding="utf-8")
    track = read_track(text)

    lat0 = sum(p[0] for p in track) / len(track)
    dlat = args.spacing / 111320.0
    dlon = args.spacing / (111320.0 * math.cos(math.radians(lat0)))
    padlat = args.pad / 111320.0
    padlon = args.pad / (111320.0 * math.cos(math.radians(lat0)))

    la_min = min(p[0] for p in track) - padlat
    la_max = max(p[0] for p in track) + padlat
    lo_min = min(p[1] for p in track) - padlon
    lo_max = max(p[1] for p in track) + padlon

    lats = [la_min + i * dlat for i in range(int((la_max - la_min) / dlat) + 1)]
    lons = [lo_min + i * dlon for i in range(int((lo_max - lo_min) / dlon) + 1)]
    print(f"Sampling {len(lats)}x{len(lons)} = {len(lats)*len(lons)} points "
          f"at {args.spacing:.0f} m from USGS 10 m NED ...")

    grid = fetch_grid(lats, lons)
    good = [g for g in grid if g is not None]
    if not good:
        sys.exit("No elevation returned.")
    lo, hi = min(good), max(good)
    print(f"  elevation {lo:.0f}-{hi:.0f} m "
          f"({lo*3.28084:.0f}-{hi*3.28084:.0f} ft)")

    levels = []
    lvl = math.ceil(lo / args.interval) * args.interval
    while lvl < hi:
        levels.append(lvl)
        lvl += args.interval

    contours = []
    total_pts = 0
    for lv in levels:
        lines = marching_squares(grid, lats, lons, lv)
        paths = []
        for ln in lines:
            s = simplify(ln, args.tolerance)
            if len(s) >= 3:
                paths.append([[round(a, 6), round(b, 6)] for a, b in s])
        if not paths:
            continue
        idx = (round(lv / args.interval) % args.index_every) == 0
        contours.append({"ele": lv, "index": idx, "paths": paths})
        total_pts += sum(len(p) for p in paths)
        print(f"  {lv:6.0f} m  {len(paths):3d} lines"
              f"{'   (index)' if idx else ''}")

    print(f"\n{len(contours)} levels, {total_pts} points")

    src = ",\n".join(
        "    { ele:%g, index:%s, paths:[%s] }" % (
            c["ele"], "true" if c["index"] else "false",
            ",".join("[" + ",".join("[%s,%s]" % (p[0], p[1]) for p in path) + "]"
                     for path in c["paths"]))
        for c in contours
    )

    if not args.write:
        print("\nPreview only. Re-run with --write to patch the HTML.")
        return

    if "\n  contours: [" in text:
        new = re.sub(r"\n  contours: \[.*?\n  \],",
                     "\n  contours: [\n" + src + "\n  ],", text, count=1, flags=re.S)
    else:
        new = text.replace("\n  // Optional: other park trails for context.",
                           "\n  // Terrain. Vector contours from USGS 10 m NED, traced with\n"
                           "  // marching squares by scripts/fetch_terrain.py. Lines rather than a\n"
                           "  // hillshade image so the sheet stays self-contained and prints at any\n"
                           "  // size. `index` marks the heavier, labelled contours.\n"
                           "  contours: [\n" + src + "\n  ],\n"
                           "\n  // Optional: other park trails for context.", 1)
    if new == text:
        sys.exit("Nothing was replaced -- the DATA block markers moved?")
    HTML.write_text(new, encoding="utf-8")
    print(f"Patched {HTML.name}: {len(contours)} contour levels.")


if __name__ == "__main__":
    main()
