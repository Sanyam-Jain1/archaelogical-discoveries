# Known-sites list: sources and status

`seed_sites.csv` holds 41 recorded sites in and around the search areas. The pipeline treats a candidate within `radius_m + precision_m + 300 m` of one of them as already recorded, not new.

| Source | Sites | Coordinate quality |
|---|---|---|
| ASI Jodhpur Circle table of centrally protected monuments (`asijodhpurcircle.in/monuments`, IDs JDHRJ043–058) | 12 mounds in Ganganagar and Hanumangarh | Decimal degrees from ASI; best in the list |
| ASI national list for Haryana (Wikipedia, N-HR-22 Banawali, N-HR-27 Agroha) | 2 | Arc-second |
| Pawar et al. 2013, *Heritage* 1: 475–485: village-to-village survey of Hanumangarh district, 2008–12, handheld GPS | 13 of ~85 Harappan sites | GPS, but rows were pulled from search-engine text extracts and one pair looks garbled (see notes) |
| Samunder & Dangi 2014, *Heritage* 2: 783–801: Suratgarh tehsil survey, handheld GPS | 2 of 79 sites | GPS, same caveat |
| Wikipedia infoboxes | 12 | Arc-second to arc-minute; some may mark the village, not the mound |
| AroundUs listing (Sothi) | 1 | Uncertain; Wikipedia's value contradicts its own text |

## How it was gathered

This sandbox's network blocks Wikipedia, Wikidata, Zenodo, the ASI sites and the journal hosts. All values were read from web-search results that quote those pages. That route is slow (1–3 rows per query) and occasionally garbles tables. Each row's `source` and `notes` say where it came from.

## Biggest gaps, in order of value

1. **The full tables of the two *Heritage* surveys.** That's about 85 Harappan sites (out of 574 visited) in Hanumangarh and 79 sites in Suratgarh tehsil, all GPS-located. They cover the north of the search area. The PDFs are small and free:
   - https://www.heritageuniversityofkerala.com/JournalPDF/Volume1/475-485.pdf
   - https://www.heritageuniversityofkerala.com/JournalPDF/Volume2/783-801.pdf
2. **The rest of the ASI Jodhpur Circle table:** Bhadrakali, Dhokal (twin mounds "Ekkal-Dhokal") and Tarkhanewala Dera are listed but have no coordinates here yet.
3. **Bikaner and Churu.** No surveyed site list with coordinates turned up for the dune tract. This is the expected gap, and the reason that area is the priority.
4. **Haryana survey gazetteers** (LWS/TwoRains, Kurukshetra University, the state department), for calibration.
5. **Wikidata**: one query would return every archaeological site with coordinates in the region.

To fill items 1, 2 and 5 automatically, allow `heritageuniversityofkerala.com`, `asijodhpurcircle.in`, `asijaipurcircle.nic.in` and `query.wikidata.org` in the cloud environment's network settings. Or download the two PDFs yourself and put them in `data/raw/`. That folder is git-ignored, so the journal PDFs are not redistributed.
