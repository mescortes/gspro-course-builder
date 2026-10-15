# Whistle Bear: research notes

Phase 0 research of 2026-10-14: researchers, then independent verifiers re-checked every claim from primary sources
(data services, file headers, club pages). Summary in the Phase 0 report
(https://claude.ai/artifact/XvUZHjumkRcWB3SmqH5anE).

## The course

* 1316 Dickie Settlement Road, Cambridge, Ontario. Designed by John Robinson (secondary sources: Golf Course
  Architecture 2013-04-15, Top100golfcourses); the club's archived history has the back nine opening in late summer
  2000 and the front nine in July 2001. Doug Carrick's 2013 master plan left no trace: the routing, ponds and bunker
  clusters are the same in 2008 (Esri Wayback), 2015, 2020 and 2025 photos.
* Practice facility (Golf Academy): lighted driving range, bentgrass tee deck, 40 hitting stations, seven target greens,
  short-game area with chipping and putting greens and bunkers. OSM maps it as a second, unnamed leisure=golf_course
  (way 382278772, 5.7 ha, 89 m north of the course outline way 152133739): 13 greens, 4 tees (one a 3415 m2 deck),
  20 bunkers, no hole lines. golf=driving_range is not tagged.

## Scorecard

* Club card WB-ScoreCard-2021.pdf (linked from whistlebear.ca/golf/course-layout; a 2026-05 re-upload has the same
  text): par 72 (36 / 36), Black 7562, Gold 6966 (the card prints 6936), Blue 6422, White 5831, Red 5111. One par row;
  men's and women's stroke-index rows.
* Ratings: men's from the Golf Ontario certificate effective 2016-08-19 (Black 76.7/137, Gold 73.6/130, Blue 71.1/126,
  White 67.8/121, Red 64.5/107); women's from the club's 2017 card (Blue 77.2/136, White 73.5/127, Red 69.2/118). Gold,
  Blue and White were rated at their pre-2019 par-71 lengths (6936 / 6414 / 5803). Nothing newer is public (Golf Canada
  Score Centre needs a member login).
* Tee slots in GreenKeeper: Black -> Black, Gold -> Yellow, Blue, White, Red.

## Data

* LiDAR: OMAFRA Lidar 2016-18, Lake Erie package, NRCan folder ON/Lake_Erie_Fall_2017 (tile suffix 2017LLAKEERIE), the
  only point cloud over the site. Six 1 km COPC tiles (E 547-549 x N 4801-4802, 887 MB), every point flown 2017-11-21
  (17:09-18:16 UTC): leaf-off. Nothing newer exists or is planned (NRCan index, Geospatial Ontario packages).
* Photo: Ontario SWOOP 2025, 0.16 m, R G B NIR, flown 2025-04-07 (leaf-off spring, no cloud).
* Backdrop: HRDEM ON-Lake_Erie_Fall_2017 1 m DTM and DSM cover the whole 5 km square.

## Changes since the LiDAR

* A planted conifer grove west of the central pond was thinned and a ~70 x 65 m patch stripped to bare soil (about
  E 548510-548580, N 4801646-4801711), between 2022-04-28 and 2025-04-07; the grove south of it (N 4801580-4801645)
  still stands. The 2017 LiDAR still has these trees: they have to be dropped (features/trees_cleared.geojson).
* An area of about 32 x 60 m south of the clubhouse (E 548840-548872, N 4801898-4801958) was being excavated on the
  2025 photo (after April 2022). By 2025-06-02 (Vantor 0.5 m) it was a finished rectangular feature with a long dark
  interior inside a new cart-path loop; its purpose is unknown.

## OSM

* Outline way 152133739 (65.1 ha), 18 golf=hole lines (refs 1-18, par 72), each starting on a tee and ending on a
  green; 117 bunkers, 19 greens, 90 tees, 17 fairways, 7 water features (all also natural=water), 18 pins.
* Cart paths: 22 ways (9.2 km) tagged golf=cartpath + highway=service + service=driveway + golf_cart=designated.
  Another 17 ordinary highway=service ways (driveways, parking aisles, maintenance roads) lie mostly inside the outlines.
* Grand Valley GC, with its own holes 1-18, lies 496 m SSE: [osm] outline keeps its features out.
