"""Candidate ranking.

Until there are field-checked labels, ranking is a transparent heuristic: each
component is a 0-1 ramp over a physically meaningful quantity, combined with
the weights in settings.yaml. Once labels exist, `train` fits a random forest
on the same features (the approach of Orengo et al. 2020 for Cholistan) and
its probability replaces the heuristic.
"""

from __future__ import annotations

import math
import pickle
from pathlib import Path

import numpy as np

FEATURES = [
    "peak_relief_m", "mean_relief_m", "area_ha", "volume_m3", "elongation", "solidity",
    "relief_density", "lc_built", "lc_tree", "lc_crop", "lc_bare", "lc_shrub",
    "crop_ndvi_z", "crop_ndvi_ring", "dry_bright_z", "dry_bsi_z", "dry_ndvi_z", "spectral_prob",
]


def ramp(x: float, lo: float, hi: float) -> float:
    return min(1.0, max(0.0, (x - lo) / (hi - lo)))


def components(c: dict) -> dict[str, float | None]:
    relief = ramp(c["peak_relief_m"], 1.5, 6.0)
    # Linear dunes, canal banks and roads are elongated; mounds are compact.
    shape = (1 - ramp(c["elongation"], 1.8, 3.5)) * (0.5 + 0.5 * ramp(c["solidity"], 0.5, 0.85))
    # A lone bump on a flat plain beats one bump among hundreds in a dune field.
    isolation = 1 - ramp(c["relief_density"], 0.05, 0.25)
    a = c["area_ha"]
    size = ramp(a, 0.5, 1.0) if a < 1 else (1 - ramp(a, 30, 80))
    return {"relief": relief, "shape": shape, "isolation": isolation, "size": size, "spectral": spectral(c),
            # Pixel classifier probability (spectral.py), where it has been run.
            "pixel": c.get("spectral_prob")}


def spectral(c: dict) -> float | None:
    """0-1 evidence that the candidate's surface differs from its surroundings."""
    have_crop = c.get("crop_ndvi_z") is not None
    have_dry = c.get("dry_bright_z") is not None
    if not (have_crop or have_dry):
        return None
    x = 0.0
    # NDVI deficit only means something where the surroundings are cropped.
    if have_crop and (c.get("crop_ndvi_ring") or 0) > 0.3:
        x += max(-c["crop_ndvi_z"], 0.0)
    if have_dry:
        x += 0.5 * max(abs(c["dry_bright_z"]), abs(c.get("dry_bsi_z") or 0.0))
    return 1 - math.exp(-x / 2)


def penalties(c: dict) -> tuple[float, list[str]]:
    mult, flags = 1.0, []
    # Buildings raise a surface model by several metres, so an inhabited village
    # looks like a mound. Many old villages here do sit on thehs, but those are
    # rarely unrecorded and cannot be checked without trespassing.
    if c.get("lc_built", 0) > 0.25:
        mult *= 0.3
        flags.append("village")
    if c.get("lc_tree", 0) > 0.25:
        mult *= 0.5
        flags.append("tree_canopy")
    # Groves too small for WorldCover: greener and darker than their surroundings even
    # in the April-May dry season, when a mound surface is bare and bright.
    dn_in, dn_ring = c.get("dry_ndvi_in"), c.get("dry_ndvi_ring")
    db_in, db_ring = c.get("dry_bright_in"), c.get("dry_bright_ring")
    if None not in (dn_in, dn_ring, db_in, db_ring) and dn_in - dn_ring > 0.05 and db_in < db_ring:
        mult *= 0.5
        flags.append("green_clump")
    if c.get("lc_water", 0) > 0.2:
        mult *= 0.3
        flags.append("water")
    if c["elongation"] > 3.5:
        flags.append("linear_dune_or_bank")
    if c["relief_density"] > 0.25:
        flags.append("dune_field")
    return mult, flags


def heuristic_score(c: dict, weights: dict[str, float], penalise: bool = True) -> float:
    comp = components(c)
    total = wsum = 0.0
    for k, w in weights.items():
        if comp.get(k) is None:
            continue
        total += w * comp[k]
        wsum += w
    mult = penalties(c)[0] if penalise else 1.0
    return round(mult * total / wsum, 4)


def score_all(cands: list[dict], weights: dict[str, float], model_path: str | Path | None = None) -> None:
    for c in cands:
        c["score_heuristic"] = heuristic_score(c, weights)
        # Without the village/tree/water penalties: how mound-like the shape alone is.
        # Many recorded mounds here carry a modern village, so calibration reports both.
        c["score_unpenalised"] = heuristic_score(c, weights, penalise=False)
        c["flags"] = ",".join(penalties(c)[1])
    if model_path:
        with open(model_path, "rb") as f:
            model = pickle.load(f)
        probs = model["clf"].predict_proba(_matrix(cands, model["fill"]))[:, 1]
        for c, p in zip(cands, probs):
            c["score_model"] = round(float(p), 4)
    for c in cands:
        c["score"] = c.get("score_model", c["score_heuristic"])


def _matrix(cands: list[dict], fill: dict[str, float]) -> np.ndarray:
    return np.array(
        [[c.get(f) if c.get(f) is not None else fill[f] for f in FEATURES] for c in cands], dtype=float
    )


def train(cands: list[dict], labels: dict[str, int], out_path: str | Path) -> dict:
    """Fit a random forest on labelled candidates (1 = site, 0 = not a site).

    Candidates matched to a recorded site count as positives unless labelled otherwise.
    """
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import cross_val_score

    y_by_id = {c["id"]: 1 for c in cands if c.get("known_site")}
    y_by_id.update(labels)
    rows = [c for c in cands if c["id"] in y_by_id]
    y = np.array([y_by_id[c["id"]] for c in rows])
    if min((y == 1).sum(), (y == 0).sum()) < 5:
        raise ValueError(f"need at least 5 positives and 5 negatives, have {(y == 1).sum()} / {(y == 0).sum()}")
    fill = {}
    for f in FEATURES:
        vals = [c[f] for c in rows if c.get(f) is not None]
        fill[f] = float(np.median(vals)) if vals else 0.0
    X = _matrix(rows, fill)
    clf = RandomForestClassifier(n_estimators=300, min_samples_leaf=2, class_weight="balanced", random_state=0)
    folds = int(min(5, (y == 1).sum(), (y == 0).sum()))
    auc = cross_val_score(clf, X, y, cv=folds, scoring="roc_auc") if folds >= 2 else np.array([np.nan])
    clf.fit(X, y)
    with open(out_path, "wb") as f:
        pickle.dump({"clf": clf, "fill": fill, "features": FEATURES}, f)
    return {"n": len(y), "positives": int(y.sum()), "cv_auc": float(np.nanmean(auc))}
