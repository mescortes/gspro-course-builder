# Westmount: QA brief

Read by the QA agents (`workflows/hole_qa.js`) before they inspect a hole.

## The course

Westmount Golf & Country Club, Kitchener, Ontario (Stanley Thompson, 1931); par 73. Holes 1-18 are the OSM golf=hole
refs. Tee sets back to front: Blue, White, Red, Gold (markers labelled B, W, R, G). Coordinates NAD83(CSRS) / UTM 17N
(EPSG:2958), heights CGVD2013. Card: Golf Canada Score Centre, verified (research/NOTES.md); some sets share a box on
some holes, and a forward (Gold) tee can be a small pad or a marker on the fairway.

## Data and what they look like

* LiDAR: OMAFRA Lidar 2016-18, Lake Erie package, flown March 2018 leaf-off, about 7 ground points/m2.
* Photo: Ontario SWOOP 2025, 16 cm, R G B NIR, leaf-off spring, registered to the LiDAR (0.25 m north shift). Trees are
  bare (you see the ground through them, and long thin trunk shadows); tall crowns lean a few metres (the photo is not a
  true ortho). Greens look pale or straw-coloured (dormant or just uncovered) while fairways are green; several west
  fairways look brown with mowing stripes; the rough is brownish. Judge edges by texture, mowing lines and the LiDAR,
  not by colour alone.
* OSM maps holes, greens, tees, fairways, bunkers and water, but no cart paths: the paths (2-2.5 m light-grey stone dust
  or asphalt strips, mostly beside tees and greens) are traced from the photo (scripts/trace_paths.py) and corrected by
  hand; add missing segments (cartpath, hole 98, a polygon about 2.2 m wide) and remove false ones.
* Structures OSM lacks (shelters) are curated in features/structures.geojson; overrides cannot add buildings.

## Changes since the 2018 LiDAR

* New back tees on holes 5 and 11 (2023-24), a longer back tee on hole 8 (2025), new boxes on hole 17 (2025) and a
  hole 14 Gold box. These show in the photo but not in the LiDAR: the model levels them as synthetic decks
  (`[tuning] level_tees`).
* The hole 12 tees were rebuilt after 2018 (one long two-terrace box in the 2025 photo); the model keeps the four 2018
  LiDAR decks, which still give the card yardages.
* Trees cleared for the hole 5 and hole 8 Blue tees: features/trees_cleared.geojson.

## Open questions

* Hole 5 Blue measures 600 against 605 (marker at the back of the 2023 deck); hole 17 White 145 against 149 (back of the
  2025 White/Red box). Both are within the 6 yd tolerance and confirmed in review.
