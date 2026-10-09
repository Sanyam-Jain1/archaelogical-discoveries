"""Sentinel-2 L2A evidence for each candidate, read straight from the public
`sentinel-cogs` bucket (the Earth Search archive) with no account or API key.

Two seasonal composites are built per candidate:

* crop season (Jan-Feb): in farmland an unploughed mound is a hole in the green,
  so a mound shows lower NDVI than the ring of fields around it;
* dry season (Apr-May): bare mound soils full of ash, pottery and salts differ
  in brightness and bare-soil index from the plain or dune sand around them.

Each feature is the contrast between a disc over the candidate and a ring
around it, scaled by the ring's variability.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import urllib.parse
import warnings
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import mgrs
import numpy as np
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.windows import from_bounds

from .remote import open_remote, retry

BUCKET = "https://sentinel-cogs.s3.us-west-2.amazonaws.com"
PREFIX = "sentinel-s2-l2a-cogs"
# Earth Search asset keys: B02, B03, B04, B08, B11 and the scene classification layer.
BANDS = ("blue", "green", "red", "nir", "swir16", "scl")
# SCL classes to drop: no data, saturated, cloud shadow, cloud (medium/high), cirrus, snow.
SCL_BAD = (0, 1, 3, 8, 9, 10, 11)
_S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
_MGRS = mgrs.MGRS()
log = logging.getLogger("moundfinder")

# Candidates near each other share COG blocks; keep them in GDAL's cache.
os.environ.setdefault("GDAL_CACHEMAX", "1024")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
os.environ.setdefault("VSI_CACHE", "TRUE")

# Opening a remote COG costs a round trip for its header, so each worker
# thread keeps its datasets open across candidates (rasterio handles are not
# shareable between threads).
_local = threading.local()


def _dataset(href: str):
    cache = getattr(_local, "datasets", None)
    if cache is None:
        cache = _local.datasets = {}
    if href not in cache:
        if len(cache) > 256:
            for ds in cache.values():
                ds.close()
            cache.clear()
        cache[href] = open_remote(f"/vsicurl/{href}")
    return cache[href]


def _forget(scene: dict) -> None:
    """Close this thread's handles on a scene so a retry starts from a fresh open."""
    cache = getattr(_local, "datasets", {})
    for asset in scene["assets"].values():
        ds = cache.pop(asset["href"], None)
        if ds is not None:
            ds.close()


def mgrs_tile(lat: float, lon: float) -> str:
    return _MGRS.toMGRS(lat, lon, MGRSPrecision=0)


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def _list_prefixes(prefix: str) -> list[str]:
    out, token = [], None
    while True:
        q = {"list-type": "2", "prefix": prefix, "delimiter": "/"}
        if token:
            q["continuation-token"] = token
        root = ET.fromstring(_get(f"{BUCKET}/?{urllib.parse.urlencode(q)}"))
        out += [p.text for p in root.iter(f"{_S3_NS}Prefix") if p.text != prefix]
        nxt = root.find(f"{_S3_NS}NextContinuationToken")
        if nxt is None:
            return out
        token = nxt.text


class SceneIndex:
    """Lists scenes per MGRS tile and season, caching listings and item JSON on disk."""

    def __init__(self, cache_dir: str | Path):
        self.cache = Path(cache_dir) / "s2"
        self.cache.mkdir(parents=True, exist_ok=True)

    def _cached_json(self, key: str, fetch):
        path = self.cache / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text())
        value = fetch()
        tmp = path.with_suffix(f".{threading.get_ident()}.part")
        tmp.write_text(json.dumps(value))
        tmp.replace(path)
        return value

    def scenes(self, tile: str, years: list[int], months: list[int]) -> list[dict]:
        zone, band, sq = tile[:2], tile[2], tile[3:5]
        found = []
        for year in years:
            for month in months:
                prefix = f"{PREFIX}/{zone}/{band}/{sq}/{year}/{month}/"
                names = self._cached_json(
                    f"list_{tile}_{year}_{month}", lambda p=prefix: _list_prefixes(p)
                )
                for scene_prefix in names:
                    found.append(self.item(scene_prefix))
        return [s for s in found if s is not None]

    def item(self, scene_prefix: str) -> dict | None:
        scene = scene_prefix.rstrip("/").rsplit("/", 1)[-1]

        def fetch():
            try:
                item = json.loads(_get(f"{BUCKET}/{scene_prefix}{scene}.json"))
            except Exception:
                return None
            p = item["properties"]
            # Earth Search re-processed scenes already have the -0.1 BOA offset of
            # processing baseline 04.00+ baked into the pixel values, yet still
            # advertise it in raster:bands. Applying it twice drives dark pixels negative.
            baked_in = bool(p.get("earthsearch:boa_offset_applied"))
            assets = {}
            for key, asset in item["assets"].items():
                rb = (asset.get("raster:bands") or [{}])[0]
                assets[key] = {
                    "href": asset["href"],
                    "scale": rb.get("scale", 1.0),
                    "offset": 0.0 if baked_in else rb.get("offset", 0.0),
                }
            epsg = p.get("proj:epsg") or int(str(p.get("proj:code", "EPSG:0")).split(":")[1])
            return {
                "id": scene,
                "datetime": p.get("datetime"),
                "cloud": p.get("eo:cloud_cover", 100),
                "nodata_pct": p.get("s2:nodata_pixel_percentage", 0),
                "epsg": epsg,
                "assets": assets,
            }

        return self._cached_json(f"item_{scene}", fetch)


def pick_scenes(scenes: list[dict], max_cloud: float, n: int) -> list[dict]:
    ok = [s for s in scenes if s["cloud"] <= max_cloud and s["nodata_pct"] < 40]
    return sorted(ok, key=lambda s: s["cloud"])[:n]


def read_chip(scene: dict, lon: float, lat: float, radius_m: float) -> dict[str, np.ndarray]:
    """Reflectance arrays on a 10 m grid centred on the point; masked pixels are NaN."""
    x, y = Transformer.from_crs("EPSG:4326", f"EPSG:{scene['epsg']}", always_xy=True).transform(lon, lat)
    bounds = (x - radius_m, y - radius_m, x + radius_m, y + radius_m)
    size = int(round(2 * radius_m / 10))
    out = {}
    for name in BANDS:
        asset = scene["assets"][name]
        src = _dataset(asset["href"])
        window = from_bounds(*bounds, transform=src.transform)
        data = src.read(
            1, window=window, out_shape=(size, size), boundless=True, fill_value=0,
            resampling=Resampling.nearest if name == "scl" else Resampling.bilinear,
        )
        if name == "scl":
            out["scl"] = data
        else:
            refl = data.astype(np.float32) * asset["scale"] + asset["offset"]
            refl[data == 0] = np.nan
            out[name] = refl
    bad = np.isin(out.pop("scl"), SCL_BAD)
    for arr in out.values():
        arr[bad] = np.nan
    return out


def composite(chips: list[dict[str, np.ndarray]]) -> dict[str, np.ndarray] | None:
    if not chips:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return {b: np.nanmedian(np.stack([c[b] for c in chips]), axis=0) for b in chips[0]}


def indices(c: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = (c["nir"] - c["red"]) / (c["nir"] + c["red"])
        bsi = ((c["swir16"] + c["red"]) - (c["nir"] + c["blue"])) / (
            (c["swir16"] + c["red"]) + (c["nir"] + c["blue"])
        )
    bright = (c["blue"] + c["green"] + c["red"]) / 3
    return {"ndvi": ndvi, "bsi": bsi, "bright": bright}


def disc_ring_contrast(img: np.ndarray, inner_m: float, ring_m: tuple[float, float], px_m: float = 10.0):
    """(inner mean, ring mean, (inner - ring) / ring std) for a centred chip."""
    n = img.shape[0]
    yy, xx = np.mgrid[:n, :n]
    r = np.hypot(yy - (n - 1) / 2, xx - (n - 1) / 2) * px_m
    inner = img[(r <= inner_m) & np.isfinite(img)]
    ring = img[(r >= ring_m[0]) & (r <= ring_m[1]) & np.isfinite(img)]
    if inner.size < 3 or ring.size < 10:
        return None, None, None
    mi, mr = float(inner.mean()), float(ring.mean())
    return mi, mr, (mi - mr) / (float(ring.std()) + 1e-3)


def candidate_features(index: SceneIndex, cand: dict, cfg: dict, chip_path: Path | None = None) -> dict:
    lat, lon = cand["lat"], cand["lon"]
    tile = mgrs_tile(lat, lon)
    radius = cfg["chip_radius_m"]
    inner = max(40.0, math.sqrt(cand["area_ha"] * 1e4 / math.pi))
    ring = (inner + 60, inner + 300)
    feats: dict = {"s2_tile": tile}

    for season in ("crop", "dry"):
        scenes = pick_scenes(
            index.scenes(tile, cfg["years"], cfg[f"{season}_season_months"]),
            cfg["max_cloud_pct"], cfg["max_scenes_per_season"],
        )
        chips = []
        for s in scenes:
            try:
                chips.append(retry(lambda s=s: read_chip(s, lon, lat, radius), what=f"{s['id']} chip",
                                   on_error=lambda s=s: _forget(s)))
            except Exception as e:
                log.warning("%s: skipping scene %s: %s", cand.get("id"), s["id"], str(e)[:120])
        comp = composite(chips)
        feats[f"{season}_scenes"] = len(chips)
        if comp is None:
            continue
        for name, img in indices(comp).items():
            mi, mr, z = disc_ring_contrast(img, inner, ring)
            if z is None:
                continue
            feats[f"{season}_{name}_in"] = round(mi, 4)
            feats[f"{season}_{name}_ring"] = round(mr, 4)
            feats[f"{season}_{name}_z"] = round(z, 3)
        if season == "dry" and chip_path is not None:
            save_rgb(comp, chip_path)
    return feats


def save_rgb(comp: dict[str, np.ndarray], path: Path) -> None:
    from PIL import Image

    rgb = np.dstack([comp["red"], comp["green"], comp["blue"]])
    finite = rgb[np.isfinite(rgb)]
    if finite.size == 0:
        return
    lo, hi = np.percentile(finite, [2, 98])
    img = np.clip((np.nan_to_num(rgb, nan=lo) - lo) / max(hi - lo, 1e-6), 0, 1)
    img = (img * 255).astype(np.uint8)
    _crosshair(img)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).resize((240, 240), Image.NEAREST).save(path)


def _crosshair(img: np.ndarray) -> None:
    c = img.shape[0] // 2
    for d in range(4, 9):
        for y, x in ((c - d, c), (c + d, c), (c, c - d), (c, c + d)):
            img[y, x] = (255, 40, 40)
