#!/usr/bin/env python3
"""
Render proofs of rttr_course_map.html so we can iterate against the image
rather than against the source.

    python3 scripts/render.py                    # both presets to PNG
    python3 scripts/render.py --pdf              # PNG + print-accurate PDF
    python3 scripts/render.py --preset volunteer --grayscale

Needs playwright (already in this machine's python env):
    python3 -m playwright install chromium
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "rttr_course_map.html"
OUT = ROOT / "render"

# Sheet inches per preset, mirroring PRESETS in the HTML.
PAGES = {"volunteer": (8.5, 11.0), "poster": (24.0, 36.0)}

# Layers to force on for a given preset, so a proof can be taken of a
# combination the preset does not ship with.
EXTRA_ON = {}


def render(preset, scale, want_pdf, grayscale, with_elev=False):
    from playwright.sync_api import sync_playwright

    w_in, h_in = PAGES[preset]
    OUT.mkdir(exist_ok=True)
    png = OUT / f"{preset}.png"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        # A viewport tall enough that the sheet lays out at a useful size; the
        # page fits the sheet to the window, so this drives on-screen scale.
        page = browser.new_page(
            viewport={"width": 1700, "height": 2100},
            device_scale_factor=scale,
        )
        page.goto(HTML.as_uri())
        page.wait_for_function("typeof applyPreset === 'function'")
        page.evaluate(f"applyPreset({preset!r})")
        page.evaluate(f"document.getElementById('presetSel').value = {preset!r}")
        if with_elev:
            page.evaluate("()=>{const cb=document.querySelector"
                          "('#controls input[data-layer=elev]');"
                          "cb.checked=true; cb.dispatchEvent(new Event('change'));}")
        # Webfonts must land before we shoot, or type metrics shift.
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(1200)

        page.locator("#sheet").screenshot(path=str(png))
        print(f"  {png.relative_to(ROOT)}")

        if want_pdf:
            pdf = OUT / f"{preset}.pdf"
            page.pdf(path=str(pdf), width=f"{w_in}in", height=f"{h_in}in",
                     print_background=True,
                     margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
            print(f"  {pdf.relative_to(ROOT)}")

        browser.close()

    if grayscale:
        gray = OUT / f"{preset}-gray.png"
        # sips ships with macOS, so no extra dependency for the mono check
        subprocess.run(
            ["sips", "-s", "format", "png", "-m", "/System/Library/ColorSync/Profiles/Generic Gray Gamma 2.2 Profile.icc",
             str(png), "--out", str(gray)],
            check=True, capture_output=True,
        )
        print(f"  {gray.relative_to(ROOT)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", choices=list(PAGES) + ["all"], default="all")
    ap.add_argument("--scale", type=float, default=2.0, help="device pixel ratio")
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--with-elev", action="store_true",
                    help="switch the elevation profile on, whatever the preset "
                         "does, so the volunteer sheet can be proofed with it")
    ap.add_argument("--grayscale", action="store_true",
                    help="also emit a true-grayscale PNG for the mono check")
    args = ap.parse_args()

    presets = list(PAGES) if args.preset == "all" else [args.preset]
    for name in presets:
        print(f"{name}:")
        render(name, args.scale, args.pdf, args.grayscale, args.with_elev)


if __name__ == "__main__":
    sys.exit(main())
