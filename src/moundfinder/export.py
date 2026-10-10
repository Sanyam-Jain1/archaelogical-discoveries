"""Shortlist outputs: CSV for spreadsheets, KML/GPX for phones, an HTML page for review."""

from __future__ import annotations

import csv
import html
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import rasterio
from rasterio.windows import from_bounds

from .geo import haversine_m, metres_per_degree

CSV_FIELDS = [
    "id", "score", "lat", "lon", "summit_lat", "summit_lon", "peak_relief_m", "area_ha", "elongation",
    "solidity", "relief_density", "lc_built", "lc_crop", "lc_bare", "lc_tree", "crop_ndvi_z", "dry_bright_z",
    "dry_bsi_z", "flags", "known_site", "border_km", "s2_tile",
]


def maps_link(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={lat:.6f},{lon:.6f}"


def satellite_link(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/@{lat:.6f},{lon:.6f},700m/data=!3m1!1e3"


def shortlist(cands: list[dict], top: int, include_known: bool = False, min_sep_m: float = 300) -> list[dict]:
    """The `top` best candidates, skipping any within `min_sep_m` of a better one.

    The surface classifier and the DEM can each outline the same mound as a
    separate candidate a hundred metres apart; it should be reviewed once.
    """
    pool = sorted((c for c in cands if include_known or not c.get("known_site")), key=lambda c: -c["score"])
    out = []
    for c in pool:
        if any(haversine_m(c["lat"], c["lon"], o["lat"], o["lon"]) < min_sep_m for o in out):
            continue
        out.append(c)
        if len(out) == top:
            break
    return out


def write_csv(cands: list[dict], path: Path) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for c in sorted(cands, key=lambda c: -c["score"]):
            w.writerow(c)


def _describe(c: dict) -> str:
    return (
        f"score {c['score']:.2f} | {c['peak_relief_m']} m high | {c['area_ha']} ha | "
        f"elongation {c['elongation']} | flags: {c.get('flags') or 'none'}"
    )


def write_kml(cands: list[dict], path: Path) -> None:
    marks = []
    for rank, c in enumerate(cands, 1):
        lat, lon = c["summit_lat"], c["summit_lon"]
        desc = (
            f"{_describe(c)}<br/>Ground check: look for pottery sherds, brick fragments, ash or slag "
            f"on the surface. Photograph, record, do not collect.<br/>"
            f'<a href="{maps_link(lat, lon)}">Navigate</a> | <a href="{satellite_link(lat, lon)}">Satellite</a>'
        )
        marks.append(
            f"<Placemark><name>{rank:03d} {escape(c['id'])}</name>"
            f"<description><![CDATA[{desc}]]></description>"
            f"<Point><coordinates>{lon:.6f},{lat:.6f},0</coordinates></Point></Placemark>"
        )
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        "<name>Mound candidates</name>" + "".join(marks) + "</Document></kml>\n"
    )


def write_gpx(cands: list[dict], path: Path) -> None:
    pts = [
        f'<wpt lat="{c["summit_lat"]:.6f}" lon="{c["summit_lon"]:.6f}"><name>{rank:03d} {escape(c["id"])}</name>'
        f"<desc>{escape(_describe(c))}</desc></wpt>"
        for rank, c in enumerate(cands, 1)
    ]
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="moundfinder" '
        'xmlns="http://www.topografix.com/GPX/1/1">' + "".join(pts) + "</gpx>\n"
    )


def relief_chip(run_dir: Path, c: dict, radius_m: float = 600) -> Path | None:
    """Grey-scale local-relief image around a candidate, from the scan's relief raster."""
    from PIL import Image

    src_path = run_dir / f"relief_{c['tile']}.tif"
    if not src_path.exists():
        return None
    m_lon, m_lat = metres_per_degree(c["lat"])
    dx, dy = radius_m / m_lon, radius_m / m_lat
    with rasterio.open(src_path) as src:
        win = from_bounds(c["lon"] - dx, c["lat"] - dy, c["lon"] + dx, c["lat"] + dy, src.transform)
        data = src.read(1, window=win, boundless=True, fill_value=0)
    img = (np.clip(data / 6.0, 0, 1) * 255).astype(np.uint8)
    out = run_dir / "chips" / f"{c['id']}_relief.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).resize((240, 240), Image.BILINEAR).save(out)
    return out


def write_review_html(run_dir: Path, cands: list[dict], path: Path) -> None:
    cards = []
    for rank, c in enumerate(cands, 1):
        relief = relief_chip(run_dir, c)
        s2 = run_dir / "chips" / f"{c['id']}_s2.png"
        imgs = ""
        if s2.exists():
            imgs += f'<figure><img src="chips/{s2.name}" alt="Sentinel-2 dry season"><figcaption>Sentinel-2, dry season</figcaption></figure>'
        if relief:
            imgs += f'<figure><img src="chips/{relief.name}" alt="Local relief"><figcaption>Local relief, 0-6 m</figcaption></figure>'
        lat, lon = c["summit_lat"], c["summit_lon"]
        flags = c.get("flags") or "none"
        cards.append(f"""
<article>
  <h2>#{rank} <code>{html.escape(c['id'])}</code> <span class="score">{c['score']:.2f}</span></h2>
  <div class="imgs">{imgs}</div>
  <dl>
    <dt>Height</dt><dd>{c['peak_relief_m']} m</dd>
    <dt>Area</dt><dd>{c['area_ha']} ha</dd>
    <dt>Elongation</dt><dd>{c['elongation']}</dd>
    <dt>Built-up</dt><dd>{c.get('lc_built', 0):.0%}</dd>
    <dt>Crop NDVI z</dt><dd>{c.get('crop_ndvi_z', '–')}</dd>
    <dt>Dry brightness z</dt><dd>{c.get('dry_bright_z', '–')}</dd>
    <dt>Flags</dt><dd>{html.escape(flags)}</dd>
  </dl>
  <p><a href="{satellite_link(lat, lon)}" target="_blank" rel="noopener">Satellite view</a> ·
     <a href="{maps_link(lat, lon)}" target="_blank" rel="noopener">Navigate</a> ·
     <span class="coord">{lat:.5f}, {lon:.5f}</span></p>
</article>""")
    path.write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mound Candidates</title>
<style>
:root {{ --bg:#faf8f4; --fg:#1d1b18; --muted:#6b655c; --card:#fff; --line:#e4dfd6; --accent:#9a4d1c; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#171512; --fg:#ece7df; --muted:#a39b8f; --card:#211e1a; --line:#38332c; --accent:#e0915a; }} }}
body {{ margin:0; padding:16px; background:var(--bg); color:var(--fg); font:15px/1.45 system-ui,sans-serif; }}
header {{ max-width:1200px; margin:0 auto 16px; }}
header p {{ color:var(--muted); margin:4px 0; }}
main {{ max-width:1200px; margin:0 auto; display:grid; gap:16px; grid-template-columns:repeat(auto-fill,minmax(min(100%,520px),1fr)); }}
article {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; }}
h2 {{ font-size:16px; margin:0 0 8px; display:flex; gap:8px; align-items:baseline; }}
.score {{ margin-left:auto; color:var(--accent); font-variant-numeric:tabular-nums; }}
.imgs {{ display:flex; gap:8px; flex-wrap:wrap; }}
figure {{ margin:0; }} img {{ width:240px; max-width:100%; height:auto; image-rendering:pixelated; border-radius:6px; display:block; }}
figcaption {{ font-size:12px; color:var(--muted); }}
dl {{ display:grid; grid-template-columns:max-content 1fr; gap:2px 12px; margin:10px 0; font-size:14px; }}
dt {{ color:var(--muted); }} dd {{ margin:0; font-variant-numeric:tabular-nums; }}
a {{ color:var(--accent); }} .coord {{ color:var(--muted); font-family:ui-monospace,monospace; font-size:13px; }}
</style></head><body>
<header><h1>Mound candidates</h1>
<p>{len(cands)} unrecorded candidates ranked by score. The red cross marks the candidate. Most will be dunes, kilns or village
sites: open the satellite view, then label each one in <code>labels.csv</code> (id,label with 1 = site, 0 = not).</p></header>
<main>{''.join(cards)}</main></body></html>
""")
