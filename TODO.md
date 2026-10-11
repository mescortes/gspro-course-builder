# TODO

Open items after QA round 2. Every hole scored 8/10 or more from its verifier; details are in
`research/qa/qa_round2_verdicts.json`.

## Windows side (course designer)

1. Unity 2018.2 + OPCD:
   * import the package with `unity/Editor/WestmountSetup.cs` (menu *Westmount*);
   * run `SetMeshMaterial.cs`;
   * add the 3DG Grass Renderer settings (`grass_3dg.json` values are estimates);
   * bake.

   The helper is syntax-checked (tree-sitter), not compiled.
2. GreenKeeper:
   * load `greenkeeper.json` (`gkd` blocks: tees, Thursday-Sunday pins, aim points, hazards, `pOOB`);
   * check OB along the residential lots and Inverness Drive;
   * mark the ponds as penalty areas (red or yellow per the club's local rules).
3. Optional: replant trees with Arborist, using `trees.csv` as the reference.

## Course data to confirm on site or with the club

* **Hole 5 Blue** measures 600 yd against the card's 605. Only an aim point within about 4 m of the fairway's west
  edge reaches 605 from the back of the new deck, so the card is probably rounded or measured on another line.
* **Hole 17 White** measures 148 against 149. The heights of the rebuilt (2025) decks are estimates: each synthetic
  deck sits at the polygon's mean 2018 height.
* **Holes 5, 8, 11 and 17:** the tee decks built after the 2018 LiDAR are synthetic planes. A newer LiDAR or a site
  survey would replace them.
* **Hole 14:** a 9 x 12 m rectangle of new turf at about 537207, 4810908 (sod nursery or a new forward tee).
* **Hole 15:** traced path 202 along the left fairway edge (537574-537632, 4810581-4810596) connects to nothing. It
  may be stone dust or a drainage strip.

## Model polish

* Mulch beds around the clubhouse and parking islands read as rough, because native under canopy is now wooded rough
  (`vectorize.under_canopy_labels`). Cosmetic and off the line of play.
* **Paths:**
  * the hole 12 path west of the tees is 4-4.5 m wide (sunlit asphalt plus a strip in the hedge shadow);
  * the east branch of the hole 18 tee-side path loop is not traced: NIR cannot separate it from trunk shadows.
* **Hole 12 tee pads** are LiDAR blobs, not the straight-edged terraced boxes in the photo. Yardages are exact.
* **Shelters:** footprints are from LiDAR building returns where they exist. The #4 / #13 shelter postdates the
  LiDAR, so its footprint is +/- 1 m from the photo.
