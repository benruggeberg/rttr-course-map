#!/usr/bin/env python3
"""
Sanity-check every marker against the course.

A coordinate typed or clicked by hand lands in the wrong place often enough
that it needs checking before race day: a post plotted off the route sends a
volunteer to a junction that does not exist.

    python3 scripts/check_markers.py
    python3 scripts/check_markers.py --tolerance 30

Reports each marker's distance to the nearest point on the route and its
distance along the course, and exits non-zero if any exceed --tolerance.
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

HTML = Path(__file__).resolve().parent.parent / "rttr_course_map.html"
R_EARTH = 6378137.0


def haversine(a, b):
    la1, lo1 = a
    la2, lo2 = b
    dla = math.radians(la2 - la1)
    dlo = math.radians(lo2 - lo1)
    x = (math.sin(dla / 2) ** 2
         + math.cos(math.radians(la1)) * math.cos(math.radians(la2)) * math.sin(dlo / 2) ** 2)
    return 2 * R_EARTH * math.asin(math.sqrt(x))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tolerance", type=float, default=30.0,
                    help="metres off-route before a marker is flagged")
    args = ap.parse_args()

    s = HTML.read_text(encoding="utf-8")
    track = json.loads(re.search(r"\n  track: (\[\[.*?\]\]),\n", s, re.S).group(1))

    # Markers are JS object literals, so pull the fields rather than JSON-parse.
    block = re.search(r"\n  markers: \[(.*?)\n  \],", s, re.S).group(1)
    markers = []
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        m = re.search(r"type:\"(\w+)\".*?at:\[\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\]", line)
        if not m:
            continue
        lab = re.search(r"label:\"([^\"]*)\"", line)
        markers.append({
            "type": m.group(1),
            "at": (float(m.group(2)), float(m.group(3))),
            "label": lab.group(1) if lab else "",
        })

    # Cumulative distance along the course, for the "at mile" column.
    cum = [0.0]
    for i in range(1, len(track)):
        cum.append(cum[-1] + haversine(track[i - 1], track[i]))

    print(f"{len(markers)} markers against {len(track)} track points "
          f"(tolerance {args.tolerance:.0f} m)\n")
    print(f"{'label':<22}{'type':<11}{'off route':>10}{'at mile':>9}")
    print("-" * 52)

    bad = 0
    for mk in markers:
        best, best_i = float("inf"), 0
        for i, p in enumerate(track):
            d = haversine(mk["at"], p)
            if d < best:
                best, best_i = d, i
        flag = ""
        if best > args.tolerance:
            flag = "  <-- CHECK"
            bad += 1
        print(f"{mk['label']:<22}{mk['type']:<11}{best:8.0f} m"
              f"{cum[best_i] / 1609.344:8.2f}{flag}")

    if bad:
        print(f"\n{bad} marker(s) more than {args.tolerance:.0f} m off the route. "
              f"That usually means a mis-click or a transposed coordinate.")
        return 1
    print("\nAll markers sit on the course.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
