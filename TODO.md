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

* **Holes 5, 8, 11, 14 (Gold) and 17:** the tee decks built after the 2018 LiDAR are synthetic planes, each at the
  polygon's mean 2018 height. A newer LiDAR or a site survey would replace them.
* **Hole 12 tees were rebuilt after the 2018 LiDAR.** The LiDAR has four small separate decks (the model's pads); the
  2025 photo shows one long, straight-edged box in two terraces, about 537373-537419 E, 4810467-4810522 N. Replacing
  the pads needs the new outlines and the deck heights (a site survey or newer LiDAR); the markers would then move,
  so the yardages (exact today) would need checking again.

## Model polish

* Mulch beds are hand-picked overrides around the clubhouse, pro shop and parking islands
  (`clubhouse_mulch.geojson`, `grounds_mulch.geojson`). Shrub beds under trees elsewhere still read as rough: in the
  spring photo they look like the leaf litter and dormant lawn around them (same Lab colour and NDVI).
* **Shelters:** footprints are from LiDAR building returns where they exist. The #4 / #13 shelter postdates the
  LiDAR, so its footprint is +/- 1 m from the photo.
