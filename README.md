# archaelogical-discoveries

This project looks for **unrecorded ancient settlement mounds** in free satellite and elevation data. It shortlists them for a field visit and gets the real ones formally recorded.

**Search area:** the Thar desert margin of the Ghaggar–Hakra / Chautang system in northwest India (southern Sri Ganganagar and Hanumangarh, northern Bikaner, northern Churu). Across the border, machine-learning survey of the same landscape in Cholistan turned up hundreds of unrecorded Indus-period mounds. On the Indian side this is the least systematically surveyed part of the river system, and it's a day's drive from Haryana for checking on the ground.

- [docs/AREA_SELECTION.md](docs/AREA_SELECTION.md): why this area, with sources, and whether locals already know the mounds
- [docs/PLAN.md](docs/PLAN.md): the phased plan and the pilot result
- [docs/FIELD_PROTOCOL.md](docs/FIELD_PROTOCOL.md): what to do (and not do) at a candidate

## How it works

1. **Relief:** Copernicus GLO-30 elevation, white top-hat local relief model. Each bump 1.5 m+ tall and 0.5–80 ha in area becomes a candidate, with its height, area, elongation, solidity and the amount of relief around it (to catch dune fields).
2. **Filters:** keep candidates inside the AOI and more than 25 km from the international border. Match them against `data/known_sites/` (rediscoveries are kept for calibration).
3. **Land cover:** ESA WorldCover over each candidate's footprint, to flag villages and tree groves (both raise a surface model).
4. **Sentinel-2:** two seasonal composites per top candidate. Crop-season NDVI deficit shows a mound as a hole in green fields; dry-season brightness and bare-soil contrast pick up mound soils. A true-colour chip is saved for review.
5. **Pixel classifier** (`spectral-train` / `spectral-predict`): a random forest on two-season, whole-tile Sentinel-2 composites, local colour contrast and relief, trained on the recorded sites (the Orengo et al. 2020 approach). It finds mound surfaces where elevation can't, such as among dunes, and adds its own candidates.
6. **Scoring:** a transparent heuristic that combines shape, relief, isolation, spectral contrast and the classifier's probability. Once you have labels, a random forest trained on them replaces it.
7. **Export:** CSV, KML/GPX for your phone, and an HTML review page with image chips.

Everything reads straight from public cloud buckets. You don't need any accounts or API keys.

## Quick start

```bash
pip install -e '.[dev]'
pytest

# One 1-degree tile (about 2 minutes)
moundfinder -v scan --aoi thar_ghaggar_margin --tiles N29E074 --out runs/pilot --s2-top 60
moundfinder calibrate runs/pilot --aoi thar_ghaggar_margin   # did it find the recorded sites?
moundfinder export runs/pilot --top 50                        # review.html, shortlist.kml/.gpx, candidates.csv

# Whole primary area
moundfinder -v scan --aoi thar_ghaggar_margin --out runs/thar --s2-top 300

# Pixel classifier: train on tiles with recorded sites, then map a run
moundfinder -v spectral-train --tiles N29E074 N29E073 N29E075 N28E074
moundfinder -v spectral-predict runs/thar
moundfinder export runs/thar --top 100

# After labelling candidates (labels.csv: id,label with 1 = site, 0 = not)
moundfinder train runs/pilot --labels labels.csv
moundfinder export runs/pilot --top 50
```

The AOIs are in `config/aois.geojson` (`thar_ghaggar_margin`, `bikaner_churu_gap`, `haryana_calibration`), and the tuning parameters are in `config/settings.yaml`. Downloads are cached in `cache/` and outputs go to `runs/`. Both folders are git-ignored, so coordinates of possible sites never land in the repo by accident.

## Layout

```
config/            AOIs, border line, settings
data/known_sites/  recorded sites (seed list; extend it, see PLAN Phase 1)
src/moundfinder/   dem, relief, landcover, sentinel2, spectral, knownsites, scoring, export, pipeline, cli
tests/             synthetic-terrain and unit tests
docs/              area choice, plan, field protocol
```
