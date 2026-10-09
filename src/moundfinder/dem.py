"""Copernicus GLO-30 elevation tiles from the public AWS bucket.

GLO-30 is a 1 arc-second (~30 m) surface model. It sees large mounds (roughly
2 m+ high and 100 m+ across), but it is a *surface* model: trees and buildings
also show up as bumps, which the land-cover stage flags.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import rasterio
from rasterio.merge import merge

from .geo import one_degree_tiles
from .remote import open_remote

COP30_BASE = "https://copernicus-dem-30m.s3.amazonaws.com"

# Avoid GDAL listing S3 "directories" on every open.
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.tiff")


def cop30_url(tile: str) -> str:
    lat, lon = tile[1:3], tile[4:7]
    name = f"Copernicus_DSM_COG_10_N{lat}_00_E{lon}_00_DEM"
    return f"/vsicurl/{COP30_BASE}/{name}/{name}.tif"


def read_dem(bounds: tuple[float, float, float, float], cache_dir: str | Path | None = None):
    """Mosaic GLO-30 over (minx, miny, maxx, maxy) in lon/lat.

    Returns (elevation float32 array, affine transform). Whole 1-degree tiles are
    cached as GeoTIFFs under `cache_dir` so repeated runs do not re-download.
    """
    paths = [_cached_tile(t, cache_dir) for t in one_degree_tiles(bounds)]
    sources = [open_remote(p) for p in paths]
    try:
        arr, transform = merge(sources, bounds=bounds)
    finally:
        for s in sources:
            s.close()
    dem = arr[0].astype(np.float32)
    return dem, transform


def _cached_tile(tile: str, cache_dir) -> str:
    url = cop30_url(tile)
    if cache_dir is None:
        return url
    dest = Path(cache_dir) / "dem" / f"{tile}.tif"
    if dest.exists():
        return str(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open_remote(url) as src:
        profile = src.profile.copy()
        profile.update(driver="GTiff", compress="deflate", tiled=True, blockxsize=512, blockysize=512)
        data = src.read()
    tmp = dest.with_suffix(".part.tif")
    with rasterio.open(tmp, "w", **profile) as dst:
        dst.write(data)
    tmp.rename(dest)
    return str(dest)
