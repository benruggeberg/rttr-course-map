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
                trailNamesDrawn: new Set([...document.querySelectorAll('.layer-trailname text')]
                    .map(n => n.textContent.trim()).filter(Boolean)).size,
                labelIssues: (typeof LABEL_ISSUES !== 'undefined' ? LABEL_ISSUES : []),
                edge: (() => {
                  // 0.25in printer margin, expressed in viewBox units.
                  const svg = document.getElementById('map');
                  const vb = svg.viewBox.baseVal;
                  const M = 0.25 / PAGE.w * vb.width;
                  const root = svg.getScreenCTM().inverse();
                  const out = [];
                  for (const g of svg.querySelectorAll(':scope > g')) {
                    if (getComputedStyle(g).display === 'none') continue;
                    const cls = g.getAttribute('class') || '';
                    for (const n of g.querySelectorAll('text,rect,circle,polygon,path,line')) {
                      let b; try { b = n.getBBox(); } catch (e) { continue; }
                      if (!b.width && !b.height) continue;
                      const m = root.multiply(n.getScreenCTM());
                      const xs = [], ys = [];
                      for (const [x, y] of [[b.x,b.y],[b.x+b.width,b.y],
                                            [b.x,b.y+b.height],[b.x+b.width,b.y+b.height]]) {
                        xs.push(m.a*x + m.c*y + m.e); ys.push(m.b*x + m.d*y + m.f);
                      }
                      const x0=Math.min(...xs), x1=Math.max(...xs);
                      const y0=Math.min(...ys), y1=Math.max(...ys);
                      if (x0 < M || y0 < M || x1 > vb.width-M || y1 > vb.height-M)
                        out.push({layer: cls, t: (n.textContent||n.tagName).trim().slice(0,26),
                                  x0:Math.round(x0), y0:Math.round(y0),
                                  x1:Math.round(x1), y1:Math.round(y1)});
                    }
                  }
                  return out;
                })(),
                offSheet: (typeof OFF_SHEET !== 'undefined' ? OFF_SHEET : []) };
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

            for it in res.get("labelIssues", []):
                print(f"  !! label {it['text']!r}: {it['issue']}")
            edge = res.get("edge", [])
            # background layers are clipped to the map area, so their raw
            # geometry crossing the margin is not a print risk
            edge = [e for e in edge
                    if e["layer"] not in ("layer-river", "layer-terrain",
                                          "layer-trails", "layer-rail", "layer-roads")]
            if edge:
                print(f"  !! {len(edge)} item(s) inside the 0.25in printer margin:")
                for e in edge[:12]:
                    print(f"       {e['layer']:<18} {e['t']!r} "
                          f"[{e['x0']},{e['y0']}]-[{e['x1']},{e['y1']}]")
            else:
                print("  edge check: nothing inside the 0.25in printer margin")
            for lb in res.get("offSheet", []):
                print(f"  !! marker {lb!r} plots off the map area")
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
