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
        # The fetched Sentinel-2 contrast feeds the score, so rank again; re-ranking can
        # pull in candidates that still lack chips, so repeat until the list is stable.
        for _ in range(3):
            _fetch_missing_chips(cfg, run, short, Path(args.cache))
            scoring.score_all(cands, cfg["scoring"]["weights"])
            new_short = export.shortlist(cands, args.top, args.include_known)
            stable = [c["id"] for c in new_short] == [c["id"] for c in short]
            short = new_short
            if stable:
                break
        _fetch_missing_chips(cfg, run, short, Path(args.cache))
        pipeline.save_candidates(cands, run)
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


def cmd_soi_index(args, cfg):
    """Georeference every downloaded one-inch sheet and OCR it for mound terms."""
    import json as _json
    from concurrent.futures import ProcessPoolExecutor

    from . import soi

    raw = Path(args.maps)
    files = sorted(p for p in raw.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".tif", ".png"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = []
        fast = [args.fast] * len(files)
        for r in pool.map(_index_one, files, [args.no_ocr] * len(files), [out / "sheets"] * len(files), fast):
            print(f"{r[0]}: {'skipped' if r[3] else f'{len(r[2])} words'}", flush=True)
            results.append(r)
    sheets, words = [], []
    for name, sheet, ws, err in results:
        if err:
            print(f"skip {name}: {err}")
            continue
        sheets.append(sheet)
        words += ws
    soi.save_index(sheets, out / "sheets.json")
    (out / "words.json").write_text(_json.dumps(words))
    terms = [w for w in words if soi.MOUND_TERMS.search(w["text"])]
    with open(out / "mound_terms.csv", "w", newline="") as f:
        wtr = csv.DictWriter(f, fieldnames=["text", "lat", "lon", "conf", "sheet", "year"], extrasaction="ignore")
        wtr.writeheader()
        wtr.writerows(terms)
    print(f"{len(sheets)} sheets georeferenced, {len(words)} words read, {len(terms)} mound terms -> {out}")


def _index_one(path: Path, no_ocr: bool, cache: Path, fast: bool = False):
    import json as _json

    from . import soi

    name = path.name.replace("_", " ")  # saved as 44_K_13_Hissar_District_(1914).jpg
    done = cache / f"{path.stem}.json"  # per-sheet result, so a rerun resumes where it stopped
    try:
        sheet, rgb, _ = soi.open_sheet(path, name)
        if no_ocr:
            return name, sheet, [], None
        if done.exists():
            return name, sheet, _json.loads(done.read_text()), None
        # fast: about 4x quicker; one tile grid with a wider overlap, less upscaling
        words = soi.ocr_words(sheet, rgb, scale=2.5, overlap=300, two_grids=False) if fast else soi.ocr_words(sheet, rgb)
        cache.mkdir(parents=True, exist_ok=True)
        tmp = done.with_suffix(".tmp")
        tmp.write_text(_json.dumps(words))
        tmp.replace(done)
        return name, sheet, words, None
    except Exception as e:  # one bad scan should not stop the rest
        return name, None, [], str(e)


def cmd_soi_leads(args, cfg):
    """List old-map mound labels, marking those with no recorded site nearby."""
    from . import soi
    from .knownsites import load_known_sites

    index = Path(args.index)
    if (index / "words.json").exists():
        words = json.loads((index / "words.json").read_text())
    else:  # an unfinished index: use the sheets read so far
        words = [w for f in sorted((index / "sheets").glob("*.json")) for w in json.loads(f.read_text())]
    phrases = soi.label_phrases(words)
    cands = sorted(pipeline.load_candidates(Path(args.run)), key=lambda c: -c["score"]) if args.run else []
    known = load_known_sites(cfg["known_sites"])
    leads = soi.historical_leads(phrases, known, cands, cfg["known_site_margin_m"], args.candidate_radius_m)
    order = {"mound": 0, "ruins": 1, "name": 2}
    leads.sort(key=lambda r: (bool(r["known_site"]), order[r["kind"]], r["candidate_rank"] or 10**9))
    fields = ["label", "kind", "lat", "lon", "sheet", "year", "conf", "known_site", "known_site_dist_m",
              "candidate", "candidate_rank", "candidate_dist_m"]
    with open(index / "leads.csv", "w", newline="") as f:
        wtr = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        wtr.writeheader()
        wtr.writerows(leads)
    new = [r for r in leads if not r["known_site"]]
    print(f"{len(words)} words, {len(leads)} mound labels, {len(new)} with no recorded site nearby "
          f"({sum(r['kind'] == 'mound' for r in new)} mound terms, {sum(r['kind'] == 'ruins' for r in new)} "
          f"deserted settlements, {sum(r['kind'] == 'name' for r in new)} place names; "
          f"{sum(1 for r in new if r['candidate'])} have a scan candidate within {args.candidate_radius_m:.0f} m) "
          f"-> {index / 'leads.csv'}")


def _edge_m(sheet, c) -> float:
    """Distance in metres from a candidate to the nearest edge of a sheet's frame."""
    from .geo import metres_per_degree

    w, s, e, n = sheet.bounds
    m_lon, m_lat = metres_per_degree(c["lat"])
    return min((c["lon"] - w) * m_lon, (e - c["lon"]) * m_lon, (c["lat"] - s) * m_lat, (n - c["lat"]) * m_lat)


def cmd_soi_chips(args, cfg):
    """Crop the old maps around shortlisted candidates and note nearby historical mound labels."""
    import math as _math

    from . import soi
    from .geo import haversine_m

    run = Path(args.run)
    sheets = soi.load_index(Path(args.index) / "sheets.json")
    terms = []
    terms_path = Path(args.index) / "mound_terms.csv"
    if terms_path.exists():
        with open(terms_path, newline="") as f:
            terms = [dict(r, lat=float(r["lat"]), lon=float(r["lon"])) for r in csv.DictReader(f)]
    cands = pipeline.load_candidates(run)
    short = export.shortlist(cands, args.top, args.include_known)
    by_sheet = {}
    for c in short:
        # Earliest sheet with the candidate well inside its frame, so the crop isn't mostly margin.
        cover = sorted((s for s in sheets if s.contains(c["lon"], c["lat"])),
                       key=lambda s: (_edge_m(s, c) < args.half_m, s.year or 9999))
        c["soi_sheet"] = cover[0].name if cover else None
        c["soi_year"] = cover[0].year if cover else None
        if cover:
            by_sheet.setdefault(cover[0].name, []).append(c)
        near = [(haversine_m(c["lat"], c["lon"], t["lat"], t["lon"]), t) for t in terms]
        near = [x for x in near if x[0] <= args.label_radius_m]
        c["soi_label"] = min(near, key=lambda x: x[0])[1]["text"] if near else ""
        c["soi_label_dist_m"] = round(min(near, key=lambda x: x[0])[0]) if near else None
    for name, group in by_sheet.items():
        sheet = next(s for s in sheets if s.name == name)
        rgb, _ = soi._load_gray(sheet.path)
        for c in group:
            img = soi.crop(sheet, rgb, c["summit_lon"], c["summit_lat"], half_m=args.half_m)
            (run / "chips").mkdir(exist_ok=True)
            img.save(run / "chips" / f"{c['id']}_soi.png")
        del rgb
    pipeline.save_candidates(cands, run)
    covered = sum(1 for c in short if c.get("soi_sheet"))
    labelled = sum(1 for c in short if c.get("soi_label"))
    print(f"{covered}/{len(short)} shortlisted candidates on an old sheet; {labelled} within "
          f"{args.label_radius_m} m of a historical mound label")


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

    si = sub.add_parser("soi-index", help="georeference and OCR the old Survey of India one-inch sheets")
    si.add_argument("--maps", default="data/raw/soi")
    si.add_argument("--out", default="runs/soi")
    si.add_argument("--workers", type=int, default=3)
    si.add_argument("--no-ocr", action="store_true")
    si.add_argument("--fast", action="store_true", help="quicker, slightly less thorough OCR")
    si.set_defaults(func=cmd_soi_index)

    sc = sub.add_parser("soi-chips", help="old-map crops and historical mound labels for a run's shortlist")
    sc.add_argument("run")
    sc.add_argument("--index", default="runs/soi")
    sc.add_argument("--top", type=int, default=100)
    sc.add_argument("--include-known", action="store_true")
    sc.add_argument("--half-m", type=float, default=1000)
    sc.add_argument("--label-radius-m", type=float, default=500)
    sc.set_defaults(func=cmd_soi_chips)

    sl = sub.add_parser("soi-leads", help="old-map mound labels with no recorded site nearby")
    sl.add_argument("--index", default="runs/soi")
    sl.add_argument("--run", help="a scan run, to note the nearest candidate and its rank")
    sl.add_argument("--candidate-radius-m", type=float, default=500)
    sl.set_defaults(func=cmd_soi_leads)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(asctime)s %(message)s")
    args.func(args, load_config(args.config))


if __name__ == "__main__":
    main()
