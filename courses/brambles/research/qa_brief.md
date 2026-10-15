# Brambles: QA brief

Read by the QA agents (`workflows/hole_qa.js`) before they inspect a hole.

## The course

Brambles (Coore & Crenshaw with James Duncan; Middletown, Lake County, California; opened April 2024); par 72 (the
GolfNow feed's card: the club publishes none). Zoysia tee to green, native meadow rough grazed by sheep, barrancas
(eroded drainage channels with sharp banks), one big valley oak in play (hole 4). Tee sets back to front: Back,
Middle, Front (markers labelled B, M, F). The club uses no tee markers: a tee is an area of zoysia near the GPS tee
points, often a flat deck, sometimes part of a mown area. Coordinates NAD83(2011) / UTM zone 10N (EPSG:6339), heights
NAVD88. Hole notes: research/hole_descriptions.json (playing reports and golfcourse.wiki diagrams; schematic).

## Data and what they look like

* LiDAR: USGS 3DEP CA_NorthCoastRanges B23, flown 2023-09-23 / 27, after construction (7 months before opening),
  leaf-on, 11-15 ground points/m2. Every tee was built before it, so the model has no synthetic tee decks.
* Photo: USDA NAIP 2024-05-22, 0.6 m pixels (coarse: edges uncertain by about 1 m, a small bunker is a few pixels),
  R G B NIR, registered onto the LiDAR (+0.75 m east). Zoysia fairways, tees and greens are all pale yellow-green;
  greens are slightly lighter and more uniform with smooth edges, best confirmed in the LiDAR (a smooth pad, often
  raised, with a collar). The meadow rough is darker green in the swales and tan / brown where dry. Sand bunkers are
  grey-white and rugged with grass faces, and are closed LiDAR hollows. Barranca floors are darker channels with sharp
  banks: model them as native or rough, not bunker, unless they hold sand. Gravel paths and ranch tracks are light
  grey-tan strips. NDVI barely separates turf from rough here.
* No OSM: the classifier's training labels were drafted automatically (scripts/draft_features.py ->
  features/golf.geojson, draft=yes) from GPS tee and green points (research/layout.geojson) and the photo; the model
  surfaces come from the classifier. Expect green outlines that take in banks or miss part of the putting surface,
  missing greenside bunkers, partial gravel paths.

## QA round 1 (126 override features, features/overrides/)

* Fixed by overrides: tee decks on holes 1, 2, 15 and 18 (and markers), false bunkers on bare soil and tracks, missing
  greenside bunkers, paths, the hole 4 aim point, the barranca before the 1st green.
* Fixed in the engine since: connected fairways are split between holes; unmapped and drafted bunkers must be closed
  hollows (channels are not); bunkers on this coarse photo are cut to their LiDAR pans; two tee sets never share one
  marker spot; no synthetic tee decks.
* Open: the green outlines of holes 3 and 5 take in banks (green slope p95 14 and 16 %, max 19 and 27 %).

## Open card questions

From the real decks holes 1, 7 and 18 measure short of the feed's card (hole 1 Back 524 / 531, Middle 485 / 496;
hole 7 Back 572 / 611, Middle 516 / 572; hole 18 Middle 458 / 467); the GPS points of the same feed give the same
shortfall and no source explains it. Do not invent a tee or an aim point to reach the card: these gaps are
documented in course.toml [tests] known_tee_gaps.
