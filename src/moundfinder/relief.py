"""Mound detection on a DEM with a white top-hat local relief model.

The top-hat (surface minus its morphological opening) keeps anything narrower
than the window at full height and removes broad landforms, which is what a
settlement mound on an alluvial plain looks like. Each connected patch of
relief becomes a candidate with shape measurements the scorer uses to tell
compact mounds from linear dunes, canal banks and dune fields.
"""

from __future__ import annotations

import math

import numpy as np
from rasterio.transform import xy
from scipy import ndimage as ndi
from scipy.spatial import ConvexHull, QhullError

from .geo import metres_per_degree


def pixel_size_m(transform, centre_lat: float) -> tuple[float, float]:
    m_lon, m_lat = metres_per_degree(centre_lat)
    return abs(transform.a) * m_lon, abs(transform.e) * m_lat


def _odd(n: float) -> int:
    n = max(3, int(round(n)))
    return n if n % 2 else n + 1


def local_relief(dem: np.ndarray, px_w: float, px_h: float, window_m: float, sigma_px: float) -> np.ndarray:
    """Height above the morphological opening of the lightly smoothed DEM."""
    z = np.where(np.isfinite(dem), dem, np.nanmedian(dem)).astype(np.float32)
    if sigma_px > 0:
        z = ndi.gaussian_filter(z, sigma_px)
    size = (_odd(window_m / px_h), _odd(window_m / px_w))
    return z - ndi.grey_opening(z, size=size)


def relief_context(mask: np.ndarray, px_w: float, px_h: float, window_m: float) -> np.ndarray:
    """Share of the surrounding window that is relief: high in dune fields, low on plains."""
    return ndi.uniform_filter(mask.astype(np.float32), size=(_odd(window_m / px_h), _odd(window_m / px_w)))


def detect_mounds(dem: np.ndarray, transform, cfg: dict) -> tuple[list[dict], np.ndarray]:
    """Return (candidates, relief raster) for a DEM in geographic coordinates."""
    rows, cols = dem.shape
    centre_lat = transform.f + transform.e * rows / 2
    px_w, px_h = pixel_size_m(transform, centre_lat)
    px_area = px_w * px_h

    relief = local_relief(dem, px_w, px_h, cfg["tophat_window_m"], cfg.get("smooth_sigma_px", 1.0))
    mask = relief >= cfg["min_relief_m"]
    labels, n = ndi.label(mask, structure=np.ones((3, 3), bool))

    relief_density = relief_context(mask, px_w, px_h, cfg["context_window_m"])

    min_px = cfg["min_area_ha"] * 1e4 / px_area
    max_px = cfg["max_area_ha"] * 1e4 / px_area

    candidates = []
    for idx, sl in enumerate(ndi.find_objects(labels), start=1):
        if sl is None:
            continue
        local = labels[sl] == idx
        npx = int(local.sum())
        if npx < min_px or npx > max_px:
            continue
        rr, cc = np.nonzero(local)
        rr = rr + sl[0].start
        cc = cc + sl[1].start
        h = relief[rr, cc]

        w = h / h.sum()
        r0 = float((rr * w).sum())
        c0 = float((cc * w).sum())
        lon, lat = xy(transform, r0, c0)
        k = int(h.argmax())
        s_lon, s_lat = xy(transform, rr[k], cc[k])

        elong, orient = _elongation(rr * px_h, cc * px_w)
        candidates.append(
            {
                "lon": round(float(lon), 6),
                "lat": round(float(lat), 6),
                "summit_lon": round(float(s_lon), 6),
                "summit_lat": round(float(s_lat), 6),
                "elevation_m": round(float(dem[rr[k], cc[k]]), 1),
                "peak_relief_m": round(float(h.max()), 2),
                "mean_relief_m": round(float(h.mean()), 2),
                "area_ha": round(npx * px_area / 1e4, 2),
                "volume_m3": round(float(h.sum() * px_area), 0),
                "elongation": round(elong, 2),
                "orientation_deg": round(orient, 1),
                "solidity": round(_solidity(rr, cc, npx), 3),
                "relief_density": round(float(relief_density[int(round(r0)), int(round(c0))]), 4),
            }
        )
    return candidates, relief


def _elongation(y: np.ndarray, x: np.ndarray) -> tuple[float, float]:
    """Major/minor axis ratio and major-axis bearing (degrees from north)."""
    if len(x) < 4:
        return 1.0, 0.0
    cov = np.cov(np.vstack([x - x.mean(), y - y.mean()]))
    vals, vecs = np.linalg.eigh(cov)
    minor, major = max(vals[0], 1e-6), max(vals[1], 1e-6)
    vx, vy = vecs[:, 1]
    # Rows grow southwards, so flip y to get a compass bearing.
    bearing = math.degrees(math.atan2(vx, -vy)) % 180
    return math.sqrt(major / minor), bearing


def _solidity(rr: np.ndarray, cc: np.ndarray, npx: int) -> float:
    if npx < 3:
        return 1.0
    corners = np.concatenate(
        [np.c_[cc + dx, rr + dy] for dx in (0, 1) for dy in (0, 1)]
    ).astype(float)
    try:
        hull_area = ConvexHull(corners).volume
    except QhullError:
        return 1.0
    return min(1.0, npx / hull_area)
