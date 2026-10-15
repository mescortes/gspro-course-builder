# Deer Ridge: research notes

Phase 0 research of 2026-10-14: researchers, then independent verifiers re-checked every claim from primary sources
(data services, file headers, club pages). Summary in the Phase 0 report
(https://claude.ai/artifact/XvUZHjumkRcWB3SmqH5anE).

## The course

* 200 Deer Ridge Drive, Kitchener, Ontario; private. Thomas McBroom ("Thomas McBroom Architect" on the card); the club
  dates itself to 1991. All greens complexes were stripped, rebuilt and sodded from 2010-08-23 to 2010-11-01, with
  greenside bunkers redone, collection areas on 4, 6, 11 and 13, and new back tees on 4, 8, 11, 13, 15 and 18 (McBroom,
  2013); reopened June 2011. Forward decks were enlarged or built after the LiDAR: 2020 (forward tees on 1, 6, 7, 9)
  and the 2021 capital budget ("forward tee construction (1, 5, 12)").
* The June 2017 Grand River flood (2017-06-24) put 13 of 21 greens and 11 fairways under water and washed out about
  600 t of bunker sand; repairs were by cultural practices, done well before the LiDAR flight (2017-11-21).

## Scorecard

* The club's 2026 card (scorecard2026.jpg, the "VIEW SCORECARD" link on deerridgegolfclub.com/golf, page 1 of the
  March 2026 PDF): par 72, six sets Black 7215, Gold 6715, Silver 6338, Bronze 6012, White 5263, Copper 4131. Copper is
  new in 2025 and probably markers on existing ground (no new pad between the 2020 and 2025 photos at the estimated
  spots on 1, 5, 12, 14, 18; on 4 and 13 Copper uses the White yardage).
* Stroke index: the 2026 card (men odd on the front, women even). It changed on the 2024, 2025 and 2026 cards; OSM's
  handicap tags match none of them.
* Ratings (GAO - RCGA, page 2 of the 2026 PDF, same as the 2025 ratings card): Black 75.3/133, Gold 72.7/131,
  Silver 70.9/128 (W 77.4/139), Bronze 69.0/126 (W 75.4/136), White 65.4/114 (W 70.9/123), Copper 60.7/105
  (W 64.7/108); women not rated on Black and Gold. Combination sets reuse the boxes; the 2026 card's back-nine combo
  arrows for Gold/Silver and Bronze/White look misplaced (the 2025 layout matches the rated totals).

## Data

* LiDAR: OMAFRA Lidar 2016-18, Lake Erie package, in two NRCan folders: Lake_Erie_Fall_2017 (N 4805 tiles and
  E 548 / N 4806) and Lake_Erie_2018 (the rest of N 4806). Inside the course outline every point was flown 2017-11-21
  (leaf-off); later strips (2017-12-06, 2018-03-20) only touch the north edge of the buffer.
* Photo: Ontario SWOOP 2025, 0.16 m, R G B NIR, flown 2025-04-07, three days after a Grand River flood peak (588 m3/s at
  Doon on 2025-04-04; about 3x baseline flow on photo day). A wet corridor (about E 546175-546365, N 4805690-4805815,
  extending NW as a diagonal channel to about E 546070-546250, N 4805770-4805900) and a flooded backwater along the
  south bank (about E 546230-546310, N 4805600-4805640) are dark brown or open water on the photo: they are turf or
  rough on the ground. A pond at about E 547136-547260, N 4806309-4806428 (6700 m2) is brown (turbid) on the photo.
* Backdrop: HRDEM 1 m DTM and DSM; the 5 km square is half Lake_Erie_2018 and half Lake_Erie_Fall_2017.

## OSM

* Outline way 140907484 (86.2 ha), 18 golf=hole lines (refs 1-18, par 72, each starting on a tee and ending on a
  green); 21 greens, 74 tees, 78 bunkers, 25 fairways, 4 water hazards, a lateral water hazard (a natural=wetland
  relation), a driving range and a natural=wood out_of_bounds.
* Paths: 39 ways tagged golf=path + highway=path + foot=designated (read as cart paths by the highway=path rule).
* The outline's east end (E 547705-547872) is a residential subdivision, a wetland and a parking lot, outside the
  build area (course.toml [frame]).
* RiverEdge (895 m ESE) and Doon Valley (1285 m SSE) have no hole lines near Deer Ridge; Doon Valley's odd tee and
  fairway tags are its own.
