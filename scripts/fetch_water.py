#!/usr/bin/env python3
"""
Pull streams and rivers for the course area and bake them into
rttr_course_map.html as DATA.water.

Source is the USGS National Hydrography Dataset (NHDPlus High Resolution),
the same layer the California State Parks map viewer uses. Stream order drives
line weight, so the San Lorenzo reads as a river and Eagle Creek reads as a
creek without anyone hand-tuning widths.

    python3 scripts/fetch_water.py            # preview
    python3 scripts/fetch_water.py --write

Stdlib only.
"""

import argparse
import json
import math
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HTML = Path(__file__).resolve().parent.parent / "rttr_course_map.html"
NHD = ("https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/"
       "NHDPlus_High_Resolution_9March2023_view/FeatureServer/0/query")
R_EARTH = 6378137.0


def read_track(text):
    m = re.search(r"\n  track: (\[\[.*?\]\]),\n", text, re.S)
    if not m:
        sys.exit("Could not find DATA.track in the HTML.")
    return json.loads(m.group(1))


def local_proj(lat0):
    kx = math.radians(1.0) * R_EARTH * math.cos(math.radians(lat0))
    ky = math.radians(1.0) * R_EARTH
    return lambda lat, lon: (lon * kx, lat * ky)


def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    d2 = dx * dx + dy * dy
    if d2 <= 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / d2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pad", type=float, default=260.0,
                    help="metres of water beyond the course bbox")
    ap.add_argument("--min-length", type=float, default=90.0,
                    help="drop stream fragments shorter than this, metres")
    ap.add_argument("--tolerance", type=float, default=5.0,
                    help="simplification tolerance, metres")
    ap.add_argument("--named-only", action="store_true", default=True,
                    help="drop unnamed headwater reaches (default). They are "
                         "real drainages but at this scale they read as stray "
                         "marks cutting across the sheet")
    ap.add_argument("--keep-unnamed", dest="named_only", action="store_false")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    text = HTML.read_text(encoding="utf-8")
    track = read_track(text)
    lat0 = sum(p[0] for p in track) / len(track)
    proj = local_proj(lat0)

    padlat = args.pad / 111320.0
    padlon = args.pad / (111320.0 * math.cos(math.radians(lat0)))
    bbox = (min(p[0] for p in track) - padlat, min(p[1] for p in track) - padlon,
            max(p[0] for p in track) + padlat, max(p[1] for p in track) + padlon)

    params = {
        "geometry": f"{bbox[1]:.6f},{bbox[0]:.6f},{bbox[3]:.6f},{bbox[2]:.6f}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326", "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "gnis_name,streamorde,ftype",
        "returnGeometry": "true",
        "f": "json",
    }
    print(f"Querying USGS NHD, bbox {bbox[0]:.4f},{bbox[1]:.4f},{bbox[2]:.4f},{bbox[3]:.4f} ...")
    req = urllib.request.Request(NHD + "?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": "rttr-course-map/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode())
    if "error" in data:
        sys.exit(f"NHD service error: {data['error']}")

    out = []
    for f in data.get("features", []):
        a = f.get("attributes") or {}
        # 460 is StreamRiver; the rest (pipelines, connectors) are not water
        # anyone can see from the trail.
        if a.get("ftype") != 460:
            continue
        name = (a.get("gnis_name") or "").strip() or None
        order = int(a.get("streamorde") or 1)
        # An unnamed order-1 reach is a seasonal headwater. Nobody navigates by
        # it and it clutters the sheet.
        if args.named_only and not name and order <= 1:
            continue
        for path in (f.get("geometry") or {}).get("paths", []):
            coords = [(p[1], p[0]) for p in path if len(p) >= 2]
            if len(coords) < 2:
                continue
            xy = [proj(la, lo) for la, lo in coords]
            if path_length(xy) < args.min_length:
                continue
            simp = simplify(xy, args.tolerance)
            idx = {id(p): i for i, p in enumerate(xy)}
            kept = [coords[idx[id(p)]] for p in simp]
            out.append({"name": name, "order": order,
                        "path": [[round(la, 6), round(lo, 6)] for la, lo in kept],
                        "len": path_length(xy)})

    out.sort(key=lambda w: (-w["order"], -w["len"]))
    print(f"  {len(out)} reaches, {sum(len(w['path']) for w in out)} points")
    for w in out:
        print(f"  order {w['order']}  {w['len']:6.0f} m  {len(w['path']):3d} pts  "
              f"{w['name'] or '(unnamed)'}")

    src = ",\n".join(
        "    { name:%s, order:%d, path:%s }" % (
            json.dumps(w["name"]) if w["name"] else "null", w["order"],
            "[" + ",".join("[%s,%s]" % (p[0], p[1]) for p in w["path"]) + "]")
        for w in out
    )

    if not args.write:
        print("\nPreview only. Re-run with --write to patch the HTML.")
        return

    if "\n  water: [" in text:
        new = re.sub(r"\n  water: \[.*?\n  \],",
                     "\n  water: [\n" + src + "\n  ],", text, count=1, flags=re.S)
    else:
        new = text.replace("\n  // Optional: other park trails for context.",
                           "\n  // Streams and rivers, from the USGS National Hydrography Dataset.\n"
                           "  // `order` is Strahler stream order and drives line weight, so the\n"
                           "  // San Lorenzo reads as a river and Eagle Creek reads as a creek.\n"
                           "  water: [\n" + src + "\n  ],\n"
                           "\n  // Optional: other park trails for context.", 1)
    if new == text:
        sys.exit("Nothing was replaced -- the DATA block markers moved?")
    HTML.write_text(new, encoding="utf-8")
    print(f"\nPatched {HTML.name}: {len(out)} reaches.")


if __name__ == "__main__":
    main()
