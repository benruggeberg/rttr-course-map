#!/usr/bin/env python3
"""
Count how many route points fall underneath each furniture panel.

The rule this enforces: a panel may float over the map only where the course
does not go. Bottom-right once held 104 route points, which is why the legend
moved in the first place. Re-run this after moving any panel rather than
eyeballing the render.

    python3 scripts/check_layout.py

Exits non-zero if any panel covers route, so it can gate a commit.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "rttr_course_map.html"

PRESETS = ["volunteer", "poster"]

# Panels to test, by the layer class the renderer puts them in.
PANELS = ["layer-legend", "layer-elev", "layer-scale", "layer-compass", "layer-brief"]

# Measured in viewBox units. A little slack so a label that merely grazes a
# panel edge still gets reported.
PAD = 4

JS = """
(panels) => {
  const out = { points: [], panels: {},
                trailNames: DATA.trailNames.length,
                trailNamesDrawn: document.querySelectorAll('.layer-trailname text').length };
  // The projected route, straight from the live projection.
  for (const [la, lo] of TRACK) out.points.push(PROJ.toXY(la, lo));
  for (const cls of panels) {
    const g = document.querySelector('.' + cls);
    if (!g || !g.getBBox) { out.panels[cls] = null; continue; }
    // hidden layers report an empty box; skip them
    const vis = getComputedStyle(g).display !== 'none';
    const b = g.getBBox();
    out.panels[cls] = vis && b.width > 0 ? {x: b.x, y: b.y, w: b.width, h: b.height} : null;
  }
  return out;
}
"""


def main():
    from playwright.sync_api import sync_playwright

    failures = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1700, "height": 2100})
        page.goto(HTML.as_uri())
        page.wait_for_function("typeof applyPreset === 'function'")

        for preset in PRESETS:
            page.evaluate(f"applyPreset({preset!r})")
            page.wait_for_timeout(400)
            res = page.evaluate(JS, PANELS)
            pts = res["points"]

            dropped = res["trailNames"] - res["trailNamesDrawn"]
            print(f"\n{preset}  ({len(pts)} route points, "
                  f"{res['trailNamesDrawn']}/{res['trailNames']} trail names placed"
                  + (f", {dropped} dropped as unplaceable)" if dropped else ")"))
            for cls, box in res["panels"].items():
                if box is None:
                    print(f"  {cls:<16} hidden")
                    continue
                x0, y0 = box["x"] - PAD, box["y"] - PAD
                x1, y1 = box["x"] + box["w"] + PAD, box["y"] + box["h"] + PAD
                n = sum(1 for x, y in pts if x0 <= x <= x1 and y0 <= y <= y1)
                verdict = "clear" if n == 0 else f"*** COVERS {n} ROUTE POINTS ***"
                if n:
                    failures += 1
                print(f"  {cls:<16} {box['w']:6.0f} x {box['h']:5.0f} at "
                      f"({box['x']:6.0f},{box['y']:6.0f})  {verdict}")

        browser.close()

    if failures:
        print(f"\n{failures} panel/preset combinations overlap the route.")
        return 1
    print("\nAll panels clear of the route.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
