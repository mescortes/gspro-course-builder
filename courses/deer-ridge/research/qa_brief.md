# Deer Ridge: QA brief

Read by the QA agents (`workflows/hole_qa.js`) before they inspect a hole.

## The course

Deer Ridge Golf Club, Kitchener, Ontario (Thomas McBroom; the club dates itself to 1991); private, par 72, on the
Grand River flood plain. Holes 1-18 are the OSM golf=hole refs. Six tee sets, back to front: Black, Gold, Silver,
Bronze, White, Copper (markers labelled Bl, G, S, Br, W, C). Coordinates NAD83(CSRS) / UTM 17N (EPSG:2958), heights
CGVD2013. Card: the club's 2026 card (research/NOTES.md, course.toml [scorecard]); combination sets reuse the same
boxes, and on holes 4 and 13 Copper plays from the White yardage.

The OSM greens that are no hole's (practice greens) and the driving range are background (hole 99).

## Data and what they look like

* LiDAR: OMAFRA Lidar 2016-18, Lake Erie package. Inside the course every point was flown 2017-11-21, leaf-off.
* Photo: Ontario SWOOP 2025 (2025-04-07), 16 cm, R G B NIR, leaf-off spring, registered to the LiDAR (shift 0.25 m east,
  0.25 m south). It was flown three days after a Grand River flood peak:
  * a wet corridor (about E 546175-546365, N 4805690-4805815, running NW as a diagonal channel to about E 546070-546250,
    N 4805770-4805900) and a flooded backwater along the south bank (about E 546230-546310, N 4805600-4805640) look
    dark brown or like open water. On the ground they are turf or rough: they are not water, bunkers or native;
  * the pond at about E 547136-547260, N 4806309-4806428 (6,700 m2) is real water, brown because it is turbid.
  Trees are bare (ground visible through them, long thin trunk shadows); greens can look pale while fairways are
  green; the rough is brownish. Judge edges by texture, mowing lines and the LiDAR, not by colour alone.
* OSM maps every hole: greens, 74 tees, 78 bunkers, 25 fairways, 4 water hazards and a lateral water hazard (a wetland).
  Hole 1's green and four tees are tagged leisure=pitch + sport=golf; the engine now keeps them as golf (they used to
  become courts). Paths: 39 OSM ways (golf=path + highway=path) are cart paths, and scripts/trace_paths.py traced 59
  more lines (5.0 km) from the photo, kept clear of the OSM ones. Some are real paths OSM lacks, some false (tree
  rows, mowing lines, shadows, the flood corridor's edges): check them.
* Lawns round the course (18 ha the classifier called green, e.g. in Homer Watson Park) are rough: the engine drops
  classifier greens more than 15 m off the course outline. Inside the outline, a green the photo does not show is a
  QA matter.

## Changes since the 2017 LiDAR

* Forward decks enlarged or built after the flight: 2020 forward tees on holes 1, 6, 7 and 9, and the 2021 capital
  budget's forward tee construction on 1, 5 and 12. They show in the photo but not as LiDAR decks: where OSM maps
  them, the model levels the tee polygon as a synthetic deck (`[tuning] level_tees`).
* The Copper set is new in 2025, probably markers on existing ground: no new pads appear between the 2020 and 2025
  photos at the estimated spots on 1, 5, 12, 14 and 18. The first build puts Copper 15-168 yd from any pad on 17
  holes. Where no deck can deliver the card yardage, pin the Copper marker (meta "tees_utm": {"copper": [e, n]}) on the
  line of play at the card distance, on mown ground (fairway or a forward deck); do not draw a new tee polygon for it.
* White is 4-57 yd off on holes 1, 3, 6, 7, 10 and 13, and Black / Gold 5-6 yd off on 3, 8 and 10: check for a
  missing or wrongly assigned pad, or a forward deck the model has not levelled, before pinning a marker.
* The greens complexes were rebuilt in 2010 and the June 2017 flood was repaired before the flight: the LiDAR shows
  the current greens and bunkers.

## Open questions

* The 2026 card's back-nine combination arrows for Gold/Silver and Bronze/White look misplaced; the 2025 layout matches
  the rated totals. Combinations do not change the boxes.
