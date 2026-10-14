# Westmount Golf & Country Club: research notes

Compiled 2026-10-11 by a multi-agent research workflow (`workflows/course_research.js`): seven researchers, each with a
different angle (official scorecard sources, aggregators, front nine, back nine, course facts, LiDAR sources,
DEM/imagery sources), then two adversarial verifiers who re-fetched the sources themselves. Raw results:
`research/research_raw.json`; hole descriptions for the QA prompts: `research/hole_descriptions.json`.

## The course

* Westmount Golf & Country Club, 50 Inverness Drive, Kitchener, Ontario (OSM way 39971102; the property straddles the
  Kitchener / Waterloo boundary). Club formed 1929; Stanley Thompson design, opened 1931 (par 71, 6,440 yd).
* 1958: extra land, par 73. Three new holes were added and the original opening trio became the practice ground (today's
  driving range in the east lobe). Later work: C.E. "Robbie" Robinson (1961), Thomas McBroom (1986, 1997), Doug Carrick
  (adviser since 2003; all bunkers reshaped and greens 11 and 12 rebuilt, completed fall 2013). New back tees on holes 5
  and 11 (in place by about August 2023); hole 8 lengthened in 2025.
* Hosted the 1957 Canadian Open (George Bayer's 64 is still the course record), the 1990 du Maurier Classic and the 2022
  Canadian Women's Amateur. SCOREGolf top 100 Canada (11th in 2024).
* Heavily tree-lined parkland: "almost every fairway framed by towering maples and pines". Bentgrass greens; poa annua
  fairways (aggregator listings). Bunkers are Thompson-style flashed faces with bright white-cream sand (Carrick 2013).
* Water: one pond in play, right of the par-3 3rd (OSM 918946248, about 890 m2, with a fountain). A larger pond in the
  south-west woods (OSM 148323977, about 3,900 m2) is probably the irrigation reservoir, mostly out of play. Maple Hills
  Creek runs just outside the west boundary along University Avenue West. No creek is in play.
* Out of bounds: houses surround the course. The holes nearest the boundary are 12, 1, 8, 10, 11, 7, 6 and 9; holes 3,
  14, 16, 17 and 18 are interior. No public OB-stake map was found, so the OSM property line is the OB line.
* Cart paths: about 2-2.5 m wide, light grey stone-dust / weathered asphalt, uncurbed, mostly beside tees and greens.
  **OSM maps none of them**; `scripts/trace_paths.py` traces them from the NIR band of the photo.
* No existing GSPro / TGC / 2K version of Westmount was found (text search only).

## Scorecard (verified)

Source: Golf Canada Score Centre, course 20954, live data fetched 2026-10-11. It equals the card in Golf Canada since
2025-07 (hole 8 lengthened); ratings were re-issued between 2024-08 and 2024-12 and are unchanged since; the stroke
indexes are the 2026 allocation. The verifier parsed the live JSON and matched every one of the 7 sets x 18 holes, plus
both stroke indexes and all ratings. Each set's holes add up to the published front / back / total.

| Tee | Total yd | Men rating / slope | Women rating / slope |
|---|---|---|---|
| Blue | 7,018 | 73.0 / 132 | – |
| White | 6,550 | 71.1 / 129 | 76.9 / 135 |
| Red | 6,143 | 69.3 / 121 | 75.1 / 130 |
| Gold | 5,432 | 66.3 / 113 | 71.3 / 121 |
| Blue/White (combo) | 6,732 | 71.8 / 130 | – |
| White/Red (combo) | 6,322 | 70.2 / 126 | 76.3 / 132 |
| Red/Gold (combo) | 5,814 | 67.8 / 118 | 73.1 / 125 |

Par 73 (37 out / 36 in) for men and women on every source. Four physical tee boxes (Blue, White, Red, Gold); the combos
reuse them hole by hole. Per-hole yardages and stroke indexes: `scripts/config.py` (`SCORECARD`, `HANDICAP`,
`HANDICAP_WOMEN`).

Sources to avoid, and why:

* Golf Ontario / BlueGolf, Golfify, AllSquare and Hole19 (in metres, labelled as yards) carry the club's **2009** card
  (Blue 6,943), which is about 17 years out of date.
* GolfPass mixes the 2022-24 Golf Canada hole rows (6,925) with a 2009-era header and ratings that appear nowhere else.
* The club's own cards (2023-08 and 2024-04 images, 6,996) predate the 2025 hole 8 change and the late-2024 re-rating.

Caveats:

* Hole 8 (305 / 275 / 260 / 245) is supported only by Golf Canada. The club cards show 283 / 265 / 247 / 240, and the
  2018 LiDAR and the OSM line (~284 yd) predate the change.
* The 2026 stroke indexes rest on one source; earlier allocations differ on every hole.
* Holes 5 and 11 got new tees on every set (about 2023). The 2018 LiDAR cannot show them, so check them against the
  2025 photo.

## Data sources (verified)

| Data | Source | Notes | Licence |
|---|---|---|---|
| Point cloud | OMAFRA Lidar 2016-18, Lake Erie package (NRCan `Lake_Erie_2018`), six 1 km COPC tiles `1km1753{6,7,8}0481{0,1}02018LLAKEERIE` | Leaf-off 2018-03-21 / 25 (+ one 2017-12-06 line), Leica ALS70-HP, 8 pts/m2 nominal, 14-20 measured; classes 1, 2, 6, 7, 17, 18 (no water class); EPSG:2958, heights CGVD2013 (file WKT says "unknown") | OGL-Ontario / OGL-Canada |
| Backdrop DTM | NRCan HRDEM `ON-Lake_Erie_2018-1m-dtm.tif` COG (same 2018 survey) | EPSG:3979 1 m, reprojected to EPSG:2958 2 m on read | OGL-Canada |
| Imagery | SWOOP 2025 (Geospatial Ontario), LIO `GEO_Imagery_Data_Service_2023to2027` ImageServer | 16 cm, R G B NIR, leaf-off March-May 2025, native EPSG:2958 | OGL-Ontario |
| Features | OpenStreetMap (OSM API /map when Overpass is down) | 18 hole lines with refs and pars, 18 greens, 17 fairways, 58 tees, 48 bunkers, 2 water polygons; no cart paths | ODbL |

Not used:

* **Esri World Imagery.** Its z20-21 levels are the Region of Waterloo 2022 aerial and z19 is a 0.5 m 2025 satellite
  image. The Esri licence forbids offline / derived export.
* **Region of Waterloo 2025 / 2026 and City of Waterloo 2022+ imagery.** These are 10 cm (leaf-on summer 2025 and
  leaf-off spring 2026), but © First Base Solutions with no open licence. They are fine for looking, not for shipping.
* **Upper Thames-Grand River 2025 LiDAR.** It leaves a hole over central Kitchener-Waterloo, so it misses the course.
* **City of Kitchener 2019 DTM.** It is clipped at the Kitchener / Waterloo boundary (no data over the north-west half
  of the course) and reads 0.4-0.6 m high (probably CGVD28).
* **City of Waterloo 2014 HRDEM.** It is older and misses the backdrop's south-east corner.
* **City of Waterloo 2021 10 cm MrSID (open).** It is a 3.9 GB download whose licence terms were not confirmed. It is a
  possible second open imagery source.

Attribution for anything shipped: "Contains information licensed under the Open Government Licence – Ontario" and "Open
Government Licence – Canada"; "© OpenStreetMap contributors" (ODbL).

## Imagery observations (SWOOP 2025, spring)

* The photo is leaf-off. Trees are bare: the ground shows through them and their long thin shadows run north-west.
* Greens are pale and straw-coloured (NDVI about 0.09, L* 56), dormant or just uncovered. Fairways are green
  (NDVI about 0.45); tees about 0.32; open rough about 0.30; bunkers about −0.03; roofs about −0.08.
* Several west-side fairways look brown with mowing stripes.
* In NIR, cart paths are crisp dark lines; NDVI hides the tree shadows that dominate the RGB.

## OSM numbering

OSM `golf=hole` refs 1-18 are the course holes in order (`config.course_hole` is the identity). Their par tags
(5,4,3,4,5,3,5,4,4 / 4,5,3,5,4,4,4,3,4) match the card. Clubhouse: OSM way 69020082. Range: the east lobe.
