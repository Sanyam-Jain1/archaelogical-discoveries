"""Registry of already-recorded sites, used to separate rediscoveries from new candidates.

A candidate that falls on a recorded site is not thrown away: it is the
detector's evidence of recall, and a positive training example for the scorer.

CSV columns: name, lat, lon, radius_m, precision_m, period, source, notes.
`radius_m` is the site's extent; `precision_m` is how far off the published
coordinate may be.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .geo import haversine_m


@dataclass
class KnownSite:
    name: str
    lat: float
    lon: float
    radius_m: float
    precision_m: float
    source: str = ""


def load_known_sites(paths: list[str | Path]) -> list[KnownSite]:
    sites = []
    for path in paths:
        if not Path(path).exists():
            continue
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                sites.append(
                    KnownSite(
                        name=row["name"],
                        lat=float(row["lat"]),
                        lon=float(row["lon"]),
                        radius_m=float(row.get("radius_m") or 200),
                        precision_m=float(row.get("precision_m") or 500),
                        source=row.get("source", ""),
                    )
                )
    return sites


def match(lat: float, lon: float, sites: list[KnownSite], margin_m: float) -> tuple[KnownSite | None, float]:
    """Nearest known site whose (radius + precision + margin) covers the point."""
    best, best_d = None, float("inf")
    for s in sites:
        d = haversine_m(lat, lon, s.lat, s.lon)
        if d <= s.radius_m + s.precision_m + margin_m and d < best_d:
            best, best_d = s, d
    return best, best_d
