"""Build a phone-friendly labelling page from a run's shortlist.

    python scripts/build_label_page.py runs/thar --top 100

Writes runs/<run>/label_page.html: one self-contained HTML page (image chips
inlined as small JPEGs) for publishing as a private Artifact with the `db`
capability. Labels tapped on the page are saved to its database as
labels/<candidate id> = {label: "site" | "not" | "unsure", at: ISO time}, and
can be pulled back into a labels.csv for `moundfinder train`.

The page carries candidate coordinates, so it is written under runs/ (git-ignored)
and should stay private.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from moundfinder.export import satellite_link, shortlist  # noqa: E402
from moundfinder.pipeline import load_candidates  # noqa: E402

SOURCE_LABEL = {"both": "Height + surface", "dem": "Height", "spectral": "Surface"}


def chip(path: Path, size: int = 200) -> str | None:
    if not path.exists():
        return None
    img = Image.open(path).convert("RGB").resize((size, size), Image.BILINEAR)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=72, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def card_data(run: Path, cands: list[dict]) -> list[dict]:
    out = []
    for rank, c in enumerate(cands, 1):
        lat, lon = c["summit_lat"], c["summit_lon"]
        out.append({
            "id": c["id"],
            "rank": rank,
            "score": round(c["score"], 2),
            "source": c.get("source", "dem"),
            "height": c["peak_relief_m"],
            "area": c["area_ha"],
            "p": c.get("spectral_prob"),
            "flags": [f for f in (c.get("flags") or "").split(",") if f],
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "sat": satellite_link(lat, lon),
            "s2": chip(run / "chips" / f"{c['id']}_s2.png"),
            "relief": chip(run / "chips" / f"{c['id']}_relief.png"),
            "oldmap": chip(run / "chips" / f"{c['id']}_soi.png", size=260),
            "oldyear": c.get("soi_year"),
            "oldlabel": c.get("soi_label") or "",
            "oldlabel_m": c.get("soi_label_dist_m"),
        })
    return out


FLAG_TEXT = {
    "dune_field": "among dunes",
    "village": "village on top",
    "tree_canopy": "trees",
    "green_clump": "green in dry season",
    "water": "water",
    "linear_dune_or_bank": "linear",
    "no_pixel_data": "no surface data",
}


def build(run: Path, top: int) -> Path:
    cands = shortlist(load_candidates(run), top)
    data = card_data(run, cands)
    template = (ROOT / "scripts" / "label_page_template.html").read_text()
    page = template.replace("/*__CARDS__*/[]", json.dumps(data, separators=(",", ":")))
    page = page.replace("/*__FLAGS__*/{}", json.dumps(FLAG_TEXT))
    page = page.replace("__RUN__", html.escape(run.name))
    page = page.replace("__COUNT__", str(len(data)))
    out = run / "label_page.html"
    out.write_text(page)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--top", type=int, default=100)
    a = ap.parse_args()
    out = build(Path(a.run), a.top)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
