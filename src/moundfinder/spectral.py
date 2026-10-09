"""Pixel classifier for mound soils, after Orengo et al. (PNAS 2020) in Cholistan.

In dune country a 2-3 m mound is lost among 10 m dunes in an elevation model,
but its surface is not sand: ash, pottery, brick and salts give it a different
colour and moisture behaviour in both the crop and the dry season. A random
forest learns that signature from the recorded sites, on per-pixel features:

* two seasonal Sentinel-2 composites (rabi crop peak and pre-monsoon dry season),
  six bands each plus NDVI and a bare-soil index;
* the same indices minus their ~330 m neighbourhood mean, so the model sees
  "different from its surroundings" rather than absolute colour;
* the DEM local relief, so height still counts where it is informative.

Everything runs on the 1 arc-second Copernicus DEM grid of a 1-degree tile.
Seasonal composites are built per MGRS tile at 20 m and cached.
"""

from __future__ import annotations

import logging
import math
import pickle
import warnings
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import Affine, xy
from rasterio.warp import reproject
from scipy import ndimage as ndi

from .geo import metres_per_degree
from .relief import _elongation, _solidity
from .remote import retry
from .sentinel2 import SCL_BAD, SceneIndex, _dataset, mgrs_tile, pick_scenes

log = logging.getLogger("moundfinder")

BANDS = ("blue", "green", "red", "nir", "swir16", "swir22")
SEASONS = ("crop", "dry")
S2_NATIVE = 10980  # 10 m pixels per MGRS tile side
S2_20M = S2_NATIVE // 2


def mgrs_tiles_for(bounds: tuple[float, float, float, float], step: float = 0.05) -> list[str]:
    minx, miny, maxx, maxy = bounds
    tiles = set()
    for lat in np.arange(miny + step / 2, maxy, step):
        for lon in np.arange(minx + step / 2, maxx, step):
            tiles.add(mgrs_tile(float(lat), float(lon)))
    return sorted(tiles)


def season_composite(index: SceneIndex, mgrs_id: str, season: str, cfg: dict, cache_dir: Path) -> Path | None:
    """Median of the clearest scenes of one season, 20 m, reflectance, NaN = no data."""
    out = Path(cache_dir) / "s2_composites" / f"{mgrs_id}_{season}.tif"
    if out.exists():
        return out
    scenes = pick_scenes(
        index.scenes(mgrs_id, cfg["years"], cfg[f"{season}_season_months"]),
        cfg["max_cloud_pct"], cfg.get("composite_scenes", 3),
    )
    if not scenes:
        log.warning("%s %s: no clear scenes", mgrs_id, season)
        return None
    # One band at a time across scenes keeps memory to a few hundred MB.
    def read(scene, name):
        def go():
            src = _dataset(scene["assets"][name]["href"])
            rs = Resampling.nearest if name == "scl" else Resampling.average
            return src.read(1, out_shape=(S2_20M, S2_20M), resampling=rs), src
        return retry(go, what=f"{scene['id']} {name} 20 m read")

    with ThreadPoolExecutor(max_workers=len(scenes)) as pool:
        scl = list(pool.map(lambda sc: read(sc, "scl"), scenes))
    bad = [np.isin(a, SCL_BAD) for a, _ in scl]
    ref = scl[0][1]
    transform = Affine(ref.transform.a * ref.width / S2_20M, ref.transform.b, ref.transform.c,
                       ref.transform.d, ref.transform.e * ref.height / S2_20M, ref.transform.f)
    out.parent.mkdir(parents=True, exist_ok=True)
    profile = dict(driver="GTiff", dtype="float32", count=len(BANDS), width=S2_20M, height=S2_20M, crs=ref.crs,
                   transform=transform, nodata=np.nan, compress="deflate", predictor=3, tiled=True)
    tmp = out.with_suffix(".part.tif")
    with rasterio.open(tmp, "w", **profile) as dst:
        for i, name in enumerate(BANDS, start=1):
            with ThreadPoolExecutor(max_workers=len(scenes)) as pool:
                raw = list(pool.map(lambda sc: read(sc, name)[0], scenes))
            stack = np.empty((len(scenes), S2_20M, S2_20M), dtype=np.float32)
            for k, (sc, data) in enumerate(zip(scenes, raw)):
                a = sc["assets"][name]
                stack[k] = data * np.float32(a["scale"]) + np.float32(a["offset"])
                stack[k][(data == 0) | bad[k]] = np.nan
            del raw
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                dst.write(np.nanmedian(stack, axis=0).astype(np.float32), i)
    tmp.replace(out)
    return out


def _nan_local_mean(img: np.ndarray, size: int) -> np.ndarray:
    valid = np.isfinite(img)
    filled = np.where(valid, img, 0).astype(np.float32)
    num = ndi.uniform_filter(filled, size)
    den = ndi.uniform_filter(valid.astype(np.float32), size)
    with np.errstate(invalid="ignore", divide="ignore"):
        return num / den


def tile_features(bounds, shape, transform, relief: np.ndarray, cfg: dict, cache_dir: Path,
                  index: SceneIndex | None = None) -> tuple[list[str], np.ndarray]:
    """Feature stack (F, H, W) on the DEM grid of a 1-degree tile."""
    index = index or SceneIndex(cache_dir)
    mgrs_ids = mgrs_tiles_for(bounds)
    log.info("composites for MGRS tiles %s", ", ".join(mgrs_ids))
    jobs = [(m, s) for m in mgrs_ids for s in SEASONS]
    # One composite at a time (each already reads its scenes in parallel) to bound memory.
    paths = {j: season_composite(index, j[0], j[1], cfg, cache_dir) for j in jobs}

    h, w = shape
    names, layers = [], []
    px_m = abs(transform.e) * metres_per_degree((bounds[1] + bounds[3]) / 2)[1]
    nbhd = max(3, int(round(330 / px_m)) | 1)
    for season in SEASONS:
        grid = np.full((len(BANDS), h, w), np.nan, dtype=np.float32)
        for m in mgrs_ids:
            p = paths.get((m, season))
            if p is None:
                continue
            with rasterio.open(p) as src:
                reproject(
                    source=src.read(), destination=grid, src_transform=src.transform, src_crs=src.crs,
                    src_nodata=np.nan, dst_transform=transform, dst_crs="EPSG:4326", dst_nodata=np.nan,
                    init_dest_nodata=False, resampling=Resampling.average,
                )
        b = dict(zip(BANDS, grid))
        with np.errstate(invalid="ignore", divide="ignore"):
            ndvi = (b["nir"] - b["red"]) / (b["nir"] + b["red"])
            bsi = ((b["swir16"] + b["red"]) - (b["nir"] + b["blue"])) / ((b["swir16"] + b["red"]) + (b["nir"] + b["blue"]))
        bright = (b["blue"] + b["green"] + b["red"]) / 3
        for name in BANDS:
            names.append(f"{season}_{name}")
            layers.append(b[name])
        for name, img in (("ndvi", ndvi), ("bsi", bsi), ("bright", bright), ("swir16", b["swir16"])):
            if name != "swir16":
                names.append(f"{season}_{name}")
                layers.append(img)
            names.append(f"{season}_{name}_contrast")
            layers.append(img - _nan_local_mean(img, nbhd))
    names.append("relief")
    layers.append(relief.astype(np.float32))
    return names, np.stack(layers).astype(np.float32)


def builtup_fraction(landcover, shape, transform) -> np.ndarray:
    """WorldCover built-up share resampled onto the DEM grid."""
    out = np.zeros(shape, dtype=np.float32)
    reproject(
        source=(landcover.data == 50).astype(np.float32), destination=out,
        src_transform=landcover.transform, src_crs="EPSG:4326",
        dst_transform=transform, dst_crs="EPSG:4326", resampling=Resampling.average,
    )
    return out


def sample_training(features: np.ndarray, transform, known, built: np.ndarray, rng: np.random.Generator,
                    n_negative: int = 20000, max_precision_m: float = 500, pos_radius_m: float = 150,
                    neg_clearance_m: float = 2000):
    """Positive pixels on recorded sites, negative pixels well away from any.

    Pixels under modern buildings are left out of the positives, so the model
    learns the mound surface rather than "village".
    """
    _, h, w = features.shape
    valid = np.all(np.isfinite(features), axis=0)
    lat0 = transform.f + transform.e * h / 2
    m_lon, m_lat = metres_per_degree(lat0)
    X, y, groups = [], [], []
    rows_idx, cols_idx = np.mgrid[:h, :w]
    for s in known:
        if s.precision_m > max_precision_m:
            continue
        col = (s.lon - transform.c) / transform.a
        row = (s.lat - transform.f) / transform.e
        if not (0 <= row < h and 0 <= col < w):
            continue
        r = min(s.radius_m, pos_radius_m)
        rr = int(math.ceil(r / (abs(transform.e) * m_lat))) + 1
        r0, r1 = max(int(row) - rr, 0), min(int(row) + rr + 1, h)
        c0, c1 = max(int(col) - rr, 0), min(int(col) + rr + 1, w)
        dy = (rows_idx[r0:r1, c0:c1] + 0.5 - row) * abs(transform.e) * m_lat
        dx = (cols_idx[r0:r1, c0:c1] + 0.5 - col) * abs(transform.a) * m_lon
        m = (np.hypot(dx, dy) <= r) & valid[r0:r1, c0:c1] & (built[r0:r1, c0:c1] < 0.3)
        pix = features[:, r0:r1, c0:c1][:, m].T
        if len(pix) == 0:
            continue
        X.append(pix)
        y.append(np.ones(len(pix), dtype=np.int8))
        groups += [s.name] * len(pix)

    # Negatives: random valid pixels at least `neg_clearance_m` from every recorded site.
    cand_r = rng.integers(0, h, n_negative * 3)
    cand_c = rng.integers(0, w, n_negative * 3)
    keep = valid[cand_r, cand_c]
    cand_r, cand_c = cand_r[keep], cand_c[keep]
    lons, lats = xy(transform, cand_r, cand_c)
    lons, lats = np.asarray(lons), np.asarray(lats)
    far = np.ones(len(cand_r), dtype=bool)
    for s in known:
        d = np.hypot((lons - s.lon) * m_lon, (lats - s.lat) * m_lat)
        far &= d > neg_clearance_m + s.precision_m
    cand_r, cand_c = cand_r[far][:n_negative], cand_c[far][:n_negative]
    X.append(features[:, cand_r, cand_c].T)
    y.append(np.zeros(len(cand_r), dtype=np.int8))
    # Spatial blocks of ~0.1 degree, so cross-validation never trains next door to its test pixels.
    bl_lon, bl_lat = np.asarray(xy(transform, cand_r, cand_c))
    groups += [f"bg_{a:.1f}_{b:.1f}" for a, b in zip(np.floor(bl_lon * 10) / 10, np.floor(bl_lat * 10) / 10)]
    return np.concatenate(X), np.concatenate(y), np.array(groups)


def train_classifier(X: np.ndarray, y: np.ndarray, groups: np.ndarray, names: list[str], out_path: Path) -> dict:
    """Fit the forest and report how each recorded site ranks when it is held out."""
    from sklearn.ensemble import RandomForestClassifier

    def make():
        return RandomForestClassifier(n_estimators=200, min_samples_leaf=5, max_features="sqrt",
                                      class_weight="balanced_subsample", n_jobs=-1, random_state=0)

    sites = sorted({g for g, t in zip(groups, y) if t == 1})
    bg = y == 0
    bg_blocks = np.unique(groups[bg])
    held_out = []
    for site in sites:
        # Hold out the site and a random fifth of the background blocks; score both
        # with a model that saw neither.
        rng = np.random.default_rng(zlib.crc32(site.encode()))
        test = groups == site
        if len(bg_blocks) >= 5:
            test_blocks = rng.choice(bg_blocks, size=len(bg_blocks) // 5, replace=False)
            bg_test = bg & np.isin(groups, test_blocks)
        else:  # too small an area for spatial blocks: hold out random background pixels
            bg_test = bg & (rng.random(len(y)) < 0.2)
        train = ~test & ~bg_test
        clf = make().fit(X[train], y[train])
        p_site = clf.predict_proba(X[test])[:, 1]
        p_bg = clf.predict_proba(X[bg_test])[:, 1]
        pct = float((p_bg < np.median(p_site)).mean() * 100)
        held_out.append({"site": site, "pixels": int(test.sum()), "median_prob": round(float(np.median(p_site)), 3),
                         "percentile_vs_background": round(pct, 1)})
        log.info("held out %s: median p=%.3f, beats %.1f%% of background", site, np.median(p_site), pct)

    clf = make().fit(X, y)
    importances = sorted(zip(names, clf.feature_importances_), key=lambda t: -t[1])
    with open(out_path, "wb") as f:
        pickle.dump({"clf": clf, "names": names}, f)
    return {"sites": len(sites), "positives": int(y.sum()), "negatives": int((y == 0).sum()),
            "held_out": held_out, "top_features": [(n, round(float(v), 3)) for n, v in importances[:10]]}


def predict(model: dict, names: list[str], features: np.ndarray, chunk_rows: int = 200) -> np.ndarray:
    if names != model["names"]:
        raise ValueError("feature names differ from the model's; rebuild features with the same settings")
    clf = model["clf"]
    _, h, w = features.shape
    prob = np.full((h, w), np.nan, dtype=np.float32)
    for r0 in range(0, h, chunk_rows):
        block = features[:, r0:r0 + chunk_rows].reshape(len(names), -1).T
        ok = np.all(np.isfinite(block), axis=1)
        out = np.full(len(block), np.nan, dtype=np.float32)
        if ok.any():
            out[ok] = clf.predict_proba(block[ok])[:, 1]
        prob[r0:r0 + chunk_rows] = out.reshape(-1, w)
    return prob


def prob_blobs(prob: np.ndarray, relief: np.ndarray, dem: np.ndarray, transform, threshold: float,
               min_area_ha: float, max_area_ha: float, relief_density: np.ndarray) -> list[dict]:
    """Connected patches of high mound probability, described like DEM candidates."""
    h, w = prob.shape
    lat0 = transform.f + transform.e * h / 2
    m_lon, m_lat = metres_per_degree(lat0)
    px_w, px_h = abs(transform.a) * m_lon, abs(transform.e) * m_lat
    px_area = px_w * px_h
    mask = np.nan_to_num(prob) >= threshold
    labels, _ = ndi.label(mask, structure=np.ones((3, 3), bool))
    out = []
    for idx, sl in enumerate(ndi.find_objects(labels), start=1):
        if sl is None:
            continue
        local = labels[sl] == idx
        npx = int(local.sum())
        area_ha = npx * px_area / 1e4
        if area_ha < min_area_ha or area_ha > max_area_ha:
            continue
        rr, cc = np.nonzero(local)
        rr, cc = rr + sl[0].start, cc + sl[1].start
        p = prob[rr, cc]
        wts = p / p.sum()
        r0, c0 = float((rr * wts).sum()), float((cc * wts).sum())
        lon, lat = xy(transform, r0, c0)
        k = int(np.argmax(relief[rr, cc]))
        s_lon, s_lat = xy(transform, rr[k], cc[k])
        hgt = relief[rr, cc]
        elong, orient = _elongation(rr * px_h, cc * px_w)
        out.append({
            "lon": round(float(lon), 6), "lat": round(float(lat), 6),
            "summit_lon": round(float(s_lon), 6), "summit_lat": round(float(s_lat), 6),
            "elevation_m": round(float(dem[rr[k], cc[k]]), 1),
            "peak_relief_m": round(float(hgt.max()), 2), "mean_relief_m": round(float(hgt.mean()), 2),
            "area_ha": round(area_ha, 2), "volume_m3": round(float(np.clip(hgt, 0, None).sum() * px_area), 0),
            "elongation": round(elong, 2), "orientation_deg": round(orient, 1),
            "solidity": round(_solidity(rr, cc, npx), 3),
            "relief_density": round(float(relief_density[int(round(r0)), int(round(c0))]), 4),
            "spectral_prob": round(float(p.max()), 4), "spectral_prob_mean": round(float(p.mean()), 4),
            "source": "spectral",
        })
    return out


def footprint_prob(cands: list[dict], prob: np.ndarray, transform) -> None:
    """Attach the highest mound probability within each DEM candidate's footprint."""
    h, w = prob.shape
    for c in cands:
        lat = c["lat"]
        m_lon, m_lat = metres_per_degree(lat)
        r = max(45.0, math.sqrt(c["area_ha"] * 1e4 / math.pi))
        col = (c["lon"] - transform.c) / transform.a
        row = (lat - transform.f) / transform.e
        rr = r / (abs(transform.e) * m_lat)
        rc = r / (abs(transform.a) * m_lon)
        win = prob[max(int(row - rr), 0):min(int(row + rr) + 1, h), max(int(col - rc), 0):min(int(col + rc) + 1, w)]
        c["spectral_prob"] = round(float(np.nanmax(win)), 4) if np.isfinite(win).any() else None
        c.setdefault("source", "dem")


def uncovered(blobs: list[dict], cands: list[dict], dist_m: float) -> list[dict]:
    """Spectral blobs with no DEM candidate within `dist_m`."""
    if not cands or not blobs:
        return list(blobs)
    from scipy.spatial import cKDTree

    m_lon, m_lat = metres_per_degree(blobs[0]["lat"])
    tree = cKDTree([(c["lon"] * m_lon, c["lat"] * m_lat) for c in cands])
    d, _ = tree.query([(b["lon"] * m_lon, b["lat"] * m_lat) for b in blobs])
    return [b for b, dd in zip(blobs, d) if dd > dist_m]
