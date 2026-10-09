"""Small geographic helpers shared by the pipeline stages."""

from __future__ import annotations

import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform as shp_transform, unary_union

EARTH_RADIUS_M = 6_371_008.8
# UTM 43N covers 72-78 E, which spans every AOI in this project.
METRIC_CRS = "EPSG:32643"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def metres_per_degree(lat: float) -> tuple[float, float]:
    """(metres per degree of longitude, metres per degree of latitude) at `lat`."""
    m_lat = 111_132.95 - 559.82 * math.cos(2 * math.radians(lat))
    m_lon = 111_412.84 * math.cos(math.radians(lat))
    return m_lon, m_lat


def load_geojson(path: str | Path) -> list[dict]:
    with open(path) as f:
        return json.load(f)["features"]


def load_aoi(path: str | Path, name: str):
    for feat in load_geojson(path):
        if feat["properties"].get("name") == name:
            return shape(feat["geometry"])
    names = [f["properties"].get("name") for f in load_geojson(path)]
    raise KeyError(f"AOI {name!r} not found in {path}; available: {names}")


class BorderDistance:
    """Distance in km from a lon/lat point to the international border."""

    def __init__(self, border_geojson: str | Path):
        geoms = [shape(f["geometry"]) for f in load_geojson(border_geojson)]
        to_metric = Transformer.from_crs("EPSG:4326", METRIC_CRS, always_xy=True).transform
        self._line = shp_transform(to_metric, unary_union(geoms))
        self._to_metric = to_metric

    def km(self, lon: float, lat: float) -> float:
        from shapely.geometry import Point

        x, y = self._to_metric(lon, lat)
        return self._line.distance(Point(x, y)) / 1000.0


def one_degree_tiles(bounds: tuple[float, float, float, float]) -> list[str]:
    """Names like 'N28E074' for every 1-degree tile touching (minx, miny, maxx, maxy)."""
    minx, miny, maxx, maxy = bounds
    tiles = []
    for lat in range(math.floor(miny), math.ceil(maxy)):
        for lon in range(math.floor(minx), math.ceil(maxx)):
            tiles.append(f"N{lat:02d}E{lon:03d}")
    return tiles


def tile_bounds(tile: str) -> tuple[float, float, float, float]:
    """'N28E074' -> (74, 28, 75, 29). Northern/eastern hemisphere only."""
    lat = int(tile[1:3])
    lon = int(tile[4:7])
    return (lon, lat, lon + 1, lat + 1)
