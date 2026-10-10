"""Fetch ~1 m satellite crops (Esri World Imagery) around candidates for visual checking.

    python scripts/fetch_hires.py runs/thar --top 100
    python scripts/fetch_hires.py runs/thar --known Kalibangan Baror   # recorded sites, for comparison

Writes runs/<run>/chips/<id>_hr.png: a north-up crop `--half-m` metres either
side of the candidate, with a ring at the candidate's footprint radius and a
100 m scale bar. Tiles are cached in cache/esri/. Imagery: Esri, Maxar, Earthstar
Geographics; free for non-commercial viewing with attribution.
"""

from __future__ import annotations

import argparse
import io
import math
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from moundfinder.export import shortlist  # noqa: E402
from moundfinder.pipeline import load_candidates  # noqa: E402

URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
TILE = 256


def _pixel(lat: float, lon: float, z: int) -> tuple[float, float]:
    """Global Web Mercator pixel coordinates at zoom z."""
    n = TILE * 2 ** z
    x = (lon + 180) / 360 * n
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return x, y


def _tile(z: int, x: int, y: int, cache: Path) -> Image.Image:
    p = cache / f"{z}_{x}_{y}.jpg"
    if not p.exists():
        req = urllib.request.Request(URL.format(z=z, x=x, y=y), headers={"User-Agent": "moundfinder/0.1"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return Image.open(p).convert("RGB")


def crop(lat: float, lon: float, half_m: float, z: int, cache: Path, ring_m: float | None = None,
         out_px: int = 420) -> Image.Image:
    m_per_px = 156543.03392 * math.cos(math.radians(lat)) / 2 ** z
    cx, cy = _pixel(lat, lon, z)
    r = half_m / m_per_px
    x0, y0, x1, y1 = int(cx - r), int(cy - r), int(cx + r), int(cy + r)
    tx0, ty0, tx1, ty1 = x0 // TILE, y0 // TILE, x1 // TILE, y1 // TILE
    mosaic = Image.new("RGB", ((tx1 - tx0 + 1) * TILE, (ty1 - ty0 + 1) * TILE))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            mosaic.paste(_tile(z, tx, ty, cache), ((tx - tx0) * TILE, (ty - ty0) * TILE))
    img = mosaic.crop((x0 - tx0 * TILE, y0 - ty0 * TILE, x1 - tx0 * TILE, y1 - ty0 * TILE)).resize((out_px, out_px))
    d = ImageDraw.Draw(img)
    k = out_px / (2 * r)  # output pixels per mosaic pixel
    c = out_px / 2
    if ring_m:
        rr = ring_m / m_per_px * k
        d.ellipse((c - rr, c - rr, c + rr, c + rr), outline=(255, 60, 60), width=2)
    bar = 100 / m_per_px * k
    d.rectangle((8, out_px - 16, 8 + bar, out_px - 11), fill="white", outline="black")
    d.text((12 + bar, out_px - 20), "100 m", fill="white")
    return img


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--known", nargs="*", help="crop recorded sites matched in the run instead of the shortlist")
    ap.add_argument("--half-m", type=float, default=300)
    ap.add_argument("--zoom", type=int, default=17)
    ap.add_argument("--cache", default="cache/esri")
    a = ap.parse_args()
    run, cache = Path(a.run), ROOT / a.cache
    cands = load_candidates(run)
    if a.known:
        best = {}
        for c in sorted(cands, key=lambda c: -c["score"]):
            k = c.get("known_site")
            if k and any(n.lower() in k.lower() for n in a.known) and k not in best:
                best[k] = c
        todo = list(best.values())
    else:
        todo = shortlist(cands, a.top)
    out = run / "chips"
    out.mkdir(exist_ok=True)

    def one(c):
        ring = max(30.0, math.sqrt(c["area_ha"] * 1e4 / math.pi))
        img = crop(c["summit_lat"], c["summit_lon"], a.half_m, a.zoom, cache, ring)
        img.save(out / f"{c['id']}_hr.png")
        return c["id"]

    with ThreadPoolExecutor(max_workers=6) as pool:
        done = list(pool.map(one, todo))
    print(f"{len(done)} high-resolution crops in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
