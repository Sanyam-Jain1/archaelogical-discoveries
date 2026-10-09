"""Command line: `moundfinder scan | export | calibrate | train`."""

from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path

import yaml

from . import export, pipeline, scoring


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def cmd_scan(args, cfg):
    cands = pipeline.scan(cfg, args.aoi, Path(args.out), args.tiles, args.s2_top, Path(args.cache), args.model, args.workers)
    new = sum(1 for c in cands if not c["known_site"])
    print(f"{len(cands)} candidates ({new} not matching a recorded site) -> {args.out}/candidates.geojson")


def cmd_export(args, cfg):
    run = Path(args.run)
    cands = pipeline.load_candidates(run)
    export.write_csv(cands, run / "candidates.csv")
    short = export.shortlist(cands, args.top, args.include_known)
    export.write_kml(short, run / "shortlist.kml")
    export.write_gpx(short, run / "shortlist.gpx")
    export.write_review_html(run, short, run / "review.html")
    print(f"wrote candidates.csv, shortlist.kml, shortlist.gpx, review.html ({len(short)} candidates) in {run}")


def cmd_calibrate(args, cfg):
    rows = pipeline.calibration_report(cfg, pipeline.load_candidates(Path(args.run)), args.aoi)
    if not rows:
        print("no recorded sites fall inside the scanned area; add some to data/known_sites/")
        return
    for r in rows:
        print(json.dumps(r))
    found = sum(r["found"] for r in rows)
    print(f"recall: {found}/{len(rows)} recorded sites detected")


def cmd_train(args, cfg):
    run = Path(args.run)
    cands = pipeline.load_candidates(run)
    with open(args.labels, newline="") as f:
        labels = {row["id"]: int(row["label"]) for row in csv.DictReader(f)}
    stats = scoring.train(cands, labels, run / "model.pkl")
    print(f"trained on {stats['n']} candidates ({stats['positives']} positive), cross-validated AUC {stats['cv_auc']:.2f}")
    scoring.score_all(cands, cfg["scoring"]["weights"], run / "model.pkl")
    pipeline.save_candidates(cands, run)
    print("re-scored candidates with the model; run `export` again for a new shortlist")


def main(argv=None):
    p = argparse.ArgumentParser(prog="moundfinder", description=__doc__)
    p.add_argument("--config", default="config/settings.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="detect, filter, enrich and score candidates")
    s.add_argument("--aoi", default="thar_ghaggar_margin")
    s.add_argument("--tiles", nargs="*", help="1-degree tiles like N28E074 (default: all tiles in the AOI)")
    s.add_argument("--out", required=True)
    s.add_argument("--s2-top", type=int, default=200, help="Sentinel-2 checks for this many top DEM candidates per tile")
    s.add_argument("--cache", default="cache")
    s.add_argument("--model", help="trained model.pkl to score with")
    s.add_argument("--workers", type=int, default=6, help="parallel Sentinel-2 downloads")
    s.set_defaults(func=cmd_scan)

    e = sub.add_parser("export", help="write CSV, KML, GPX and an HTML review page")
    e.add_argument("run")
    e.add_argument("--top", type=int, default=50)
    e.add_argument("--include-known", action="store_true", help="also list candidates on recorded sites")
    e.set_defaults(func=cmd_export)

    c = sub.add_parser("calibrate", help="how well did the scan find recorded sites?")
    c.add_argument("run")
    c.add_argument("--aoi", default="thar_ghaggar_margin")
    c.set_defaults(func=cmd_calibrate)

    t = sub.add_parser("train", help="fit a classifier on labelled candidates and re-score")
    t.add_argument("run")
    t.add_argument("--labels", required=True, help="CSV with columns id,label (1 site, 0 not)")
    t.set_defaults(func=cmd_train)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(asctime)s %(message)s")
    args.func(args, load_config(args.config))


if __name__ == "__main__":
    main()
