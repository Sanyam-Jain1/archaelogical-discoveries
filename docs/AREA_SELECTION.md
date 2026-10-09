# Where to look: choosing the search area

**Decision:** search the **Thar desert margin of the Ghaggar–Hakra / Chautang system on the Indian side**: southern Sri Ganganagar and Hanumangarh, northern Bikaner, and northern Churu (roughly 28.2–29.6° N, 73.2–75.4° E, minus a 25 km belt along the border). The highest-priority sub-area is the dune tract between the Ghaggar and the Sothi/Chautang line (Lunkaransar, Sardarshahar, Taranagar).

The Haryana plains (Sirsa, Fatehabad, Hisar, Jind) are the **calibration** area, not the main target.

## What "maximise the chances" actually means

A discovery only counts once someone has stood on the site, seen the evidence, and reported it to people who can record it. So the odds depend on five things, and all five have to be good at the same time:

1. **Density of unrecorded sites.** How many real sites are out there that nobody has written down?
2. **Visibility in free data.** Can a 10–30 m satellite pixel or a 1960s spy photo actually see them?
3. **Survey gap.** Has someone already walked the area village by village?
4. **Ground-truthing.** Can *you* get there, legally and cheaply, more than once?
5. **Urgency.** Will the site still be there in ten years? This doesn't change the odds, but it makes a find worth more.

Most famous remote-sensing finds score well on 1–3 and very badly on 4. Valeriana, the Maya city, came out of a lidar dataset that a forest-carbon project had collected in 2013 ([Inverse](https://www.inverse.com/science/archaeologists-uncovered-ancient-maya-empire-city)). It counts as a find because archaeologists read the data and can take it to the field. A candidate nobody can visit stays a pin on a map.

## Candidates compared

Scores are my judgement from the sources below (5 = best).

| Region | Unrecorded density | Visible in free data | Survey gap | You can ground-truth | Urgency | Verdict |
|---|---|---|---|---|---|---|
| **Thar margin of the Ghaggar–Chautang (Bikaner, Churu, S Sri Ganganagar/Hanumangarh)** | 4 | 4 | 4 | 4 | 4 | **Primary** |
| Haryana Ghaggar–Chautang plains (Sirsa, Fatehabad, Hisar, Jind) | 3 | 3 | 2 | 5 | 5 | Calibration |
| Cholistan, Pakistan | 5 | 5 | 3 | 0 | 3 | Not reachable |
| Kachchh / North Gujarat | 3 | 4 | 3 | 2 | 3 | Backup |
| Jammu alluvial plains | 3 | 3 | 3 | 2 | 4 | Backup |
| Amazon / Maya lowlands (lidar) | 5 | 4 (where lidar exists) | 3 (crowded since 2025) | 0 | 3 | No |
| Arabian deserts (kites, mustatils) | 3 | 5 | 2 | 0 | 2 | No |

## Why the Thar margin

**The same landscape across the border turned out to be full of unrecorded mounds.** Orengo, Petrie and colleagues trained a random forest on known mounds in Cholistan, using Sentinel-1 radar and Sentinel-2 imagery. The resulting probability map covered about 36,000 km² and showed "many more archaeological mounds than previously recorded, extending south and east into the desert" ([PNAS 2020](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7414161/)). Petrie described it as "hundreds of new sites, much deeper in the desert than previously suspected, including several unexpected large-sized urban centres" ([Cambridge](https://www.arch.cam.ac.uk/news/cloud-computing-and-machine-learning-are-identifying-archaeological-sites-space)). Cholistan is the western end of the Thar. The palaeochannels and the settlement pattern run straight on into Sri Ganganagar and Bikaner, and the border is not an archaeological boundary. Their code is public ([CORA, doi 10.34810/data184](https://doi.org/10.34810/data184)).

**It is the least walked part of the Ghaggar system in India.** Haryana has had village-to-village surveys: the Cambridge–BHU *Land, Water and Settlement* project and then *TwoRains*, which covered about 3,400 km² of Sirsa, Fatehabad and Hisar in 2018 alone ([TwoRains 2018](https://www.arch.cam.ac.uk/node/1611)). Kurukshetra University and the state department have surveyed there too. Hanumangarh got a full village-by-village survey from 2008 to 2012, which visited 574 sites and still turned up new ones ([Pawar et al.](https://www.heritageuniversityofkerala.com/JournalPDF/Volume1/475-485.pdf)). For Bikaner, the same paper cites K.F. Dalal's 1980 work as the *only* notable methodical survey with surface collection. The Bikaner–Churu dune country is the gap.

**Arid ground makes sites visible.** With little vegetation, mound soils full of ash, pottery and salts stand out spectrally, which is why the Cholistan classifier worked. Dunes are the main confuser here, and the detector has specific checks for them (shape, orientation, and how much relief surrounds a bump).

**The 1960s spy photos matter most here.** The Indira Gandhi Canal has been turning this desert into irrigated farmland since the 1960s, and levelling for irrigation destroys mounds. CORONA frames from 1960–72 show the land before most of that happened, and the Survey of India 1-inch maps from the 1910s–40s go back further. Both are free: the maps are on [Zenodo](https://zenodo.org/communities/old-survey-of-india-maps/about) and at the [National Library of Scotland](https://maps.nls.uk/india/survey-of-india), and CORONA is on USGS EarthExplorer.

**You can actually get there.** It is a 2–4 hour drive from Hisar to Nohar, Sardarshahar or Lunkaransar. You can make repeat trips in the cool season (November–February).

## Your question: don't local people already know these mounds?

Often, yes, and that's fine. Villagers usually know the big mounds: the *theh* or *kheda* where old bricks and potsherds turn up. Many villages are named after them. But "known to the village" is not the same as "in the archaeological record." A site is only recorded once it is in a state or ASI listing or a published survey, with coordinates, size and a period from its surface pottery.

The evidence says the gap between the two is large:

- Green, Petrie and colleagues field-checked mound symbols from the old Survey of India maps across northwest India. They concluded that "there remain many unreported cultural heritage sites on the plains of northwest India" ([Remote Sensing 2019](https://www.mdpi.com/2072-4292/11/18/2089)).
- The Land, Water and Settlement survey literally went village to village *asking people*. That is how it found sites, which tells you the knowledge sat with villagers and not with archaeologists.
- A 2023 deep-learning pass over the historical maps flagged nearly 6,000 mound features across the Indus basin ([Berganzo-Besga et al., Sci. Rep. 2023](https://doi.org/10.1038/s41598-023-38190-x)). Most of them have never been checked on the ground.

What this means for you:

- **In Haryana,** the big mounds are mostly recorded already. What's left are small, low mounds and sites that are already levelled (visible only in CORONA or the old maps). That's still valuable, but the payoff per candidate is lower.
- **In the Thar margin,** the population is sparser, dunes hide and expose sites, and fewer surveyors have passed through. Local knowledge is thinner and the archaeological record is thinner still.
- **Either way, ask locals.** "Is there an old theh near here where people find pottery?" is the single best field technique. It's how professional surveys work too.

## Why not the others

- **Cholistan:** it has the best density, but it's in Pakistan, so you can't ground-truth it.
- **Amazon and Maya lowlands:** the lidar is excellent, but you can't do follow-up fieldwork there. The 2025 "OpenAI to Z" Kaggle challenge also put a crowd of people on the same Amazon data.
- **Arabian deserts:** the AAKSAU and other teams have systematically mapped the kites and mustatils from imagery, and access is hard.
- **Kachchh / North Gujarat:** this is a strong backup. It's arid, sites are well preserved, and there's an open field-verified dataset for eastern Kachchh ([Zenodo](https://zenodo.org/records/18796737)). But it's about 1,000 km from Haryana. Switch here if the Thar margin turns out to be mostly recorded.
- **Jammu plains:** a CORONA + HEXAGON + old-maps project found "more than a dozen previously unknown sites" ([ICAC](https://giap.icac.cat/2023/06/06/navjot-jammu-fieldwork/)). It's a good method precedent, but there's already an active team there.

## Risks in this choice

- **The border belt.** Under India's drone rules, the 25 km belt along the international border is a red zone. Border districts have also had temporary movement and drone bans ([Deccan Herald, 2025](https://www.deccanherald.com/india/rajasthan/rajasthan-border-districts-on-high-alert-amid-threats-of-pak-strikes-3534265)). The pipeline drops everything within 25 km of the border, which costs the Anupgarh–Khajuwala strip, including the area around Binjor.
- **Dunes bury sites.** Some real sites will be invisible under sand. Others will be exposed between dunes and look like dunes. Expect a lower hit rate per candidate than in farmland, and make up for it by covering more area.
- **"Recorded" is hard to check.** There is no open, complete gazetteer of Indian sites. Building the known-sites list (Phase 1 of the [plan](PLAN.md)) is the step that turns "a mound" into "an unrecorded mound." It is also the best reason to bring in an archaeologist early.
