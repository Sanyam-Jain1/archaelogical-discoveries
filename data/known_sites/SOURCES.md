# Known-sites list: sources and status

The pipeline treats a candidate within `radius_m + precision_m + 300 m` of a recorded site as already recorded, not new. There are **182 sites** in two files:

| File | Source | Sites | Coordinate quality |
|---|---|---|---|
| `heritage_surveys.csv` | Pawar, Parmar & Sharan 2013, *Heritage* 1: 475–485, Table 2: Harappan-related sites from a village-to-village survey of Hanumangarh district, 2008–12 | 74 | Handheld GPS; site size in ha |
| `heritage_surveys.csv` | Samunder & Dangi 2014, *Heritage* 2: 783–801, Table 1: every site explored in Suratgarh tehsil | 79 | Handheld GPS; 74 of them "placed on the archaeological map for the first time" by that survey |
| `seed_sites.csv` | ASI Jodhpur Circle table of centrally protected monuments (JDHRJ043–058) | 12 | ASI decimal degrees |
| `seed_sites.csv` | ASI national list for Haryana (N-HR-22 Banawali, N-HR-27 Agroha) | 2 | Arc-second |
| `seed_sites.csv` | Wikipedia infoboxes and village geocodes (Haryana; Karanpura, Badopal, Sothi) | 15 | Arc-second to village level; see `notes` |

`heritage_surveys.csv` is generated: put the two PDFs in `data/raw/` (git-ignored) and run `python scripts/import_heritage_surveys.py`. The script flags rows that sit far from the other sites of their tehsil. So far that's only Daniasar-II, whose latitude reads 29°57′ but is almost certainly 28°57′; it is kept with a 3 km precision.

Cross-check: the Suratgarh survey's GPS point for Rang Mahal agrees with the ASI table to about 50 m. A Wikipedia mirror's value, 5 km to the north, was wrong.

## How it was gathered

The survey tables come straight from the journal PDFs. The `seed_sites.csv` values were read from web-search results quoting ASI and Wikipedia pages, because this sandbox could not reach those sites. Each row's `source` and `notes` say where it came from.

## Biggest gaps, in order of value

1. **The non-Harappan sites of the Hanumangarh survey.** It visited 574 sites but tabulates only the 74 Harappan-related ones. Early-historic and medieval mounds there are still missing.
2. **The rest of the ASI Jodhpur Circle table:** Bhadrakali, Dhokal (twin mounds "Ekkal-Dhokal") and Tarkhanewala Dera are listed but have no coordinates here yet.
3. **Bikaner and Churu.** No surveyed site list with coordinates turned up for the dune tract. This is the expected gap, and the reason that area is the priority.
4. **Haryana survey gazetteers** (LWS/TwoRains, Kurukshetra University, the state department), for calibration.
5. **Wikidata**: one query would return every archaeological site with coordinates in the region.

To fill items 2 and 5 automatically, allow `asijodhpurcircle.in`, `asijaipurcircle.nic.in` and `query.wikidata.org` in the cloud environment's network settings.
