import numpy as np
from rasterio.transform import from_origin

from moundfinder.knownsites import KnownSite
from moundfinder.spectral import prob_blobs, sample_training, train_classifier, uncovered

PX = 1 / 3600


def grid(n=300):
    return from_origin(74.0, 29.5, PX, PX), n


def test_prob_blobs_finds_patch_and_reports_shape():
    tr, n = grid()
    prob = np.zeros((n, n), dtype=np.float32)
    prob[100:108, 150:158] = 0.9  # ~240 m square
    relief = np.zeros_like(prob)
    relief[103, 153] = 3.0
    blobs = prob_blobs(prob, relief, relief + 180, tr, 0.5, 0.5, 80, np.zeros_like(prob))
    assert len(blobs) == 1
    b = blobs[0]
    assert b["spectral_prob"] == 0.9 and b["source"] == "spectral"
    assert b["elongation"] < 1.3 and 4 < b["area_ha"] < 7
    assert b["peak_relief_m"] == 3.0


def test_uncovered_drops_blobs_next_to_dem_candidates():
    blobs = [{"lat": 29.40, "lon": 74.40}, {"lat": 29.45, "lon": 74.45}]
    cands = [{"lat": 29.4005, "lon": 74.4005}]  # ~70 m from the first blob
    left = uncovered(blobs, cands, 150)
    assert left == [blobs[1]]


def test_sample_training_and_classifier_learn_a_distinct_surface():
    tr, n = grid()
    rng = np.random.default_rng(0)
    feats = rng.normal(0, 1, (3, n, n)).astype(np.float32)
    sites = []
    # Five "mounds" whose first feature is shifted, like a brighter surface.
    for k, (r, c) in enumerate([(40, 40), (40, 200), (150, 120), (250, 60), (250, 240)]):
        feats[0, r - 4:r + 5, c - 4:c + 5] += 4
        lon, lat = tr.c + (c + 0.5) * PX, tr.f - (r + 0.5) * PX
        sites.append(KnownSite(f"site{k}", lat, lon, radius_m=120, precision_m=50))
    built = np.zeros((n, n), dtype=np.float32)
    X, y, g = sample_training(feats, tr, sites, built, rng, n_negative=3000, neg_clearance_m=600)
    assert y.sum() > 50 and (y == 0).sum() > 1000
    assert set(g[y == 1]) == {s.name for s in sites}

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        stats = train_classifier(X, y, g, ["a", "b", "c"], Path(d) / "m.pkl")
    assert stats["top_features"][0][0] == "a"
    assert all(r["percentile_vs_background"] > 90 for r in stats["held_out"])


def test_built_up_pixels_are_not_positives():
    tr, n = grid(120)
    feats = np.ones((2, n, n), dtype=np.float32)
    site = KnownSite("village_mound", tr.f - 60.5 * PX, tr.c + 60.5 * PX, radius_m=100, precision_m=50)
    built = np.ones((n, n), dtype=np.float32)
    X, y, g = sample_training(feats, tr, [site], built, np.random.default_rng(0), n_negative=100,
                              neg_clearance_m=200)
    assert y.sum() == 0
