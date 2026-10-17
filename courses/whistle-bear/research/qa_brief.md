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
* **Water in reaches** ([#15]): a water body whose level falls more than 0.3 m is cut across into reaches, each with
  its own flat water plane. Here that is the 13,017 m2 pond between holes 8, 9 and 10 (OSM way 936553651), which falls
  1.65 m at a rock cascade, so one step in its water is expected (round 2 found the cut in the wrong place: see
  below).
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

## QA round 2 (65 override features, 1 meta file)

Run 2026-10-17 on the clean build above (`hole_qa.js` round 2: 6 inspectors, 3 verifiers, 18 minutes). Two
proposals, both approved; none rejected; no round-1 override found misaligned or harmful (the four redundant ones are
kept). Verifier scores: 9 on every hole except 8 (8, for the water step below). test_course: 137 passed, 4 skipped.

* Fixed by overrides: a false traced cart path along a lot-boundary fence behind the conifer rows right of hole 2
  (73 m2 of path, rough 99), and the unmown long-grass bed with three conifers short right of hole 9's green (928 m2,
  deep rough 99: straw-coloured with a crisp mowing edge, NDVI 0.09 against 0.31 round it, a low mound in dem_raw).
* Left as they are:
  * Hole 11 Red stands at the front of the White deck at 330 / 324 (+5.7); the forward deck (117 m2 at E 548787
    N 4801665) would give at most 318 (-5.9), no better.
  * Hole 14 Blue 182 / 188 (-6): the marker is at the back of the Blue deck with the cart path behind it, and the
    Gold deck's front gives 191-194.
  * Hole 3 Red is the engine's fairway marker at 410: the forward decks give about 452 and 374. The 44 m2 deck at
    E 548768 N 4801462 (OSM tee 937313439) is hole 3's but unused; it may be a forward tee for hole 8 (about 95 yd,
    card Red 90). It changes no marker.
  * The 28 m2 "bunker" behind hole 12's Red deck (E 548604 N 4801939) is the club's bear-paw logo in flagstone (OSM
    maps it as 10 tiny `natural=sand` pads); out of play.
  * Small cosmetic notches in the green outlines of 2 and 13.
* Left for the engine (seen on several holes, or wrong in an engine rule):
  * **Water reaches cut in open water.** On the pond between 8, 9 and 10 the reach cut (60 m shoreline radius)
    falls 20-45 m west of the rock cascade (E 548891-548900 N 4801564-4801574), so about 1,000 m2 of the upper pond
    (E 548845-548899, N 4801537-4801574) takes the lower plane, 306.35 m, though the LiDAR water there is at 308.05:
    a 1.4 m step in the water and about 1.7 m of exposed bank right beside hole 10's green. The cut should fall where
    the shoreline level changes. (Holes 8, 9.)
  * **Yardage-book maps paint rough over everything.** `make_maps.py` fills each polygon's exterior and draws its
    holes as empty patches, so the large rough polygons (one is 853,337 m2 with 263 holes) cover the fairways,
    greens, bunkers and water drawn before them: output/<slug>/maps/holeNN_map.png and course_map.png show rough,
    trees and paths only. Deer Ridge's course map has the same fault, so it is in every course's maps and bundle.
    (Reported on hole 10; every hole map shows it.)
  * **Off-course native listed as hazards.** holes.json lists native areas wholly outside the course outline:
    ploughed fields across Dickie Settlement Road, which the classifier calls native (69,952 m2 on hole 3, 512 m2 on
    2), and patches past the west edge (16, 17). Hazards should stay inside the outline. (Holes 1-3, 16, 17.)
  * Still open from round 1: small false native blobs on mown rough (holes 5, 10, 12-15; on 14 and 15 they are
    listed as hazards); `trace_paths.py` tracing linear features that are no paths (here a fence line, on 2); OSM
    middle vertices kept as aim points on straight holes (3, 6, 12, 18; under 0.3 yd each here, so harmless); front
    pin yardages measured from a bunker cut-in (7: -1.4 yd, 10: -8.5 yd, 16: -5.3 yd); bunker islands drawn as sand
    in the GreenKeeper SVG.
  * One hole so far, an engine note rather than a pattern: deep rough comes only from the CHM shrub layer (0.6-5 m
    cover), so unmown long grass under 0.6 m is never deep rough (hole 9, fixed by override).

[#11]: https://github.com/mescortes/gspro-course-builder/pull/11
[#15]: https://github.com/mescortes/gspro-course-builder/pull/15
[#16]: https://github.com/mescortes/gspro-course-builder/pull/16
[#18]: https://github.com/mescortes/gspro-course-builder/pull/18
