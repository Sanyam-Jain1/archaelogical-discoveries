import numpy as np
from rasterio.transform import from_origin, xy

from moundfinder.relief import detect_mounds
from moundfinder.scoring import heuristic_score

CFG = {
    "tophat_window_m": 700,
    "smooth_sigma_px": 1.0,
    "min_relief_m": 1.5,
    "min_area_ha": 0.5,
    "max_area_ha": 80,
    "context_window_m": 2000,
}
WEIGHTS = {"relief": 0.3, "shape": 0.2, "isolation": 0.2, "spectral": 0.2, "size": 0.1}
PX = 1 / 3600  # one arc-second, like Copernicus GLO-30


def synthetic_plain():
    """A gently tilted plain with one round mound and one linear dune."""
    rng = np.random.default_rng(0)
    n = 400
    yy, xx = np.mgrid[:n, :n].astype(float)
    dem = 180 + 0.002 * xx + rng.normal(0, 0.2, (n, n))
    # Mound: 5 m high, ~250 m across, centred at row 100, col 100.
    dem += 5 * np.exp(-(((yy - 100) ** 2 + (xx - 100) ** 2) / (2 * 3.0**2)))
    # Dune: 4 m high, ~2.5 km long, ~150 m wide, running east-west along row 300.
    dune = np.exp(-((yy - 300) ** 2) / (2 * 2.0**2)) * ((xx > 120) & (xx < 200))
    dem += 4 * dune
    transform = from_origin(74.0, 29.5, PX, PX)
    return dem.astype(np.float32), transform


def nearest(cands, row, col, transform):
    lon, lat = xy(transform, row, col)
    return min(cands, key=lambda c: (c["lon"] - lon) ** 2 + (c["lat"] - lat) ** 2)


def test_mound_found_and_compact():
    dem, tr = synthetic_plain()
    cands, relief = detect_mounds(dem, tr, CFG)
    mound = nearest(cands, 100, 100, tr)
    lon, lat = xy(tr, 100, 100)
    assert abs(mound["lon"] - lon) < 2 * PX and abs(mound["lat"] - lat) < 2 * PX
    assert 3.5 < mound["peak_relief_m"] < 5.5
    assert mound["elongation"] < 1.5
    assert relief.shape == dem.shape


def test_dune_is_elongated_and_ranks_below_mound():
    dem, tr = synthetic_plain()
    cands, _ = detect_mounds(dem, tr, CFG)
    mound = nearest(cands, 100, 100, tr)
    dune = nearest(cands, 300, 160, tr)
    assert dune["elongation"] > 3.5
    assert 75 < dune["orientation_deg"] < 105  # east-west
    assert heuristic_score(dune, WEIGHTS) < heuristic_score(mound, WEIGHTS)


def test_noise_alone_gives_no_candidates():
    rng = np.random.default_rng(1)
    dem = (180 + rng.normal(0, 0.2, (300, 300))).astype(np.float32)
    cands, _ = detect_mounds(dem, from_origin(74.0, 29.5, PX, PX), CFG)
    assert cands == []
