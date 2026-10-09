"""Import the GPS site tables of two village-to-village surveys into data/known_sites/.

* Pawar, Parmar & Sharan 2013, Heritage 1: 475-485 - Table 2, Harappan-related
  sites of Hanumangarh district (longitude, latitude, size in ha, culture sequence).
* Samunder & Dangi 2014, Heritage 2: 783-801 - Table 1, all 79 sites explored in
  Suratgarh tehsil (latitude, longitude, area in ha, culture sequence).

The PDFs are not redistributed: download them into data/raw/ (see
data/known_sites/SOURCES.md), then run

    python scripts/import_heritage_surveys.py

Needs `pdftotext` (poppler-utils). Rows whose position is far from the other
sites of the same tehsil are kept but flagged, with a wide precision, because
they are most likely typos in the table (e.g. 29 deg for 28 deg).
"""

from __future__ import annotations

import csv
import math
import re
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "known_sites" / "heritage_surveys.csv"

DMS = re.compile(r"(\d{2})\s*°?\s*(\d{2})\s*[’'ʹ]?\s*(\d{1,2}(?:[.,]\d+)?)\s*[”\"]?")
ROW = re.compile(r"^\s*(\d{1,3})\s+(\S.*)$")
TEHSILS = ("Nohar", "Rawatsar", "Bhadra", "Hanumangarh", "Pilibangan", "Sangria", "Tibbi")
PERIOD = re.compile(r"\b(Hakra|EH|MH|LH|PGW|BRW|HW|Hist|Med)\b")

PAWAR = ("Pawar et al. 2013, Heritage 1:475-485, Table 2 (Hanumangarh village survey, GPS)",
         "heritage_Volume1_475-485.pdf")
SAMUNDER = ("Samunder & Dangi 2014, Heritage 2:783-801, Table 1 (Suratgarh tehsil survey, GPS)",
            "heritage_Volume2_783-801.pdf")
# Named in the Suratgarh paper as already known before that survey.
SURATGARH_PREVIOUSLY_KNOWN = {"Ladana", "Birthwala‐1", "Chak 2 GDSM‐2", "Chak 7 SGM", "Chadshar"}


def text(pdf: Path) -> list[str]:
    out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def dms(m: re.Match) -> float:
    d, mi, s = m.groups()
    return int(d) + int(mi) / 60 + float(s.replace(",", ".")) / 3600


def parse(lines: list[str]) -> list[dict]:
    rows = []
    for i, line in enumerate(lines):
        m = ROW.match(line)
        if not m:
            continue
        coords = list(DMS.finditer(line))
        if len(coords) < 2:
            continue
        a, b = dms(coords[0]), dms(coords[1])
        lat, lon = (a, b) if a < b else (b, a)
        if not (27 < lat < 31 and 72 < lon < 77):
            continue
        head = line[m.start(2):coords[0].start()].strip()
        tehsil = next((t for t in TEHSILS if head.endswith(t)), "")
        name = head[: -len(tehsil)].strip() if tehsil else head
        # A wrapped row continues on the next line(s): in the left column for the name
        # ("Dabli Chugta/" + "Chakjhana", or an alias "(Chak 3 BMN)"), far right for
        # the culture sequence and references.
        extra_name, extra_tail = [], []
        for cont in lines[i + 1:i + 4]:
            if not cont.strip() or ROW.match(cont) or DMS.search(cont) or "Early Harappan" in cont:
                break  # blank, next row, or the table's legend
            indent = len(cont) - len(cont.lstrip())
            if indent < 15 and re.search(r"[A-Za-z]", cont):
                extra_name.append(cont.strip())
            else:
                extra_tail.append(cont.strip())
        if extra_name:
            name = " ".join([name] + extra_name).replace("/ ", "/")
        name = re.sub(r"[°\s]+$", "", name)
        tail = line[coords[1].end():]
        area = re.match(r"\s*(\d*\.?\d+)\s", tail + " ")
        order = "Hakra EH MH LH PGW BRW HW Hist Med".split()
        periods = sorted(set(PERIOD.findall(" ".join([tail] + extra_tail))), key=order.index)
        rows.append({"name": re.sub(r"\s+", " ", name), "tehsil": tehsil, "lat": lat, "lon": lon,
                     "area_ha": float(area.group(1)) if area else None, "periods": periods})
    return rows


def flag_outliers(rows: list[dict], key: str) -> None:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r[key] or "_all", []).append(r)
    for members in groups.values():
        if len(members) < 4:
            continue
        mlat = statistics.median(r["lat"] for r in members)
        mlon = statistics.median(r["lon"] for r in members)
        for r in members:
            r["outlier"] = abs(r["lat"] - mlat) > 0.45 or abs(r["lon"] - mlon) > 0.45


def to_csv_rows(rows: list[dict], source: str, district: str, new_by_survey: bool) -> list[list]:
    out = []
    for r in rows:
        radius = round(math.sqrt(r["area_ha"] * 1e4 / math.pi)) if r["area_ha"] else 100
        notes = [f"{district}{' / ' + r['tehsil'] if r['tehsil'] else ''}"]
        if r["area_ha"]:
            notes.append(f"{r['area_ha']:g} ha")
        if new_by_survey and r["name"].split(" (")[0] not in SURATGARH_PREVIOUSLY_KNOWN:
            notes.append("first recorded by this survey")
        precision = 100
        if r.get("outlier"):
            precision = 3000
            notes.append("position far from the other sites of its tehsil - probably a typo in the table; verify")
        out.append([r["name"], f"{r['lat']:.6f}", f"{r['lon']:.6f}", radius, precision,
                    ", ".join(r["periods"]), source, "; ".join(notes)])
    return out


def main() -> int:
    missing = [f for _, f in (PAWAR, SAMUNDER) if not (RAW / f).exists()]
    if missing:
        print(f"missing {missing} in {RAW}; see data/known_sites/SOURCES.md", file=sys.stderr)
        return 1
    hng = parse(text(RAW / PAWAR[1]))
    sgr = parse(text(RAW / SAMUNDER[1]))
    flag_outliers(hng, "tehsil")
    flag_outliers(sgr, "tehsil")
    rows = to_csv_rows(hng, PAWAR[0], "Hanumangarh", False) + to_csv_rows(sgr, SAMUNDER[0], "Sri Ganganagar / Suratgarh", True)
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "lat", "lon", "radius_m", "precision_m", "period", "source", "notes"])
        w.writerows(rows)
    flagged = [r[0] for r in rows if int(r[4]) > 100]
    print(f"{len(hng)} Hanumangarh + {len(sgr)} Suratgarh sites -> {OUT.relative_to(ROOT)}; flagged: {flagged}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
