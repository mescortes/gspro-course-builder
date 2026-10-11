# QA round 2: what changed since round 1

Round 1 (12 agents, `build/qa/qa_round1_verdicts.json`) approved 71 corrections and rejected 10; it wrote 5 meta files. The model was
rebuilt from `paths` through `views` with those overrides and the pipeline fixes below. All images in `build/qa/holeNN/`
are from the rebuilt model.

## Pipeline fixes (the recurring round-1 issues)

1. **Leaf litter as native.** With a leaf-off photo, `native` under LiDAR canopy is now wooded rough
   (`vectorize.under_canopy_labels`). Open mulch beds away from trees stay native. Check that no orange blobs are left
   in the woods, and that real mulch beds and native areas survive.
2. **Bunkers in branch shadow.** Sand in thin shadow counts as sand (NDVI near 0, `vectorize.sand_mask`), but only
   where it connects to sunlit sand. An unmapped bunker must also be a LiDAR hollow *on the course*. Result: 58
   bunkers, covering all 48 OSM bunkers, plus 10 unmapped ones (5 are the practice-area bunkers). Check the back-left
   #6 bunkers and look for any bunker on bare soil.
3. **Cart-path gaps.** `trace_paths.bridge` joins collinear dead-ends (short gaps, then gaps up to 35 m when the
   corridor is clear). Check that bridges follow the real path and do not cut across turf.
4. **Off-course sidewalks** (holes 7 and 11) are now `road`, not cart path, more than 5 m outside the golf-course
   boundary.
5. **False tees on flat ground** (holes 7 and 18: fairway edges, swale bottoms). A non-OSM tee must now be a built
   deck: part of its surroundings must fall away *below* it, and it must lie in the first ~45 % of the hole.
6. **L-shaped and composite tee pads.** Markers now slide along any line of play across the pad, not only the one
   through the centroid. Check that markers are on pads and yardages match the card.
7. **New tees with no deck in the 2018 LiDAR** get a synthetic deck: a plane of at most 1 % at the tee's mean height,
   feathered into the ground with banks of about 1:3 above the ground slope (`build_terrain_mesh.level_tees`). Real 2018
   decks (plane std < 6 cm, fall <= 3.5 %) and polygons over 500 m² are left alone. See the list below; check the
   hillshade at each one.
8. **Steep greens.** Pin candidates relax from <= 3 % up to <= 5 % slope until at least 12 % of the green is pinnable
   (`hole_data.pin_candidates`). Hole 14 had 3.7 % at <= 3 %. `holes.json` → `green.pin_slope_limit_pct`.
9. **Shelters.** Three shelters OSM lacks were added in `features/structures.geojson`:
   * #4 / #13 (newer than the LiDAR, synthetic hip roof, footprint +/- 1 m from the photo);
   * beside the #15 Blue tee;
   * between #13 and #14 (both from LiDAR building returns).

## Override housekeeping

* Duplicate cart-path links removed: `hole05` features 1 and 2, which doubled `hole07`'s links (round-1 hole 7 verifier).
* The `hole04` / `hole13` Oasis-path overlap was left. It is about 3.5-4 m wide at N 4811020-030, over the patio stone.
* Every override feature now carries `"frame": "lidar"`.
* `features/overrides/practice.geojson` (hole 99): the short-game practice green at E 538093-538130, N 4810915-4810945,
  with a 1 m fringe. It is pale and dormant in the photo, and the path tracer had taken its edge for a cart path.
* The tee rule dropped 7 build-3 pads, none with a pad-placed marker:
  * hole 1: 67 m² at 537690, 4810960 (round-1 false tee);
  * hole 7: 86 m² at 536949, 4810663 and 70 m² at 536977, 4810765 (round-1 false tees);
  * hole 15: 143 m² at 537495, 4810586 (flat, no fill bank; Gold was already a fairway marker) and 50 m² at
    537392, 4810602;
  * hole 18: 143 m² at 537272, 4810998 and 136 m² at 537337, 4810925 (round-1 false pads).
  If one of these is a real tee, restore it with a `tee` override.
* Snapshot of the overrides before round 2: `build/qa/snapshots/overrides_before_r2/`.

## Open items from round 1 to check

* **Hole 5:** Blue measures about 600 against a card of 605 even at the back of the new deck. The other tees are also
  1-5 yd short at their pad backs, so the aim point (line of play) is the likely cause. Check the aim point against
  the fairway.
* **Hole 8:** the new 2025 back tee is now levelled (it had 2.1 m of relief under the pad). Check the hillshade and the
  White, Red and Gold assignment.
* **Hole 11:** the rebuilt tees (about 2023) sit on 7-19 % planes in the 2018 DEM. They are now levelled. Check that
  the pad outlines match the 2025 photo boxes, not 2018 shapes.
* **Hole 14:** Blue 371 / 375. A possible post-2018 forward tee (about 8 x 13 m) sits at about 537206, 4810909.
* **Hole 15:** the Gold tee is probably the LiDAR deck at E 537514-537523, N 4810567-4810572.5. The current polygon
  (13 m²) covers only part of it, and Gold is a fairway marker in the rough. Suggested: enlarge the pad to the deck and
  pin Gold at about [537517.5, 4810570.0], which is 315.5 yd, matching the card. Verify before applying.
* **Hole 15:** the path between the Blue and White tees is about 4 m wide; the override covers only 2.5 m.
* **Hole 9:** the fairway "loop" at 537450-537458, 4811040-4811080 may be an intermediate-cut band.
* **Hole 13:** the shelter patio and the short walkway SSW of it are not modelled.

* **Oversized tee polygons** (over 500 m², not levelled, left for you):
  * 836 m² at 537303, 4810870;
  * 516 m² at 537314, 4810945;
  * 544 m² at 537661, 4810719.

  Each is either a real multi-tee deck or an outline that swallowed a bank or approach. If the latter, cut it back to
  the deck (`rough` or `semirough` override).

## Tees levelled to a synthetic deck in this build

The list is also in `build/qa/levelled_tees.txt`. The expected ones are the post-2018 tees on holes 5 (back), 8 (2025
back tee) and 11 (all rebuilt). For every other entry, check on `build/dem_raw.tif` and the photo whether the
polygon is really a deck. Large fill (over about 0.7 m) usually means the outline runs down a bank. If so, cut the
polygon back to the deck with a `rough` override; the levelling follows the polygon.

* hole 5: 242 m2 at 537065, 4811000: cut 0.46 m / fill 0.60 m
* hole 5: 228 m2 at 537077, 4811030: cut 0.16 m / fill 0.62 m
* hole 8: 349 m2 at 537152, 4811079: cut 0.20 m / fill 0.16 m
* hole 12: 98 m2 at 537388, 4810501: cut 0.13 m / fill 0.64 m
* hole 17: 262 m2 at 537313, 4810842: cut 0.41 m / fill 1.41 m
* hole 11: 152 m2 at 537860, 4810545: cut 0.90 m / fill 0.87 m
* hole 11: 12 m2 at 537882, 4810557: cut 0.07 m / fill 0.31 m
* hole 11: 70 m2 at 537924, 4810570: cut 0.64 m / fill 1.01 m
* hole 5: 110 m2 at 537071, 4811061: cut 1.32 m / fill 0.68 m
* hole 8: 81 m2 at 537124, 4811069: cut 1.21 m / fill 1.24 m
* hole 11: 154 m2 at 537891, 4810555: cut 0.27 m / fill 0.26 m
* hole 11: 63 m2 at 537814, 4810523: cut 0.28 m / fill 0.15 m
* hole 18: 138 m2 at 537301, 4810974: cut 0.14 m / fill 0.74 m
