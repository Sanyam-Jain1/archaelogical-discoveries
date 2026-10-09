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
    pipeline.refresh_known(cfg, cands)
    pipeline.save_candidates(cands, run)
    export.write_csv(cands, run / "candidates.csv")
    short = export.shortlist(cands, args.top, args.include_known)
    if not args.no_fetch:
        _fetch_missing_chips(cfg, run, short, Path(args.cache))
        # The fetched Sentinel-2 contrast feeds the score, so rank again.
        scoring.score_all(cands, cfg["scoring"]["weights"])
        pipeline.save_candidates(cands, run)
        short = export.shortlist(cands, args.top, args.include_known)
    export.write_kml(short, run / "shortlist.kml")
    export.write_gpx(short, run / "shortlist.gpx")
    export.write_review_html(run, short, run / "review.html")
    print(f"wrote candidates.csv, shortlist.kml, shortlist.gpx, review.html ({len(short)} candidates) in {run}")


def _fetch_missing_chips(cfg, run: Path, short: list[dict], cache: Path) -> None:
    """Sentinel-2 contrast and a chip for shortlisted candidates the scan didn't enrich
    (e.g. ones added by the pixel classifier)."""
    from concurrent.futures import ThreadPoolExecutor

    from .sentinel2 import SceneIndex, candidate_features

    todo = [c for c in short if not (run / "chips" / f"{c['id']}_s2.png").exists()]
    if not todo:
        return
    index = SceneIndex(cache)

    def go(c):
        try:
            c.update(candidate_features(index, c, cfg["sentinel2"], run / "chips" / f"{c['id']}_s2.png"))
        except Exception as e:
            logging.getLogger("moundfinder").warning("%s: Sentinel-2 failed: %s", c["id"], e)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(go, todo))


def cmd_calibrate(args, cfg):
    rows = pipeline.calibration_report(cfg, pipeline.load_candidates(Path(args.run)), args.aoi, Path(args.run))
    if not rows:
        print("no recorded sites fall inside the scanned area; add some to data/known_sites/")
        return
    print(f"{'site':28} {'found':>5} {'rank':>6} {'pct':>6} {'unpen.':>6} {'height':>6} {'relief':>6}  flags")
    for r in rows:
        print(f"{r['site'][:28]:28} {'yes' if r['found'] else 'no':>5} {r['rank'] or '-':>6} "
              f"{r['percentile'] if r['percentile'] is not None else '-':>6} {r['rank_unpenalised'] or '-':>6} "
              f"{r['peak_relief_m'] or '-':>6} {r['max_relief_m'] if r['max_relief_m'] is not None else '-':>6}  {r['flags']}")
    print("rank = final score rank; unpen. = rank ignoring village/tree/water penalties; "
          "height = matched blob; relief = max local relief within the site's uncertainty radius")
    found = sum(r["found"] for r in rows)
    print(f"recall: {found}/{len(rows)} recorded sites detected (of {rows[0]['of']} candidates)")


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


def cmd_spectral_train(args, cfg):
    stats = pipeline.spectral_train(cfg, args.tiles, Path(args.model), Path(args.cache))
    print(f"{stats['sites']} recorded sites, {stats['positives']} positive / {stats['negatives']} background pixels")
    print("held-out sites (model trained without the site and without nearby background):")
    for r in stats["held_out"]:
        print(f"  {r['site'][:30]:30} median p={r['median_prob']:.2f}  beats {r['percentile_vs_background']:5.1f}% of background")
    print("top features:", ", ".join(f"{n} {v}" for n, v in stats["top_features"]))
    print(f"model -> {args.model}")


def cmd_spectral_predict(args, cfg):
    cands = pipeline.spectral_predict(cfg, Path(args.run), Path(args.model), args.aoi, Path(args.cache), args.tiles)
    by = {}
    for c in cands:
        by[c.get("source", "dem")] = by.get(c.get("source", "dem"), 0) + 1
    print(f"{len(cands)} candidates by source: {by}; run `export` for a new shortlist")


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
    e.add_argument("--no-fetch", action="store_true", help="don't download chips for shortlisted candidates")
    e.add_argument("--cache", default="cache")
    e.set_defaults(func=cmd_export)

    c = sub.add_parser("calibrate", help="how well did the scan find recorded sites?")
    c.add_argument("run")
    c.add_argument("--aoi", default="thar_ghaggar_margin")
    c.set_defaults(func=cmd_calibrate)

    t = sub.add_parser("train", help="fit a classifier on labelled candidates and re-score")
    t.add_argument("run")
    t.add_argument("--labels", required=True, help="CSV with columns id,label (1 site, 0 not)")
    t.set_defaults(func=cmd_train)

    st = sub.add_parser("spectral-train", help="train the Sentinel-2 pixel classifier on recorded sites")
    st.add_argument("--tiles", nargs="+", required=True)
    st.add_argument("--model", default="models/spectral.pkl")
    st.add_argument("--cache", default="cache")
    st.set_defaults(func=cmd_spectral_train)

    sp = sub.add_parser("spectral-predict", help="map mound probability over a scanned run and add its candidates")
    sp.add_argument("run")
    sp.add_argument("--model", default="models/spectral.pkl")
    sp.add_argument("--aoi", default="thar_ghaggar_margin")
    sp.add_argument("--tiles", nargs="*")
    sp.add_argument("--cache", default="cache")
    sp.set_defaults(func=cmd_spectral_predict)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(asctime)s %(message)s")
    args.func(args, load_config(args.config))


if __name__ == "__main__":
    main()
