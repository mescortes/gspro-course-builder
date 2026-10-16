# QA round 2 context (what changed since round 1)
- The aerial imagery was registered to the LiDAR: +2.75 m east (measured on 123 bunkers). All surfaces were re-derived.
  Round-1 override polygons drawn on the old photo were shifted +2.75 m east (frame "lidar"); a few tagged "lidar" by
  round-1 verifiers were NOT shifted (holes 7 and 9 partly). Check that overrides still line up with the real features.
- New automatic rules: a tee pad must overlap a mapped OSM tee or be a flat raised LiDAR deck (else -> fairway/rough);
  a bunker must overlap a mapped OSM bunker or be a LiDAR hollow (else -> cart path/rough); mapped OSM bunkers hidden by
  shade are kept when the LiDAR confirms the hollow; fairway pieces < 150 m2 are dropped; OSM service roads inside the
  course are cart paths; water outranks every surface; clear banks (> 12 % slope within 2.5 m of a green edge) are trimmed
  from greens; new surface "deeprough" = chaparral/brush (dense low LiDAR canopy, >= 3 m from mown turf).
- Tee decisions (lead): hole 12 Forward on OSM pad 1157465526 (~96 yd), hole 18 Forward on OSM pad 1157472363 (~446 yd,
  card 481: documented gap), hole 17 all three markers on the OSM decks (~15-20 yd short of the card: documented gap),
  hole 10 Forward on its real pad (~358 vs 366). Forward tees without a pad that can deliver the card fall back to a
  "fairway_marker" on the line of play at the card distance.
- Known accepted: green mean slopes up to ~5.5 % (holes 3, 5) are real hillside tilts.
