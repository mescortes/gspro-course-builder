# MountainGate: research notes

Research of 2026-10-10 in the standalone MountainGate project: researchers, each claim re-checked by a verifier from
primary sources (raw results in `ns_research.json`; hole notes in `hole_descriptions.json`).

## The course

* MountainGate Country Club, 12445 Mountaingate Drive, Los Angeles, CA 90049; private. 27 holes in three nines (North,
  South, Lake) by Ted Robinson; the course opened in 1975-76 (sources give 1975, 1976 or 1981). Built on the former Mountaingate landfill (closed 1980)
  in the canyons of the Santa Monica Mountains; not damaged by the January 2025 Palisades fire.
* The model is the North/South course: North 1-9, South 10-18. The Lake nine is scenery (holes 19-27).
* Hole notes: N2 a wide, shallow green wrapped round a deep front bunker with a steep bank behind; N3 trouble left;
  S2 (hole 11, stroke index 1) a sharp dogleg left round a canyon to a peninsula-like green; S3 (12) a forced carry
  over a canyon, a pond below right; S4 (13) a dogleg left over native brush to an elevated green, a pond in front of
  the back tee; S9 (18) a severe dogleg left, uphill finish.
* Turf: kikuyu fairways and rough (little roll), firm fast greens (bent / poa); bright white-cream bunker sand. The
  hillsides between the holes are chaparral and summer-dry native grass.
* Clubhouse (OSM 419975852, 1976 / 1981): angular mid-century-modern low-rise, wood and glass, charcoal low-slope roofs.

## Scorecard

* The North/South card (golfingrecord.com, cross-checked against offcourse.co and the greenskeeper.org per-nine cards):
  Championship (Gold) 6719, Middle (Blue) 6358, Forward (White) 5667 yards; par 72 (36 / 36). Men's stroke index
  16, 10, 6, 18, 8, 2, 14, 4, 12 | 15, 1, 13, 9, 5, 11, 17, 7, 3.
* Ratings / slopes, men: Gold 73.2 / 134, Blue 71.6 / 132, White 68.3 / 123; women 80.4 / 143, 78.3 / 139,
  74.7 / 129 (women's par 73: hole 8 is a par 5 for them). The sources disagree on the women's stroke index, so
  course.toml gives everyone the men's (`women = "same"`).
* Older 6,766-yard cards (the GolfPass per-hole table, opengolfapi's back nine, BlueGolf) are out of date.
* The Forward set is a composite (on 10-13 it is the old red tee).

## Data

* LiDAR: USGS 3DEP `CA_2025LosAngelesPostWildfire_C25` (work unit CA_LAPostWildfire_Palisades_C25), flown
  2025-01-21, leaf-on (coast live oak, pines, eucalyptus and chaparral are evergreen; only the sycamores are bare).
  About 45 points/m2 and 16-18 ground points/m2; classes 1 / 2 / 7 / 17 / 18 only (no vegetation or building class; 17:
  bridge decks), LAS 1.4,
  NAD83(2011) / UTM 11N (EPSG:6340) + NAVD88 (GEOID18) metres. Nine 750 m tiles cover the build extent
  (`tnm_lpc.json`: a National Map query round the clubhouse, listing 5 of them).
* A straight swale about 0.5 m deep runs south-west to north-east across the North nine (e.g. E 362600, N 3775349).
  Both flight lines agree, so it is real ground: the stream / drainage line OSM maps (way 1059731972) across N1, N2,
  N8 and N9.
* Photo: USDA NAIP 2024 (California, quarter quad m_3411861_nw, flown 2024-05-06 by its file name in the service's catalogue), 0.6 m, R G B NIR, public domain,
  from the USDA FPAC ImageServer (the service keeps only the latest year per state). It shows most of the
  bunker renovation and the turf-to-native conversions between the holes that the 2025 LiDAR has (below). NAIP 2022 (2022-05-11, on
  USGS The National Map), which the first port used, predates both.
* Backdrop: the 3DEP 1 m DEM tile x36y378 of the same 2025 survey, gaps (19 % of the 5 km square) from LA County's
  2023 survey (CA_LosAngeles_B23) (`tnm_dem1m.json`). No public DSM.
* Not used: Esri World Imagery (its terms do not allow redistributing derived textures; the standalone build used it)
  and LA County's LARIAC imagery (licensed to its participants only).

## What changed on the course

* A bunker renovation between the 2022 photo and the 2025 LiDAR (no published date): bunkers reshaped, moved, removed and added, and some green edges rebuilt. The 2025
  LiDAR shows all of it, the May 2024 photo most of it (not the hole 18 second-leg and corner bunkers, the filled hole
  15 / 16 pans, the reshaped hole 15 south-west greenside bunker or the new cart paths on holes 15, 16 and 18); the
  first port's NAIP 2022 photo none of it. A QA round on the 2025 LiDAR
  (hillshade and depths; an inspector and an adversarial verifier per three holes, all 27 holes) redrew bunkers, greens
  and tees to the 2025 ground: 113 approved corrections (in `features/overrides/`, LiDAR evidence in each
  feature's `reason`).
* Turf converted to native planting (tan ground with scattered shrubs) between several holes, visible in the 2024 photo.

## OSM

OSM maps all 27 holes: greens, tees, fairways, bunkers, the two ponds and 44 golf=cartpath ways (so the photo path
tracer is off: `[tuning] trace_paths = false`). Its golf=hole refs number the nines North 1-9, Lake 10-18, South 19-27
(checked against the pars); course.toml `[holes.osm_ref]` maps them onto the card. The club's leisure=golf_course
relation (5201230) is two outer rings (30.3 and 41.5 ha); the club's land is wider: 12 of the 44 cart-path ways (6 % of their
length) run outside it.

## Out of bounds and penalty areas

The standalone build derived the club's OB and penalty areas from the LA County parcels and the canyons, edited in its
metadata QA: `ob.geojson` (the property perimeter, 110.5 ha, and 44 inner OB areas: homes, roads, the clubhouse) and
`penalty_areas.geojson` (34 canyon, 3 water and 1 watercourse areas, all red). The engine does not model OB or penalty
areas; they are kept here for the GreenKeeper work on the Windows side.

## GreenKeeper facts

For the GreenKeeper course file: course name "MountainGate Country Club - North/South"; Los Angeles, California, USA;
the clubhouse at 34.10827 N, 118.48776 W, 1329 ft (405 m, USGS 1 m DEM); keywords Mountain, Parkland. GreenKeeper has no
Gold tee slot: Gold goes in Black (course.toml `[[tees]] gkd_slot`).

## Card against the ground

Every marker stands on a tee pad (the QA rounds moved misplaced ones onto real decks). Where no deck delivers the card, the marker stays on the deck
(yards, measured tee -> aim points -> green centre / card, from the build's holes.json):

* hole 5 Forward: the old Middle and Forward pads (OSM tees 1157492258 / 59) are native planting now (no deck in the
  2025 LiDAR, tan ground with shrubs in the 2024 photo); the marker is on the only forward deck left, a flat raised
  turf island OSM does not map (423 / 467; QA round 3);
* hole 10 Forward: the small forward pad at the east end of the tee complex, the only forward deck (358 / 366);
* hole 17, all three sets: the three OSM / LiDAR decks, whose spacing matches the card's, all 13-16 yd short
  (434 / 450, 416 / 430, 369 / 382; the research measured the OSM tees 8-13 yd short too);
* hole 18 Forward: the only forward pad (447 / 481; the card's Forward set is a composite).

Every other tee is within 6 yd of the card (hole 13 Forward 219 / 224 and hole 18 Middle 535 / 540 on their real
decks). No tee was invented; course.toml `[tests] known_tee_gaps` records the gaps.
