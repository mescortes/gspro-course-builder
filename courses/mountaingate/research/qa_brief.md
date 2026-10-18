# MountainGate: QA brief

Read by the QA agents (`workflows/hole_qa.js`) before they inspect a hole.

## The course

MountainGate Country Club, Los Angeles (Ted Robinson, opened 1975-76): the North/South course of the club's 27 holes, par 72, in
the canyons of the Santa Monica Mountains. Holes 1-9 are the North nine (OSM golf=hole refs 1-9), holes 10-18 the South
nine (OSM refs 19-27); the Lake nine (OSM refs 10-18) is scenery, holes 19-27, outside the QA groups. Tee sets back to
front: Championship (Gold), Middle (Blue), Forward (White), markers labelled C, M, F. Coordinates NAD83(2011) / UTM 11N
(EPSG:6340), heights NAVD88. Card: the North/South card (research/NOTES.md); the Forward set is a composite.

## Data and what they look like

* LiDAR: USGS 3DEP 2025 (flown 2025-01-21), leaf-on, about 45 points/m2, classes 1 / 2 / 7 / 17 / 18 only (no vegetation or
  building class). It is the newest data and shows the course as it is.
* Photo: USDA NAIP 2024 (2024-05-06), 0.6 m, R G B NIR, late spring: the turf is green, the hillsides and the native
  areas tan; trees cast long shadows. NAIP's 0.6 m pixels blur edges: judge them by the LiDAR.
* The photo shows most of the bunker renovation and the turf converted to native planting (tan ground with scattered
  shrubs), but not the last of it: on the South nine the 2025 LiDAR has work done after May 2024 (the hole 18
  second-leg and corner bunkers, the filled hole 15 / 16 pans, the reshaped hole 15 south-west greenside bunker, the new
  cart paths from the hole 16 junction to the hole 15 green and along hole 18's second leg). There the photo texture
  disagrees with the model. Where the LiDAR shows post-May-2024 work, do not overturn the earlier rounds' overrides
  (drawn on a newer photo) with NAIP 2024 evidence; LiDAR intensity tells the new paths (like the old ones) from turf, but not freshly graded ground.
* A QA round on the 2025 LiDAR already made 113 corrections to bunkers, greens and tees (features/overrides/, reasons
  starting with the LiDAR evidence); where the LiDAR and the photo disagree on a bunker or a green edge, trust the LiDAR.
* OSM maps all 27 holes, greens, tees, fairways, bunkers, two ponds (one in play, in front of the hole 13 back tee) and
  44 cart paths. The photo path tracer is off (`[tuning] trace_paths = false`). The club's leisure=golf_course relation
  is narrower than its land: beyond it, paths OSM maps as golf paths stay cart path, other paths come out as road.
* Between the holes: canyons of chaparral (deep rough) and summer-dry native grass (native). They are scenery, not
  rough: a hillside the classifier made rough or semirough is a QA matter where it is in play.

## Changes on the course

* The bunker renovation (between the 2022 photo and the 2025 LiDAR; bunkers reshaped, moved, removed and added; some green edges rebuilt) and the native
  conversions: in the LiDAR, and in the photo except the South-nine work listed above. Rounds 1 and 2 were drawn on
  another photo (below), 1-4 m off the NAIP 2024 classification in places: small tee slivers, and bunker remnants
  over 2 m wide, can survive beside their overrides (the engine gives narrower bunker strips to the grass).

## Open questions

* Tees that no deck can bring to the card (holes 5 and 10 Forward, 17 all sets, 18 Forward) are documented
  gaps (research/NOTES.md, course.toml [tests] known_tee_gaps): do not invent tees for them.

## QA so far

* Rounds 1 and 2 ran in the standalone project on another photo (Esri World Imagery, registered to the LiDAR): 144
  override features; round 2 scored every hole 8 or 9 (`research/qa/qa_round1_verdicts.json`,
  `qa_round2_verdicts.json`, `qa/round2_context.md`).
* A round on the 2025 LiDAR, all 27 holes: 113 approved corrections.
* Tee markers and aim points the rounds locked are in `features/overrides/holeNN_meta.json`.
* Round 3 (`workflows/hole_qa.js` round 2 mode, on this engine and NAIP 2024): 16 approved changes, 11 rejected, 5
  earlier overrides corrected or removed (`research/qa/qa_round3_verdicts.json`). Every hole scores 8 or 9 except
  hole 18 (7: the photo predates its second-leg bunkers and path). Hole 5's old Middle and Forward pads are native
  planting now: its Forward marker is on the only forward deck left (`5.forward` gap).
