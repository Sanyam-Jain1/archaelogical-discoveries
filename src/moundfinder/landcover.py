"""Land-cover context from ESA WorldCover 10 m (2021, v200) on the public AWS bucket.

Used to flag the commonest false positives of a surface model: villages and
tree groves. A modern village on a mound can still be an ancient site (many
villages in this region sit on old thehs), so built-up candidates are flagged,
not dropped.
"""

from __future__ import annotations

import math
from pathlib import Path

import rasterio
from rasterio.windows import from_bounds

from .geo import metres_per_degree
from .remote import open_remote, retry

WORLDCOVER_BASE = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"

CLASSES = {
    10: "tree",
    20: "shrub",
    30: "grass",
    40: "crop",
    50: "built",
    60: "bare",
    80: "water",
    90: "wetland",
}


def worldcover_url(lat: float, lon: float) -> str:
    la = math.floor(lat / 3) * 3
    lo = math.floor(lon / 3) * 3
    return f"/vsicurl/{WORLDCOVER_BASE}/ESA_WorldCover_10m_2021_v200_N{la:02d}E{lo:03d}_Map.tif"


class LandCover:
    """WorldCover for one 1-degree tile, read once and sampled per candidate.

    A 1-degree tile never straddles WorldCover's 3-degree files, so one read suffices.
    """

    def __init__(self, bounds: tuple[float, float, float, float], cache_dir: str | Path | None = None):
        minx, miny, maxx, maxy = bounds
        cached = Path(cache_dir) / "worldcover" / f"{minx:.0f}_{miny:.0f}.tif" if cache_dir else None
        if cached and cached.exists():
            with rasterio.open(cached) as src:
                self.data, self.transform = src.read(1), src.transform
            return
        url = worldcover_url((miny + maxy) / 2, (minx + maxx) / 2)

        def read():
            with open_remote(url) as src:
                window = from_bounds(minx, miny, maxx, maxy, src.transform)
                return src.read(1, window=window, boundless=True, fill_value=0), src.window_transform(window)

        self.data, self.transform = retry(read, what="WorldCover read")
        if cached:
            cached.parent.mkdir(parents=True, exist_ok=True)
            profile = dict(driver="GTiff", dtype="uint8", count=1, width=self.data.shape[1],
                           height=self.data.shape[0], crs="EPSG:4326", transform=self.transform,
                           compress="deflate", tiled=True)
            with rasterio.open(cached, "w", **profile) as dst:
                dst.write(self.data, 1)

    def fractions(self, lat: float, lon: float, radius_m: float) -> dict[str, float]:
        m_lon, m_lat = metres_per_degree(lat)
        t = self.transform
        col, row = (lon - t.c) / t.a, (lat - t.f) / t.e
        rx = radius_m / m_lon / self.transform.a
        ry = radius_m / m_lat / -self.transform.e
        r0, r1 = max(int(row - ry), 0), int(row + ry) + 1
        c0, c1 = max(int(col - rx), 0), int(col + rx) + 1
        data = self.data[r0:r1, c0:c1]
        total = max(int((data > 0).sum()), 1)
        return {f"lc_{name}": round(float((data == code).sum()) / total, 3) for code, name in CLASSES.items()}
