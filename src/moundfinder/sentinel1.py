"""Sentinel-1 radar layers for the pixel classifier, from Planetary Computer's
radiometrically terrain-corrected (RTC) collection.

Radar backscatter responds to surface roughness and moisture rather than colour.
Orengo et al. (2020) found that adding it to Sentinel-2 is what made Cholistan's
mounds separable from the desert around them. Per pixel, over a year of passes:
the median VV and VH backscatter (dB), their difference, and the temporal
spread of VV. A field swings with each crop cycle; a mound or a dune stays put.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
import warnings
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT

from .remote import retry

log = logging.getLogger("moundfinder")

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/token/sentinel1euwestrtc/sentinel1-grd-rtc"
LAYERS = ("s1_vv", "s1_vh", "s1_vv_minus_vh", "s1_vv_spread")


def _post(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


_token: dict = {}


def _sas_token() -> str:
    if not _token or _token["expires"] < time.time() + 600:
        with urllib.request.urlopen(SAS, timeout=60) as r:
            d = json.load(r)
        _token.update(token=d["token"], expires=time.time() + 3000)
    return _token["token"]


def search(bounds, start: str, end: str, limit: int = 200) -> list[dict]:
    w, s, e, n = bounds
    body = {"collections": ["sentinel-1-rtc"], "bbox": [w, s, e, n], "datetime": f"{start}/{end}", "limit": limit}
    items = _post(STAC, body).get("features", [])
    # One orbit direction keeps the viewing geometry consistent across passes.
    asc = [i for i in items if i["properties"].get("sat:orbit_state") == "ascending"]
    return asc or items


def _read_on_grid(href: str, shape, transform) -> np.ndarray:
    """Read a remote RTC COG resampled onto the target lon/lat grid (linear power, NaN = no data)."""
    url = f"/vsicurl/{href}?{_sas_token()}"

    def go():
        with rasterio.open(url) as src, WarpedVRT(src, crs="EPSG:4326", transform=transform,
                                                   width=shape[1], height=shape[0],
                                                   resampling=Resampling.average, src_nodata=src.nodata or 0,
                                                   nodata=np.nan, dtype="float32") as vrt:
            return vrt.read(1)

    return retry(go, what="Sentinel-1 read")


def tile_layers(bounds, shape, transform, cfg: dict, cache_dir: Path) -> dict[str, np.ndarray]:
    """Sentinel-1 layers on the DEM grid of one 1-degree tile, cached as .npz.

    cfg: start and end dates (ISO) and max_items (frames to read).
    """
    key = f"{bounds[0]:.0f}_{bounds[1]:.0f}"
    out = Path(cache_dir) / "s1" / f"{key}.npz"
    if out.exists():
        with np.load(out) as z:
            return {k: z[k] for k in LAYERS}
    # Each item is one frame of one pass and covers part of the tile; per-pixel
    # statistics over all of them use whichever passes saw that pixel.
    items = search(bounds, cfg["start"], cfg["end"])[: cfg["max_items"]]
    log.info("Sentinel-1: %d frames over %s", len(items), key)

    def stack(pol: str) -> np.ndarray:
        from concurrent.futures import ThreadPoolExecutor

        def one(it):
            try:
                a = _read_on_grid(it["assets"][pol]["href"], shape, transform)
            except Exception as e:
                log.warning("Sentinel-1 %s %s skipped: %s", it["id"], pol, str(e)[:120])
                return None
            with np.errstate(divide="ignore", invalid="ignore"):
                db = 10 * np.log10(np.clip(a, 1e-5, None))
            db[~np.isfinite(a)] = np.nan
            return db.astype(np.float32)

        with ThreadPoolExecutor(max_workers=4) as pool:
            arrs = [a for a in pool.map(one, items) if a is not None]
        if not arrs:
            raise RuntimeError(f"no Sentinel-1 data for {key}")
        return arrs

    def blockwise(arrs, fn) -> np.ndarray:
        """Apply a per-pixel statistic over the passes, 300 rows at a time to bound memory."""
        out = np.empty(shape, dtype=np.float32)
        for r0 in range(0, shape[0], 300):
            out[r0:r0 + 300] = fn(np.stack([a[r0:r0 + 300] for a in arrs]))
        return out

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        vv = stack("vv")
        layers = {
            "s1_vv": blockwise(vv, lambda x: np.nanmedian(x, axis=0)),
            "s1_vv_spread": blockwise(vv, lambda x: np.nanpercentile(x, 90, axis=0) - np.nanpercentile(x, 10, axis=0)),
        }
        del vv
        layers["s1_vh"] = blockwise(stack("vh"), lambda x: np.nanmedian(x, axis=0))
    layers["s1_vv_minus_vh"] = layers["s1_vv"] - layers["s1_vh"]
    layers = {k: layers[k].astype(np.float32) for k in LAYERS}
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, **layers)
    return layers
