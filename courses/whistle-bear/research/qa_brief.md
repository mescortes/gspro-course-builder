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

## QA round 1 (63 override features, features/overrides/)

* Fixed by overrides: cart paths traced along tree rows, hedges and mowing lines; false bunkers (pond-bank grass);
  tee decks reassigned to the holes they serve (White and Red on hole 5, two decks to hole 8); the grass islands in
  hole 5's big bunker; a hole-4 bunker that was hole 99.
* Black tees: hole 10 now matches the card. Holes 1 (426 / 468) and 11 (433 / 442) cannot reach it from any deck and
  are documented in course.toml [tests] known_tee_gaps: do not invent a tee. Every other marker is within 6 yd of the
  card; the largest gaps are 9 Black -6, 11 Red +6, 14 Blue -6 and 17 White -4 (look for a better-fitting deck before
  moving one).
* Left for the engine (seen on several holes): false green and fringe under the forest canopy (holes 17, 18) and on a
  green metal roof; traced paths along shadows and forest edges; small false native blobs on mown rough (holes
  13-15); OSM middle vertices kept as aim points on straight holes; front pin yardages measured from a bunker
  cut-in (holes 7, 10); bunker islands drawn as sand in the GreenKeeper SVG.

## Engine changes since round 1 (the model you inspect is built with them)

Round 1 looked at a build from before these engine changes. The model in build/ and output/ now has all of them
(rebuilt clean on main f3d1312). They are engine rules: do not redo or undo them by hand. If one of them looks wrong
on several holes, describe it once with category "recurring".

* **Off-course lawns** ([#11]): a classifier green more than 15 m outside the course outline (`leisure=golf_course`)
  is rough. About 48,600 m2 of false green on the lawns and fields round the course went. OSM-mapped greens stay
  green wherever they are (the Academy's nine target greens). A green the photo does not show inside the outline is
  still a QA matter.
* **Forward tees off the line of play** ([#15]): an OSM tee that no line of play claims goes to the hole whose card it
  plays. The Red decks on 5, 14 and 17 now belong to their holes; the four Academy and range tees stay hole 99.
  Four round-1 overrides now say what the engine already gives (the Red tees on 5, 14 and 17, and hole 18's second
  left fairway bunker): they are redundant but harmless, so leave them.
* **Semirough takes its fairway's hole** ([#15]): the semirough ring round a fairway carries that fairway's hole (it
  used to be hole 99). A semirough ring with this hole's number is expected; rings round no hole's fairway stay 99.
* **Deckless forward markers** ([#15]): a tee set that no deck delivers at the card distance is placed at the card
  distance on the best ground within 20 m of the back tee's first leg (the hole's fairway, its decks, semirough, then
  rough), at least 5 m from bunkers, water and native areas. Such a marker has `"source": "fairway_marker"` in
  holes.json. On this build that is hole 3's Red (410 yd, as on the card); every other marker stands on a pad.
* **Water in reaches** ([#15]): a water body whose level falls more than 0.3 m (the creek, 1.65 m) is cut across into
  reaches, each with its own flat water plane. Steps in the creek's water are expected.
* **Wetland hazards and cycle trails** ([#16]): nothing to do here. Every Whistle Bear water hazard is mapped
  `natural=water` (the wetland rule is for hazards mapped `natural=wetland`), the marshes OSM maps are no hazards, and
  OSM has no `highway=cycleway` in the area.
* **Small mapped fairways** ([#16]): an OSM fairway under 300 m2 (a collection area, a drop zone) is fairway as mapped,
  below greens, bunkers, tees, paths and water. Both of Whistle Bear's are in the Academy (hole 99): 52 m2 at E 548789
  N 4802186 and the 133 m2 artificial-turf ring at E 548705 N 4802313.
* **Woodland greens** ([#16]): a classifier green lying half or more under the closed canopy is woodland floor in the
  trees' shadow, so rough. Two such hole-99 greens in the woods went (157 m2 at E 548666 N 4802027, 64 m2 at E 548096
  N 4801904).
* **No second hazard inside a penalty area** ([#16]): surfaces lying mostly inside a water hazard are not listed as
  hazards again.
* **Mesh** ([#18]): a vertex snapped onto another boundary's segment splits it. No segment on Whistle Bear needed it.

What that leaves of round 1's "Left for the engine" list:

* False green under the canopy and on the roof: gone. Every hole-99 green left is an OSM-mapped practice or target
  green, plus the Academy's one unmapped target green (181 m2 at E 548854 N 4802352, real). Fringe or semirough left
  in the woods round holes 17 and 18 is still worth a look.
* Still open, for the engine, not for overrides: traced paths along shadows and forest edges (remove a false one on
  your hole, as in round 1, but report the pattern as recurring); small false native blobs on mown rough; OSM middle
  vertices kept as aim points on straight holes (set `aim_points_utm` only where an aim point makes the hole play or
  measure wrong); front pin yardages measured from a bunker cut-in; bunker islands drawn as sand in the GreenKeeper
  SVG.

[#11]: https://github.com/mescortes/gspro-course-builder/pull/11
[#15]: https://github.com/mescortes/gspro-course-builder/pull/15
[#16]: https://github.com/mescortes/gspro-course-builder/pull/16
[#18]: https://github.com/mescortes/gspro-course-builder/pull/18
