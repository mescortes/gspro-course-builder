# Lessons: why the engine is the way it is

Technical lessons from building MountainGate, Westmount, Brambles and Whistle Bear, kept from the original playbook
(the procedure is now [PLAYBOOK.md](PLAYBOOK.md)). Paths that start with `features/`, `research/`, `data/`, `build/`
or `output/` are the course's folders (`courses/<slug>/...`, `data/<slug>/`, `build/<slug>/`, `output/<slug>/`);
course values said to be in `scripts/config.py` are in `courses/<slug>/course.toml`.

## Viewer and visual verification

* `scripts/devserver.py` sends `Cache-Control: no-store`. Changing only the URL **hash doesn't reload the page**:
  add a cache-busting query (`?v=N`) or call `location.reload()` in its own call. A reload cuts off the script that
  triggered it.
* When the browser pane is **hidden, `requestAnimationFrame` is paused**: counters and animations don't update. Use
  `window.__shot(name, w, h)`, which updates LOD and grass, renders once and POSTs the PNG to `build/shots/`.
  * `window.__go('h13-approach')` and similar set cameras.
  * `window.__view` exposes `{camera, controls, scene}` for custom cameras (model frame: x = E − ORIGIN_E,
    y = H − BASE_H, z = −(N − ORIGIN_N)).
* Combine shots into a contact sheet with PIL and Read the image: many issues are only visible there, such as giant
  normal-map blobs on water, blades rendered as dark hairs, or a camera below ground.
* The viewer loads `../output/<config.MODEL_NAME>.glb`, `../output/holes.json` and `../output/gspro/grass_3dg.json`.

## Technical lessons (why the code is the way it is)

### Rasters and classification

* Stream the LAZ files once into per-tile ground buckets with 12 m overlap, then a per-tile TIN, to get a 0.25 m DEM.
  This scales past one hole.
* The classifier over-predicts "cart path" course-wide. Trust it only next to mapped paths.
* **The classifier is deterministic** (checked at Westmount: two runs, bit-identical `classes.tif` and `proba_u8.npy`).
  The forest's threaded `predict_proba` sums trees in thread order, so probabilities jitter in the last float bits,
  but that never survives the uint8 rounding or the argmax. If a rebuild's surfaces move, look at its inputs (OSM,
  overrides, `features/structures.geojson`, package versions) before suspecting noise.
* **Bunkers.**
  * Sand colour gates them: L* > 66, low chroma.
  * A confident classifier inside a mapped OSM bunker covers shaded sand.
  * Then **trim clearly green pixels** (a* < −14) outside canopy, because the classifier bleeds onto grass faces.
  * Keep a bunker only if it overlaps OSM or is a LiDAR hollow.
* **Tees.**
  * Keep one if it overlaps an OSM tee, or is a flat **built** deck (`vectorize.is_deck`: part of the ring around it
    falls away *below* it) in the first ~45 % of some hole's line of play. Otherwise it is a lawn, terrace, court
    apron, swale bottom or fairway edge.
  * Markers slide along any line of play across the pad (`hole_data.pad_axes`; L-shaped complexes have their
    centroid outside the pad), nearest the centre line. If no pad can deliver the card yardage, pin the marker in
    `holeNN_meta.json` and document the gap.
  * Tees built after the LiDAR survey get a synthetic deck (`build_terrain_mesh.level_tees`); see §11b.
* **Greens.** Trim banks steeper than 12 % within 2.5 m of the edge. 8 % split tiered greens. Hillside greens can
  average 6 % on the bare LiDAR; test against the raw LiDAR, not a fixed number.

### Overrides

* Later overrides win and cut everything earlier.
* Remnants a cut leaves below vectorize's minimum part for their surface (0.25 × `MIN_AREA`, at least 0.05 m²; 2.5 m²
  for a bunker) must be merged into the cutting override. Dropping them leaves gaps; keeping them left 0.1-1.3 m²
  bunkers with 10 cm lips and 0 m² GreenKeeper hazards (`assemble_features.min_part`).

### Mesh

* One conforming constrained Delaunay triangulation (`triangle`) with every boundary as a constraint, so there are
  no cracks or T-junctions.
* Snap-round to 1 cm and remove needle angles. On "Ran out of precision", retry on 3 cm, then 6 cm grids.
* Label faces by constraint-bounded components with a 0.125 m label-raster majority. **Thin rings** (10 cm lips,
  15 cm water edges) need an exact centroid-in-ring post-pass.
* Use fine triangles only in the detail zone (playable holes), coarser on scenery holes.

### DEM blending on greens, tees, paths and bunkers

* A masked normalised convolution is biased toward the interior on slopes. Debias it with a large-scale unmasked
  trend (exact for planes).
* Extend only the **correction** outward, continuously. Falling back to the raw DEM where the mask weight dies made
  a 6–8 cm ring.

### Water

* The level is the 20th percentile of the shoreline − 5 cm.
* Carve a shelving bed: 3 cm at the shore, +0.35 m per metre, at most 1.2 m.
* Raise the land inside the plane's outset to level + 2 cm (berm).

### Textures and colour

* Recolour each texture so its mean equals the surface's median photo colour.
* COLOR_0 then only carries brightness variation. Strong tints turned dry blades purple.
* Mowing stripes follow each hole's line of play. Canopy AO darkens under trees.
* Backdrop shadows: a pixel-local tone-curve lift. A local-mean lift made haze.

### Heightmap

* Unity samples sit on the corners: 2^n + 1.
* Sink the terrain 5 cm below the meshes (no z-fighting), and feather into the backdrop over 25 m.

### Blender

* Run headless as `blender -b --python script.py -- args`.
* glTF `COLOR_1` imports as `Color.001`. Export FBX with `colors_type="LINEAR"` to keep mask values exact.
* Set `preferences.filepaths.save_version = 0`, or every save leaves a 350 MB `.blend1`.
* The Blender glTF importer builds one object per mesh, with one material slot per primitive, in primitive order.

### Python

* NumPy 2's `np.cross` refuses 2-D vectors: write the 2-D cross product by hand.
* Use the venv's Python everywhere (`.venv/bin/python`).

### glTF

* EXT_mesh_gpu_instancing for trees.
* Two scenes: 0 = course + detailed trees, 1 = light tree LOD.
* Per-256 m-cell LOD switching in the viewer.

## Lessons from Westmount (Ontario open data, leaf-off LiDAR and leaf-off NIR photo)

* **Open data instead of Esri.** Ontario publishes everything needed under the OGL:
  * COPC LiDAR tiles (NRCan);
  * SWOOP 16 cm RGB + NIR imagery (LIO ImageServer `exportImage`, chunks of at most 800 m on the ground or it 504s);
  * the HRDEM 1 m backdrop.

  Overpass was down for hours: `fetch_data.py` falls back to the OSM API `/map` in tiles.
* **NIR changes everything in a leaf-off photo.** NDVI is a band ratio, so it barely moves in shadow:
  * cart paths are NDVI ridges (`trace_paths.py`, Sato filter), where colour rules drowned in leaf litter and trunk
    shadows;
  * sand in branch shadow is NDVI ~0. Accept it only where it connects to sunlit sand (`vectorize.sand_hysteresis`).
    Alone, the shadow rule also took bare soil, shaded roofs and pavement off the course.
* **Leaf-off canopy.** Bare trees hide nothing:
  * keep turf labels under canopy;
  * turn `native` under canopy into wooded rough (leaf litter);
  * close the CHM (grey closing, 1.25 m) before crown segmentation, or one oak becomes five trees;
  * conifers vs bare hardwoods: LiDAR pulse penetration plus crown NDVI.
* **Unmapped bunkers** must be LiDAR hollows *on the course*: garden beds next door are hollows too. They must also
  be 1 m clear of roads and parking and 10 m from buildings (`vectorize.bunker_ok`): a kerbed concrete drive, a
  parking island and a bed by a wall are bright, bare and lower than their surroundings.
* **Off-course paths.** OSM footways along the streets feed the path corridor. Cart path more than 5 m outside
  `leisure=golf_course` is road (`vectorize.off_course_paths`).
* **Tees newer than the LiDAR** (Westmount: holes 5, 8 and 11 rebuilt 2023-25) have no deck in the DEM:
  * `level_tees` fits a plane of at most 1 % at the mean height and feathers it with banks of about 1:3 over the
    ground slope;
  * real decks (plane std < 6 cm, fall <= 3.5 %; drainage falls are 1.5-3 %) are left alone, and so are polygons over
    500 m² (a bad outline would terrace the hillside);
  * list the levelled tees for QA: large fill means the outline runs down a bank.
* **Steep Thompson greens.** Relax the pin slope limit (3 → 5 %) until 12 % of the green is pinnable, or all pins land
  in one spot (`hole_data.pin_candidates`).
* **Structures OSM lacks** go in `features/structures.geojson` (`building`, `height`, `roof:shape=hipped` for a
  synthetic roof when the shelter is newer than the LiDAR). `osm_geoms` reads them as buildings.
* **Spring photo, summer course.** `config.TURF_TINT` grades turf to summer in the glTF only. GSPro uses its own turf
  materials by object name.
* **QA in parallel** writes duplicate cart paths on hole boundaries; two traces 1 m apart union into a 3.5 m path.
  Prompts must tell verifiers to check every override file first. Dedupe before rebuilding.
* **Blender exits 0 on Python errors** unless you pass `--python-exit-code 1`.
* **GreenKeeper distance rule.** Aim points that are not nearer the green than the tee are skipped. Compute yardages
  the same way, or forward tees past a dogleg read long.

## Multi-agent workflows: what worked

* **Research** (scorecard, GSPro practice): 4–6 angles, each a different method (local docs, official docs, forums,
  benchmarks, …). An **adversarial verifier per angle** re-opens sources and tries to refute claims, then one
  synthesiser writes the document. Every research prompt gets the no-browser rule.
* **Per-hole QA**: give agents exact file semantics, image legends, the grid and coordinate conversion, override
  semantics, and "never edit scripts". Inspectors write proposals; verifiers approve or reject them and write the
  override files. Expect ~80 min and 12 agents for 18 holes.
* **Before the workflow edits files**, snapshot `features/overrides/`. Afterwards validate the files: frame is
  `lidar`, the surface is valid, the geometry is valid and non-empty.
* Read a workflow's `journal.jsonl` for progress and results. Large results are easier to read from there than from
  the notification.
