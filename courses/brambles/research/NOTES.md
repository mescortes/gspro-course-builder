# Brambles: research notes

Phase 0 research of 2026-10-14: eight researchers, then eight independent verifiers re-checked every claim from primary
sources (data services, file headers, club pages). Summary in the Phase 0 report
(https://claude.ai/artifact/XvUZHjumkRcWB3SmqH5anE).

## The course

* 18900 Grange Road, Middletown, Lake County, California (CEQA SCH 2019119002 gives 19970 S. Highway 29). Coore &
  Crenshaw with James Duncan, on the old Crazy Creek gliderport.
* Timeline: land bought 2017; CEQA mitigated negative declaration filed 2019-11-01; work began 2020; shaped, and a couple
  of holes planted, by the end of 2021; most of the course planted in summer 2022; official opening April 2024
  (GCM Online, Feb 2025; Golf Course Architecture, 2020-07-15).
* Zoysia tee to green; native meadow rough, grazed by sheep; barrancas (drainage channels); one valley oak in play.

## Scorecard

* The club publishes no par and, by several accounts (Golf Club Atlas, Golfadelphia, Global Golf Post), no rating.
* The only hole-by-hole card is the GolfPass / 18Birdies / OpenGolfAPI feed (GolfNow data, in place by 2026-05-13):
  Back 7190, Middle 6579, Front 5318 yards; par 72 (par 5s on 1, 7, 13, 17; par 3s on 3, 8, 12, 16); one stroke-index
  row for men and women. All 18 Back yardages match Golfadelphia's playing report of 2026-08-20; 8 match the Golf Club
  Atlas profile (2025-03-10).
* Ratings in the feed (73.1/141 Back men, 71.7/132 Middle men, 71.5/127 Front women) are unofficial: the USGA NCRDB
  returned 403 and GHIN needs a login. Hidden Valley Lake GC next door is listed at 73.1/142.
* The club uses no tee markers; tee names Back / Middle / Front.

## Data

* LiDAR: USGS 3DEP `CA_NorthCoastRanges_2_B23` (QL1, NV5, Riegl VQ-1560 II-S). Over the course the points' GPS times
  are 2023-09-23 (20:40-21:36 UTC) and 2023-09-27 (15:14-15:56 UTC): after the shaping and planting, seven months
  before the opening. LAS 1.4 point format 6, 16.5-17.9 pts/m2 per tile header, 11-15 ground pts/m2 on turf, NVA RMSE
  3.67 cm, EPSG:6339 + NAVD88 (GEOID18), classes 1 / 2 / 7 / 18 (vegetation unclassified). Ground is classified from
  one swath per flight. Tile names start 500 m west of the tile's real easting range. Nothing newer exists or is
  planned (3DEP index, WESM, OpenTopography, NOAA US Interagency Elevation Inventory). The older CA_LakeCounty_2015
  survey (Feb 2016) shows the pre-course pasture.
* The irrigation pond (about 0.8 ha, near E 536640, N 4291310) is not hydro-flattened: the DEM has a sloping bed 2-4 m
  below the old pasture. Its water level has to be set by hand.
* Photo: USDA NAIP 2024 (2024-05-22, 0.6 m, R G B NIR, public domain) from the USDA FPAC ImageServer, the only open
  image of the finished course. The service keeps only the latest year per state; NAIP 2026 (30 cm, 4 bands) was
  flown over the course on 2026-06-01 and should be published around early 2027.
* NDVI does not separate the turf from the rough: zoysia fairways ~0.09 sit between dry tan rough (~0.04) and green
  swale meadow (~0.33). Colour and brightness (zoysia: R ~ G, bright, NIR high) or hand-drawn polygons do.
* Backdrop: 3DEP 1 m DEM tiles x53y429 and x53y430 of the same project cover the 5 km square. No public DSM.

## OSM

OSM has no golf features here. It has the gliderport runways, a "Glider Port" track and old ranch tracks, and landuse
polygons (farmland, farmyard, industrial, meadow) across the playing area: course.toml [osm] exclude drops them. Hole
numbering and the lines of play follow the GolfNow GPS layout (tee and green-centre points), checked against NAIP;
all features are drawn in features/golf.geojson. Holes 1, 4, 6 and 7 are doglegs: the straight tee-to-green line is
well short of the card (hole 7: 556 vs 611 yd), so their lines follow the fairway.

## Card against the ground (QA round 1)

From the built tee decks, holes 1, 7 and 18 measure short of the feed's card (yards, measured / card): hole 1 Back
524 / 531 and Middle 485 / 496; hole 7 Back 572 / 611 and Middle 516 / 572; hole 18 Middle 458 / 467. The GPS tee and
green points of the same feed give the same shortfall along the line of play (hole 7: 557 / 518 / 389 against 611 /
572 / 449), and no source explains it: no deck, aim point or routing reaches the card. The model keeps the markers on
the real decks; course.toml [tests] known_tee_gaps documents the gaps.

