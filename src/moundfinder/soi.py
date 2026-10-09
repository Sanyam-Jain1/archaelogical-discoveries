"""Old Survey of India one-inch maps (1:63,360, 1910s-1960s) as a historical layer.

The sheets come from the free "Old Survey of India Maps" collection on Zenodo,
indexed by its Map Selection spreadsheet. They show the land before canal
irrigation levelled much of it: villages, tanks, sand ridges, and the mounds
locals call theh, khera or dheri, often as place names. Green et al. (2019)
field-checked such map mounds in northwest India and found they mark older sites.

Sheet numbering: a 4-degree block (44 = 28-32 N, 72-76 E) splits into
1-degree sheets A-P, column by column from the north-west (A-D at 72-73 E,
north to south), and each of those into sixteen 15-minute one-inch sheets
numbered the same way (1-4 in the western column, north to south).

Georeferencing uses the sheet's neat line: its corners are the sheet's
15-minute corners, so a projective mapping through them (which absorbs scan
rotation and skew) is accurate to roughly 100 m, well inside the precision of
the maps themselves.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

BLOCKS = {"44": (72.0, 28.0)}  # block -> (west longitude, south latitude); 4 x 4 degrees
MOUND_TERMS = re.compile(r"\b(theh|thehr?i|khera|kheri|kheda|dheri|dhera|ruins?|mound|old\s*site|kot)\b", re.I)


def sheet_bounds(block: str, letter: str, number: int) -> tuple[float, float, float, float]:
    """(west, south, east, north) of a one-inch sheet such as 44 K/13."""
    w0, s0 = BLOCKS[block]
    li = "ABCDEFGHIJKLMNOP".index(letter.upper())
    deg_w = w0 + li // 4
    deg_n = s0 + 4 - li % 4
    ni = number - 1
    west = deg_w + 0.25 * (ni // 4)
    north = deg_n - 0.25 * (ni % 4)
    return (west, north - 0.25, west + 0.25, north)


def parse_name(name: str) -> tuple[str, str, int, int | None]:
    """'44 K]13 Hissar District (1914).jpg' -> ('44', 'K', 13, 1914)."""
    m = re.match(r"^\s*(\d{2})\s*([A-P])\]?\s*0?(\d{1,2})\b", name)
    if not m:
        raise ValueError(f"not a one-inch sheet name: {name!r}")
    year = re.search(r"\((\d{4})", name)
    return m.group(1), m.group(2), int(m.group(3)), int(year.group(1)) if year else None


@dataclass
class Sheet:
    name: str
    path: Path
    bounds: tuple[float, float, float, float]
    year: int | None
    # Pixel positions of the neat-line corners: NW, NE, SE, SW.
    corners: tuple[tuple[float, float], ...] | None = None

    def _h(self, inverse: bool = False) -> np.ndarray:
        import cv2

        w, s, e, n = self.bounds
        geo = np.float32([[w, n], [e, n], [e, s], [w, s]])
        px = np.float32(self.corners)
        return cv2.getPerspectiveTransform(geo, px) if not inverse else cv2.getPerspectiveTransform(px, geo)

    def to_pixel(self, lon: float, lat: float) -> tuple[float, float]:
        x, y, z = self._h() @ np.array([lon, lat, 1.0])
        return float(x / z), float(y / z)

    def to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        lon, lat, z = self._h(inverse=True) @ np.array([x, y, 1.0])
        return float(lon / z), float(lat / z)

    def contains(self, lon: float, lat: float) -> bool:
        w, s, e, n = self.bounds
        return w <= lon < e and s <= lat < n

    def scale_px_per_m(self) -> float:
        (x0, y0), (x1, y1) = self.corners[0], self.corners[1]
        w, s, e, n = self.bounds
        return float(np.hypot(x1 - x0, y1 - y0) / ((e - w) * 111320 * np.cos(np.radians((s + n) / 2))))


def download(sheets: list[dict], dest: Path) -> list[Path]:
    """Fetch sheet scans listed as {'name', 'url'} into dest (skips files already there)."""
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for s in sheets:
        p = dest / s["name"].replace("]", "_").replace(" ", "_")
        if not p.exists():
            tmp = p.with_suffix(".part")
            with urllib.request.urlopen(s["url"], timeout=600) as r, open(tmp, "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            tmp.rename(p)
        out.append(p)
    return out


def _load_gray(path: Path) -> tuple[np.ndarray, np.ndarray]:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    rgb = np.asarray(Image.open(path).convert("RGB"))
    return rgb, (rgb @ np.array([0.3, 0.59, 0.11])).astype(np.float32)


def find_frame(gray: np.ndarray, bounds) -> tuple[tuple[float, float], ...]:
    """Locate the neat line; return its corners (NW, NE, SE, SW) in pixels.

    Scans are often rotated by a fraction of a degree, so the four sides are found
    as long straight lines at any small angle (probabilistic Hough on a 1/4-scale
    copy) and intersected. Of all side combinations, the one whose shape best
    matches the sheet's ground footprint wins, which rejects borders, legend
    boxes and grid lines.
    """
    import cv2

    k = 4
    small = cv2.resize(gray, None, fx=1 / k, fy=1 / k, interpolation=cv2.INTER_AREA)
    h, w = small.shape
    dark = (small < 150).astype(np.uint8) * 255
    lines = cv2.HoughLinesP(dark, 1, np.pi / 1440, threshold=int(min(h, w) * 0.3),
                            minLineLength=int(min(h, w) * 0.45), maxLineGap=12)
    if lines is None:
        raise ValueError("no long lines found")
    horiz, vert = [], []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        ang = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(ang) < 2 or abs(abs(ang) - 180) < 2:
            horiz.append((x1, y1, x2, y2))
        elif abs(abs(ang) - 90) < 2:
            vert.append((x1, y1, x2, y2))

    def merge(segs, horizontal):
        """Collapse segments of the same line (offset within 3 px) and keep the longest span."""
        key = (lambda s: (s[1] + s[3]) / 2) if horizontal else (lambda s: (s[0] + s[2]) / 2)
        out = []
        for sg in sorted(segs, key=key):
            if out and abs(key(sg) - key(out[-1][0])) < 3:
                out[-1].append(sg)
            else:
                out.append([sg])
        fitted = []
        for group in out:
            pts = np.array([[p[0], p[1]] for g in group for p in (g[:2], g[2:])], dtype=float)
            span = np.ptp(pts[:, 0] if horizontal else pts[:, 1])
            if horizontal:
                a, b = np.polyfit(pts[:, 0], pts[:, 1], 1)  # y = a x + b
            else:
                a, b = np.polyfit(pts[:, 1], pts[:, 0], 1)  # x = a y + b
            fitted.append((a, b, span))
        return fitted

    H, V = merge(horiz, True), merge(vert, False)
    west, south, east, north = bounds
    expect = (east - west) * np.cos(np.radians((south + north) / 2)) / (north - south) * 1.0055

    def corner(hl, vl):
        ah, bh, _ = hl
        av, bv, _ = vl
        y = (ah * bv + bh) / (1 - ah * av)
        return av * y + bv, y

    best, best_err = None, 1e9
    for i, top in enumerate(H):
        for bot in H[i + 1:]:
            for j, lft in enumerate(V):
                for rgt in V[j + 1:]:
                    t, b = sorted([top, bot], key=lambda l: l[1])
                    l, r = sorted([lft, rgt], key=lambda l: l[1])
                    nw, ne, se, sw = corner(t, l), corner(t, r), corner(b, r), corner(b, l)
                    width = np.hypot(ne[0] - nw[0], ne[1] - nw[1])
                    height = np.hypot(sw[0] - nw[0], sw[1] - nw[1])
                    if width < w * 0.5 or height < h * 0.5:
                        continue
                    err = abs(width / height - expect) / expect
                    # Among frames that fit the footprint, prefer the larger (the neat line,
                    # not an inner grid box) and the better-supported sides.
                    score = err - 0.02 * (width * height) / (w * h) - 0.01 * min(t[2], b[2], l[2], r[2]) / max(w, h)
                    if err < 0.03 and score < best_err:
                        best_err, best = score, (nw, ne, se, sw)
    if best is None:
        raise ValueError("neat line not found")
    return tuple((float(x * k + k / 2), float(y * k + k / 2)) for x, y in best)


def open_sheet(path: Path, name: str) -> tuple[Sheet, np.ndarray, np.ndarray]:
    block, letter, num, year = parse_name(name)
    rgb, gray = _load_gray(path)
    sheet = Sheet(name, path, sheet_bounds(block, letter, num), year)
    sheet.corners = find_frame(gray, sheet.bounds)
    return sheet, rgb, gray


def clean_for_ocr(rgb: np.ndarray) -> np.ndarray:
    """Grey image with the magenta grid and hand colouring painted out."""
    r, g, b = (rgb[..., i].astype(np.int16) for i in range(3))
    gray = 0.3 * r + 0.59 * g + 0.11 * b
    colored = ((r - g) > 45) | ((b - g) > 25)
    return np.where(colored, 235, gray).astype(np.uint8)


def ocr_words(sheet: Sheet, rgb: np.ndarray, scale: float = 3.0, tile: int = 900, overlap: int = 150) -> list[dict]:
    """Every word Tesseract reads inside the neat line, with its position."""
    import cv2
    import pytesseract

    clean = clean_for_ocr(rgb)
    xs, ys_ = zip(*sheet.corners)
    xw, xe, yn, ys = int(min(xs)), int(max(xs)), int(min(ys_)), int(max(ys_))
    seen = {}
    # Two tile grids offset by half a tile: a label cut by one grid's edge is whole in the other.
    starts = [(ty, tx) for ty in range(yn, ys, tile - overlap) for tx in range(xw, xe, tile - overlap)]
    half = tile // 2
    starts += [(ty, tx) for ty in range(yn + half, ys, tile - overlap) for tx in range(xw + half, xe, tile - overlap)]
    for ty, tx in starts:
        t = clean[ty:min(ty + tile, ys), tx:min(tx + tile, xe)]
        t = cv2.resize(t, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        t = cv2.threshold(t, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        d = pytesseract.image_to_data(t, config="--psm 11", output_type=pytesseract.Output.DICT)
        for i, txt in enumerate(d["text"]):
            txt = txt.strip()
            if len(txt) < 3 or float(d["conf"][i]) < 45 or sum(ch.isalpha() for ch in txt) < 3:
                continue
            x = tx + (d["left"][i] + d["width"][i] / 2) / scale
            y = ty + (d["top"][i] + d["height"][i] / 2) / scale
            key = (txt.lower(), round(x / 60), round(y / 60))  # de-duplicate tile overlaps
            if key in seen:
                continue
            lon, lat = sheet.to_lonlat(x, y)
            seen[key] = {"text": txt, "lon": round(lon, 6), "lat": round(lat, 6), "conf": float(d["conf"][i]),
                         "sheet": sheet.name, "year": sheet.year}
    return list(seen.values())


def crop(sheet: Sheet, rgb: np.ndarray, lon: float, lat: float, half_m: float = 1000, out_px: int = 360):
    """A north-up map crop centred on (lon, lat) with a red ring marking the spot."""
    from PIL import Image, ImageDraw

    px_per_m = sheet.scale_px_per_m()
    x, y = sheet.to_pixel(lon, lat)
    r = half_m * px_per_m
    box = (int(x - r), int(y - r), int(x + r), int(y + r))
    img = Image.fromarray(rgb).crop(box).resize((out_px, out_px), Image.BILINEAR)
    d = ImageDraw.Draw(img)
    c = out_px / 2
    rr = out_px * 0.08
    d.ellipse((c - rr, c - rr, c + rr, c + rr), outline=(220, 20, 20), width=3)
    return img


def save_index(sheets: list[Sheet], path: Path) -> None:
    path.write_text(json.dumps([{"name": s.name, "path": str(s.path), "bounds": s.bounds, "year": s.year,
                                 "corners": s.corners} for s in sheets], indent=1))


def load_index(path: Path) -> list[Sheet]:
    return [Sheet(d["name"], Path(d["path"]), tuple(d["bounds"]), d["year"],
                  tuple(tuple(c) for c in d["corners"]) if d.get("corners") else None)
            for d in json.loads(path.read_text())]
