"""Per-tile scan: DEM detection -> filters -> land cover -> Sentinel-2 -> scoring."""

from __future__ import annotations

import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import rasterio
from shapely.geometry import Point, box

from . import dem as dem_mod
from .geo import BorderDistance, load_aoi, one_degree_tiles, tile_bounds
from .knownsites import load_known_sites, match
from .landcover import LandCover
from .relief import detect_mounds, local_relief, pixel_size_m, relief_context
from .scoring import score_all
from . import spectral
from .sentinel2 import SceneIndex, candidate_features, mgrs_tile

log = logging.getLogger("moundfinder")


def scan(cfg: dict, aoi_name: str, out_dir: Path, tiles: list[str] | None = None,
         s2_top: int = 200, cache_dir: Path = Path("cache"), model_path: str | None = None,
         workers: int = 6) -> list[dict]:
    aoi = load_aoi(cfg["aois"], aoi_name)
    tiles = tiles or [t for t in one_degree_tiles(aoi.bounds) if aoi.intersects(box(*tile_bounds(t)))]
    border = BorderDistance(cfg["border"])
    known = load_known_sites(cfg["known_sites"])
    out_dir.mkdir(parents=True, exist_ok=True)

    all_cands = load_candidates(out_dir) if (out_dir / "candidates.geojson").exists() else []
    done = {c["tile"] for c in all_cands}
    for tile in tiles:
        if tile in done:
            log.info("%s already scanned, skipping", tile)
            continue
        all_cands += scan_tile(cfg, tile, aoi, border, known, out_dir, s2_top, cache_dir, workers)
        score_all(all_cands, cfg["scoring"]["weights"], model_path)
        save_candidates(all_cands, out_dir)
    score_all(all_cands, cfg["scoring"]["weights"], model_path)
    save_candidates(all_cands, out_dir)
    return all_cands


def scan_tile(cfg, tile, aoi, border, known, out_dir, s2_top, cache_dir, workers=6) -> list[dict]:
    bounds = tile_bounds(tile)
    log.info("%s: reading DEM", tile)
    elev, transform = dem_mod.read_dem(bounds, cache_dir=cache_dir)
    cands, relief = detect_mounds(elev, transform, cfg["dem"])
    _save_relief(relief, transform, out_dir / f"relief_{tile}.tif")
    log.info("%s: %d relief blobs", tile, len(cands))

    buffer_km = cfg["border_buffer_km"]
    kept = []
    for i, c in enumerate(cands):
        if not aoi.contains(Point(c["lon"], c["lat"])):
            continue
        c["border_km"] = round(border.km(c["lon"], c["lat"]), 1)
        if c["border_km"] < buffer_km:
            continue
        c["id"] = f"{tile}-{i:05d}"
        c["tile"] = tile
        kept.append(c)
    match_known(kept, known, cfg["known_site_margin_m"])
    log.info("%s: %d inside AOI and outside the %g km border belt", tile, len(kept), buffer_km)

    log.info("%s: land cover", tile)
    lc = LandCover(bounds, cache_dir=cache_dir)
    for c in kept:
        # Sample the candidate's own footprint: a 200 m village diluted by a
        # wide circle of fields would otherwise pass as an empty mound.
        radius = max(cfg["landcover"]["min_radius_m"], math.sqrt(c["area_ha"] * 1e4 / math.pi))
        c.update(lc.fractions(c["lat"], c["lon"], radius))
    del lc

    # Sentinel-2 is the slow part, so only the best DEM candidates (plus every
    # recorded site, for calibration) get it.
    score_all(kept, cfg["scoring"]["weights"])
    ranked = sorted(kept, key=lambda c: -c["score"])
    to_enrich = ranked[:s2_top] + [c for c in ranked[s2_top:] if c["known_site"]]
    index = SceneIndex(cache_dir)
    # List scenes once per MGRS tile before fanning out, so workers hit the cache.
    for mgrs_id in sorted({mgrs_tile(c["lat"], c["lon"]) for c in to_enrich}):
        for season in ("crop", "dry"):
            index.scenes(mgrs_id, cfg["sentinel2"]["years"], cfg["sentinel2"][f"{season}_season_months"])

    def enrich(c):
        try:
            c.update(candidate_features(index, c, cfg["sentinel2"], out_dir / "chips" / f"{c['id']}_s2.png"))
        except Exception as e:  # network hiccups should not kill a long scan
            log.warning("%s: Sentinel-2 failed: %s", c["id"], e)

    # Neighbouring candidates share image blocks, so process them in spatial order.
    to_enrich.sort(key=lambda c: (round(c["lat"], 1), round(c["lon"], 1)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for n, _ in enumerate(pool.map(enrich, to_enrich), 1):
            if n % 25 == 0:
                log.info("%s: Sentinel-2 %d/%d", tile, n, len(to_enrich))
    return kept


def match_known(cands: list[dict], known, margin_m: float) -> None:
    for c in cands:
        site, dist = match(c["lat"], c["lon"], known, margin_m)
        c["known_site"] = site.name if site else ""
        c["known_site_dist_m"] = round(dist) if site else None


def refresh_known(cfg: dict, cands: list[dict]) -> None:
    """Re-match a finished scan against the current known-sites files (no downloads)."""
    match_known(cands, load_known_sites(cfg["known_sites"]), cfg["known_site_margin_m"])


def _save_relief(relief: np.ndarray, transform, path: Path) -> None:
    profile = dict(driver="GTiff", dtype="float32", count=1, width=relief.shape[1], height=relief.shape[0],
                   crs="EPSG:4326", transform=transform, compress="deflate", predictor=3, tiled=True)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.clip(relief, -5, 50).astype(np.float32), 1)


def save_candidates(cands: list[dict], out_dir: Path) -> None:
    feats = [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]}, "properties": c}
        for c in cands
    ]
    tmp = out_dir / "candidates.geojson.part"
    tmp.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    tmp.replace(out_dir / "candidates.geojson")


def load_candidates(out_dir: Path) -> list[dict]:
    data = json.loads((out_dir / "candidates.geojson").read_text())
    return [f["properties"] for f in data["features"]]


def calibration_report(cfg: dict, cands: list[dict], aoi_name: str, run_dir: Path | None = None) -> list[dict]:
    """For each recorded site the scan could have found: was it found, and how high did it rank?

    `max_relief_m` is the highest local relief within the site's radius + coordinate
    precision. A missed site with high relief there means the detector or filters
    dropped it; one with no relief is either levelled or has wrong coordinates.
    """
    refresh_known(cfg, cands)
    known = load_known_sites(cfg["known_sites"])
    aoi = load_aoi(cfg["aois"], aoi_name)
    border = BorderDistance(cfg["border"])
    tiles = {c["tile"] for c in cands}
    score_all(cands, cfg["scoring"]["weights"])
    ranked = sorted(cands, key=lambda c: -c["score"])
    rank_of = {c["id"]: i + 1 for i, c in enumerate(ranked)}
    raw_rank_of = {c["id"]: i + 1 for i, c in enumerate(sorted(cands, key=lambda c: -c["score_unpenalised"]))}
    rows = []
    for s in known:
        tile = f"N{int(s.lat):02d}E{int(s.lon):03d}"
        if tile not in tiles or not aoi.contains(Point(s.lon, s.lat)):
            continue
        if border.km(s.lon, s.lat) < cfg["border_buffer_km"]:
            continue
        hits = [c for c in cands if c["known_site"] == s.name]
        best = min(hits, key=lambda c: rank_of[c["id"]]) if hits else None
        best_raw = min(hits, key=lambda c: raw_rank_of[c["id"]]) if hits else None
        rows.append({
            "site": s.name,
            "found": bool(best),
            "rank": rank_of[best["id"]] if best else None,
            "rank_unpenalised": raw_rank_of[best_raw["id"]] if best_raw else None,
            "flags": best["flags"] if best else "",
            "of": len(cands),
            "percentile": round(100 * (1 - rank_of[best["id"]] / len(cands)), 1) if best else None,
            "peak_relief_m": best["peak_relief_m"] if best else None,
            "score": best["score"] if best else None,
            "max_relief_m": _max_relief(run_dir, tile, s) if run_dir else None,
        })
    return rows


def _max_relief(run_dir: Path, tile: str, site) -> float | None:
    path = run_dir / f"relief_{tile}.tif"
    if not path.exists():
        return None
    from rasterio.windows import from_bounds

    from .geo import metres_per_degree

    m_lon, m_lat = metres_per_degree(site.lat)
    r = site.radius_m + site.precision_m
    with rasterio.open(path) as src:
        win = from_bounds(site.lon - r / m_lon, site.lat - r / m_lat, site.lon + r / m_lon, site.lat + r / m_lat,
                          src.transform)
        data = src.read(1, window=win, boundless=True, fill_value=0)
    return round(float(data.max()), 2)


# --- Pixel classifier (see spectral.py) -------------------------------------------------


def tile_inputs(cfg: dict, tile: str, cache_dir: Path):
    """DEM, local relief, relief density and land cover for one 1-degree tile (all cached)."""
    bounds = tile_bounds(tile)
    elev, transform = dem_mod.read_dem(bounds, cache_dir=cache_dir)
    px_w, px_h = pixel_size_m(transform, (bounds[1] + bounds[3]) / 2)
    d = cfg["dem"]
    relief = local_relief(elev, px_w, px_h, d["tophat_window_m"], d.get("smooth_sigma_px", 1.0))
    density = relief_context(relief >= d["min_relief_m"], px_w, px_h, d["context_window_m"])
    return bounds, elev, transform, relief, density, LandCover(bounds, cache_dir=cache_dir)


def spectral_train(cfg: dict, tiles: list[str], model_path: Path, cache_dir: Path) -> dict:
    known = load_known_sites(cfg["known_sites"])
    rng = np.random.default_rng(0)
    Xs, ys, gs, names = [], [], [], None
    for tile in tiles:
        log.info("%s: building features", tile)
        bounds, elev, transform, relief, _, lc = tile_inputs(cfg, tile, cache_dir)
        names, feats = spectral.tile_features(bounds, elev.shape, transform, relief, cfg["sentinel2"], cache_dir)
        built = spectral.builtup_fraction(lc, elev.shape, transform)
        X, y, g = spectral.sample_training(feats, transform, known, built, rng,
                                           n_negative=cfg["spectral"]["negatives_per_tile"],
                                           pos_radius_m=cfg["spectral"]["positive_radius_m"])
        log.info("%s: %d positive pixels from %d sites, %d negatives", tile, int(y.sum()),
                 len({a for a, b in zip(g, y) if b}), int((y == 0).sum()))
        Xs.append(X), ys.append(y), gs.append(g)
        del feats
    model_path.parent.mkdir(parents=True, exist_ok=True)
    return spectral.train_classifier(np.concatenate(Xs), np.concatenate(ys), np.concatenate(gs), names, model_path)


def spectral_predict(cfg: dict, run_dir: Path, model_path: Path, aoi_name: str, cache_dir: Path,
                     tiles: list[str] | None = None) -> list[dict]:
    import pickle

    with open(model_path, "rb") as f:
        model = pickle.load(f)
    sc = cfg["spectral"]
    aoi = load_aoi(cfg["aois"], aoi_name)
    border = BorderDistance(cfg["border"])
    cands = load_candidates(run_dir)
    tiles = tiles or sorted({c["tile"] for c in cands})
    for tile in tiles:
        log.info("%s: predicting", tile)
        bounds, elev, transform, relief, density, lc = tile_inputs(cfg, tile, cache_dir)
        names, feats = spectral.tile_features(bounds, elev.shape, transform, relief, cfg["sentinel2"], cache_dir)
        prob = spectral.predict(model, names, feats)
        del feats
        _save_float(prob, transform, run_dir / f"prob_{tile}.tif")
        # Re-running replaces this tile's spectral-only candidates.
        cands = [c for c in cands if not (c["tile"] == tile and c.get("source") == "spectral")]
        tile_cands = [c for c in cands if c["tile"] == tile]
        spectral.footprint_prob(tile_cands, prob, transform)
        for c in tile_cands:
            c["source"] = "both" if (c.get("spectral_prob") or 0) >= sc["threshold"] else "dem"
        blobs = spectral.prob_blobs(prob, relief, elev, transform, sc["threshold"], sc["min_area_ha"],
                                    sc["max_area_ha"], density)
        blobs = spectral.uncovered(blobs, tile_cands, sc["merge_distance_m"])
        added = 0
        for i, b in enumerate(blobs):
            if not aoi.contains(Point(b["lon"], b["lat"])):
                continue
            b["border_km"] = round(border.km(b["lon"], b["lat"]), 1)
            if b["border_km"] < cfg["border_buffer_km"]:
                continue
            b["id"] = f"{tile}-S{i:05d}"
            b["tile"] = tile
            radius = max(cfg["landcover"]["min_radius_m"], math.sqrt(b["area_ha"] * 1e4 / math.pi))
            b.update(lc.fractions(b["lat"], b["lon"], radius))
            cands.append(b)
            added += 1
        log.info("%s: %d spectral-only candidates added", tile, added)
    refresh_known(cfg, cands)
    score_all(cands, cfg["scoring"]["weights"])
    save_candidates(cands, run_dir)
    return cands


def _save_float(arr: np.ndarray, transform, path: Path) -> None:
    profile = dict(driver="GTiff", dtype="float32", count=1, width=arr.shape[1], height=arr.shape[0],
                   crs="EPSG:4326", transform=transform, nodata=np.nan, compress="deflate", predictor=3, tiled=True)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr.astype(np.float32), 1)
