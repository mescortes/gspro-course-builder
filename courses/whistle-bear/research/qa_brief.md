# Whistle Bear: QA brief

Read by the QA agents (`workflows/hole_qa.js`) before they inspect a hole.

## The course

Whistle Bear Golf Club, Cambridge, Ontario (John Robinson; opened 2000-01); par 72. Holes 1-18 are the OSM golf=hole
refs. Five tee sets, back to front: Black, Gold, Blue, White, Red (markers labelled Bla, G, Blu, W, R). Coordinates
NAD83(CSRS) / UTM 17N (EPSG:2958), heights CGVD2013. Card: the club's 2021 card (research/NOTES.md). The course went
from par 71 to par 72 around 2019 and Gold, Blue and White were lengthened then: some tees may have been built after
the 2017 LiDAR (they would show in the photo but not as LiDAR decks), and a forward (Red, White) tee can be a marker
on the fairway rather than a pad.

The practice facility (driving range, tee deck, target greens, short-game area) lies about 90 m north of the course
outline (OSM way 382278772): its features are background (hole 99), not part of any hole.

## Data and what they look like

* LiDAR: OMAFRA Lidar 2016-18, Lake Erie package, flown 2017-11-21, leaf-off.
* Photo: Ontario SWOOP 2025 (2025-04-07), 16 cm, R G B NIR, leaf-off spring, registered to the LiDAR (+0.25 m east).
  Trees are bare (ground visible through them, long thin trunk shadows); greens can look pale or straw-coloured while
  fairways are green; the rough is brownish. Judge edges by texture, mowing lines and the LiDAR, not colour alone.
* OSM maps every hole: greens, tees, fairways, 117 bunkers, water, and 22 cart paths (golf=cartpath, highway=service).
  scripts/trace_paths.py also traced about 1.5 km of path lines from the photo, kept 4 m clear of the OSM paths: some
  may be real paths OSM lacks, some false; check them.
* Grand Valley GC (500 m SSE) is outside this course: its features are not part of the model.

## Changes since the 2017 LiDAR

* A conifer grove west of the central pond was stripped to bare soil between 2022 and 2025 (about E 548510-548580,
  N 4801646-4801711; a few trees remain at the NW corner): its LiDAR trees are dropped (features/trees_cleared.geojson).
  The grove south of it still stands. The bare patch should be rough or native, not a bunker.
* South of the clubhouse (about E 548840-548872, N 4801898-4801958) an area was being excavated on the April 2025 photo
  (bare soil, machines); by June 2025 it was a finished rectangular feature with a long dark interior inside a new
  cart-path loop. Its purpose is unknown: model it as rough unless the photo clearly shows water.

## Open questions (first build)

* Black tees short of the card: hole 1 426/468, hole 10 391/417, hole 11 433/442, hole 9 506/512. Look for a back deck
  (in the photo, and in dem_raw if it predates 2017) behind the current marker.
* Forward markers off any pad: Red on holes 3, 5, 8, 14, 17; White on hole 5.
