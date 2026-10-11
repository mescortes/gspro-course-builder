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
* **Hole 17 White** measures 145 against 149 (the pinned marker is at the back of the 2025 box). The heights of the
  rebuilt (2025) decks are estimates: each synthetic deck sits at the polygon's mean 2018 height.
* **Holes 5, 8, 11 and 17:** the tee decks built after the 2018 LiDAR are synthetic planes. A newer LiDAR or a site
  survey would replace them.
* **Hole 12 tees were rebuilt after the 2018 LiDAR.** The LiDAR has four small separate decks (the model's pads); the
  2025 photo shows one long, straight-edged box in two terraces, about 537373-537419 E, 4810467-4810522 N. Replacing
  the pads needs the new outlines and the deck heights (a site survey or newer LiDAR); the markers would then move,
  so the yardages (exact today) would need checking again.
* **Hole 14:** a 9 x 12 m rectangle of new turf at about 537207, 4810908 (sod nursery or a new forward tee).
* **Hole 15:** traced path 202 along the left fairway edge (537574-537632, 4810581-4810596) connects to nothing. It
  may be stone dust or a drainage strip.

## Model polish

* Mulch beds around the clubhouse and parking islands read as rough. The classifier rarely calls them native (its
  colour seeds need open ground, and every bed is under a tree), and no rule can pick them out of this photo: the
  dormant spring lawns beside them have the same Lab colour and NDVI (L* 29-44, a* -5 to +6, NDVI 0 to 0.3 for both).
  A summer photo, or hand-drawn overrides, would fix it. Cosmetic and off the line of play.
* **Shelters:** footprints are from LiDAR building returns where they exist. The #4 / #13 shelter postdates the
  LiDAR, so its footprint is +/- 1 m from the photo.
