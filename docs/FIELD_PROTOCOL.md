# Field protocol

The aim of a field visit is to **record**, not to collect. A good record lets an archaeologist decide, without going there, whether a site is worth their time.

## Legal and ethical rules

- **Never dig, probe or collect.** That includes sherds lying loose on the surface. Under India's Antiquities and Art Treasures Act 1972 and the Ancient Monuments and Archaeological Sites and Remains (AMASR) Act 1958, excavation needs a licence, and antiquities are regulated. Taking a single sherd removes the evidence you're trying to report. Photograph it where it lies.
- **Protected monuments** (ASI or state) have prohibited and regulated zones around them. Don't do anything in those zones beyond looking.
- **Ask permission.** Nearly all mounds are on private farmland, village common land or graveyards. Ask the farmer or the sarpanch first, explain what you're doing, and leave if they say no.
- **Stay out of the border belt.** The pipeline already drops candidates within 25 km of the international border. Don't fly drones in border districts, and check the district's current orders before you travel.
- **Don't publish exact coordinates** of unrecorded sites in public places (social media, a public repo). Coordinates go to the authorities and your academic partner only. Looters read the internet too.

## Kit

- A phone with `shortlist.kml` or `shortlist.gpx` loaded (Organic Maps, OsmAnd and Google Earth all read them), plus an offline map of the district.
- A camera or phone. A scale card or coin, and a north arrow (or note the compass bearing of each photo).
- A notebook or a form app (KoboToolbox or ODK work offline). The fields to record are below.
- Water, a hat, and a printed one-paragraph letter explaining the project. A letter from your partner institution helps a lot.

## At each candidate

1. **Before you walk on:** take one photo of the whole mound from the access road, and note its shape and how high it rises above the fields.
2. **Walk a loop over the top and the slopes, slowly.** Look for:
   - pottery sherds, especially red ware with black painted bands (Harappan), or thick coarse ware;
   - brick fragments, including baked brick and mud-brick lines in section faces;
   - ash, charcoal and burnt soil (grey patches);
   - slag or vitrified lumps (signs of craft activity);
   - bangle pieces, terracotta cakes, beads (photograph them, leave them);
   - **section faces:** fresh cuts made by tractors, soil diggers or canals expose layers. These are the most informative thing you'll see.
3. **Photograph** each type of material where it lies, next to the scale. Take the GPS point of the summit and of each corner of the scatter.
4. **Record the threats:** ploughing, levelling, soil quarrying, graves, brick kilns, construction.
5. **Ask locals:** the local name of the mound (*theh*, *kheda*, *dhora*), what gets found there, and whether there are other old mounds nearby. Write down who told you what.

## Record sheet

| Field | Example |
|---|---|
| candidate id | `N29E074-03718` |
| date, recorder | 2026-12-14, your name |
| summit GPS (lat, lon, accuracy) | 29.xxxxx, 74.xxxxx, ±4 m |
| village / tehsil / district | |
| local name | |
| land use and owner | ploughed field, owned by … |
| dimensions (paced) | 180 × 140 m, ~5 m high |
| surface material | sherds (red ware, some black-painted), baked brick, ash patch on S slope |
| verdict | site / probable site / not a site (dune, kiln, spoil heap, village) |
| threats | levelled on N side; soil digging |
| photos | IMG_0412–0438 |
| informants | sarpanch, farmer (names if they agree) |

Bring the verdicts back into the repo as `labels.csv` (`id,label`) so the model learns from them.

## Reporting

Send confirmed and probable sites, with the record sheet and photos, to your academic partner and to the Rajasthan Department of Archaeology & Museums (or Haryana's, for calibration-area finds). Your partner can date the site from photos of the pottery and get it into a published survey report. That is the step that puts it in the record.
