# How GSPro courses are put together (OPCD, 3DG, GreenKeeper) and what our hand-off covers

Compiled 2026-10-11 by a multi-agent research workflow. It covered three angles (the OPCD pipeline, cosmetics, and GreenKeeper), and adversarial verifiers re-fetched or re-read every source. Audience: the course designer who takes `output/gspro/` into Unity, OPCD and GreenKeeper on Windows, and future agents working on this repo. We cannot run Unity, GSPro, GreenKeeper or any Windows tool here, so nothing below has been tested in those tools.

**Tags.** Every statement cites source numbers from section 8 and carries a tag. **V** means verified from the source. **I** means inferred, from our own reasoning or from a pattern in the data. **old** means the source predates 2023 and may be outdated. **low** means a low-trust secondary source. Sources [12] and [14] are AI-agent projects, so their prose is secondary. The artefacts they copied, such as a `ProjectVersion.txt` and the stock add-on, are stronger evidence [12, 14] V.

## 1. Summary

- A GSPro course is a Unity 2018 scene built from the OPCD BaseProject. "GSP > Build Course" turns it into an encrypted `.gspcrse`, and that step needs a Windows-only encryption DLL [11] V. GSPro 2.0.5.0 added "Support for OPCD V4 courses" [20] V.
- Unity version: every OPCD artefact says **2018.2.8f1**, including the BaseProject's `ProjectVersion.txt` [12, 11, 5] V. The V4 guide only says "Unity 2018 Installation" [1] V. The Perfect Lie says 2018.4.36f1 [35] low. Confirm on Windows.
- The current toolset is "OPCD None to Done (V4 Toolset)". You submit the SVG through the web app at app.opcdgolf.com (Discord sign-in) to the "Clender" mesher, which returns `.blend` files [1] V. The 2021 route (GSProSVGConvert.exe, then the Blender add-on's "Convert Mats and Cut") is legacy [3] V old. The V4 guide calls the written documentation "VERY old. Still a valuable resource but NOT a recipe" [1] V.
- Terrain: LiDAR goes through QGIS to a 4097 x 4097 16-bit RAW for a square inner terrain, plus an outer plot about twice its size [4, 5] V.
- Surfaces are SVG shapes filled from a fixed palette. They become meshes whose names carry a surface token. A Unity script then assigns render materials and PhysicMaterials by substring of the GameObject name [3] V old, [10] V.
- 3D grass is the paid Stix Games "DirectX 11 Grass Shader" (3DG), which the designer adds in Unity [1, 32] V.
- OPCD Arborist is "the recommended method for planting all vegetation". Vegetation Studio Pro has not been on sale since March 2023 [1, 34] V.
- Water is a water-base mesh plus a water plane, with realtime reflection probes that refresh on awake [2] V old, [1] V.
- GreenKeeper is a standalone Windows tool. It runs after the course is built and writes `<name>.GKD`, a JSON file holding tees, aim points, pins, hazards, OB and scorecard data [1, 15, 16, 17] V/I. We found no documented import of positions into it [16, 22] I.
- Before beta submission there are GreenKeeper "Pre-Beta Checks" (Collider Inspector, Flyover Benchmark, CPU_GPU Bounding) and the community "OPCD Beta Submission Assistant" [1, 13] V.
- The 2026 GSPro betas add a BIRP/HDRP/URP course engine with "full backward compatibility with existing courses", plus "GSPro Physics 2.0" [20] V. Neither OPCD nor GSPro has published new course-creation instructions for these pipelines [20] I.
- Licence: the OPCD tools are for personal use, and "the only entity licensed for creation, distribution and loading of assets utilizing the OPCD Conversion Tools is GSPro" [3] V old.

## 2. OPCD pipeline and naming

### 2.1 Toolchain versions

| Tool | Evidence | Tag |
|---|---|---|
| Unity | `m_EditorVersion: 2018.2.8f1` in the BaseProject copy at `Unity/Stonehill_Holes_01_02/ProjectSettings/ProjectVersion.txt` [12]; `unityhub://2018.2.8f1/cb6e3408ec90` [11]; "First make sure Unity 2018.2.8f1 is installed" [5]; V4 guide says only "Unity 2018" [1]; "Unity 2018.2.8f1" as of March 2021 [36] old | V |
| Blender | V4 lesson "Installing Blender 4.0.2" [1]. Stock add-on `bl_info`: "OPCD Mesh Editing Tools", version (2, 6), blender (4, 3, 2), internal version "01132026" [10]. Stonehill runs 4.2.2 LTS [12] | V |
| Inkscape | "Inkscape 1.2 works fine" (9/2023) [2]; V4.1 has an "Installing Inkscape(V4.1)" lesson [1]; SVG scale is 1 mm = 1 m [11] | V |
| Mesher | Clender (V4 web app) [1]; osm2svg4opcd v9 targets "the new Clender Beta mesher which does not need clips and cuts of cartpaths" [11] | V |
| Build | "GSP > Build Course ... currently is a Windows only release", output `Unity/GPS/Course_name.gspcrse` [11]; V4 "Building Your Course File (updated 11/2025)" [1] | V |

### 2.2 Object-name tokens, render materials and physics (2021 `SetMeshMaterial.cs`)

The menu is `GSP/SetMeshMaterials` and the button is "Replace Materials". The script loops over `FindObjectsOfType<GameObject>()` where `activeInHierarchy` is true, and matches with case-sensitive `name.Contains` [3] V old. `Custom1` and `Custom2` are two independent `if`s. After them comes an if/else-if chain in the order below, where the first match wins, so a Custom object also runs through the chain [3] V old. The PhysicMaterial names are verified. Mappings marked * are inferred from the material's name [3] V/I.

| # | Token | PhysicMaterial | Our objects (`course_meshes.fbx`, 121 objects [38]) |
|---|---|---|---|
| – | `Custom1`, `Custom2` | roughPhMat | none in the FBX. The SVG uses them for courts and buildings [43] |
| 1 | `_Tee` | teePhMat* | `Hole##_Tee` |
| 2 | `_Fairway` | fairwayPhMat* | `Hole##_Fairway`, `Hole99_Fairway` |
| 3 | `_GreenFringe` | greenPhMat | `Hole##_GreenFringe`, `Hole99_GreenFringe` |
| 4 | `_Green` | greenPhMat* | `Hole##_Green`, `Hole99_Green`. The branch checks `teeMat != null` before assigning `greenMat` [3] |
| 5-7 | `_SemiRough`, `_Rough`, `_DeepRough` | semiroughPhMat*, roughPhMat*, deeproughPhMat* | `Hole99_SemiRough`, `Hole99_Rough`, `Hole99_DeepRough` (all rough is in Hole99) |
| 8 | `_Concrete` | concretePhMat* | `Hole98_Concrete`, `Hole99_Concrete` (material leaked as `Concrete.001`) |
| 9 | `_Bunker_Lip` | roughPhMat | `Hole##_Bunker_Lip` |
| 10, 11 | `_Pot_Wall`, `_Pot` | roughPhMat, sandPhMat* | – |
| 12 | `_WaterPlane` | waterPhMat (the only waterPhMat) | `Hole99_WaterPlane`, `_2`, `_3`, `_4` |
| 13 | `_Bulkhead_Base` | roughPhMat; writes `sharedMaterials[1]` | – |
| 14 | `_Curb` | concretePhMat | – |
| 15 | `_Pinestraw` | pinestrawPhMat* | `Hole99_Pinestraw` |
| 16 | `_Bunker` | sandPhMat* | `Hole##_Bunker`, `Hole99_Bunker` |
| 17 | `_Water_Base` | roughPhMat; slot 1 gets `Materials/Dual Tex - BulkHead_Edge` | `Hole99_Water_Base` with slots [Water_Base, Water_Edge] |
| 18, 19 | `Stone_Wall`, `Wood_Wall` | concretePhMat, timberPhMat | – |
| – | no token | nothing assigned | `Hole99_Road` ("Road"), `Hole99_Court` ("Court"), `Building_<id>` in `structures.fbx` (873 objects, Roof / Wall_Stucco), `Backdrop_Terrain` |

- Each PhysicMaterial is created as `new PhysicMaterial("concretePhMat")` and so on: 11 names, no friction or bounce values, and nothing saved as an asset [3] V old. That GSPro reads the lie from the PhysicMaterial name is I and unconfirmed.
- Preconditions: the PhysicMaterial is set only if `GetComponent<Collider>() != null`, and the render material is replaced only if the MeshRenderer already has a non-null `sharedMaterial` [3] V old. Colliders come first: the Outline PDF has "Add colliders" as step 17 and materials as step 19 (the written doc numbers them 18 and 20) [3, 2] V old.
- Crash modes that abort the whole loop [3] V old:
  - (a) `_Water_Base` and `_Bulkhead_Base` write `sharedMaterials[1]`, which throws on a mesh with one material slot.
  - (b) A matching GameObject with no MeshRenderer throws a NullReferenceException. Our FBX root `course_meshes` carries no token [38], so it is safe.
- Use exactly one surface token per name. A name holding both `Custom1` and `_Rough` gets both assignments, and the later one wins [3] I.
- The V4 "Set Mesh Material Tool (Themes)" code is not public; only lesson titles are known [1] V. It may not recognise `_Bunker_Lip`, `_GreenFringe` or plain `_Water_Base` (see 2.3) [10] I.

### 2.3 V4 Blender naming (why `course.blend` is not an OPCD V4 .blend)

- V4 surface meshes end in `_-_Mesh` and their transition meshes in `_-_Blend`. They are paired through `obj['opcd_parent_id']`, `obj['opcd_kind']` and `obj['opcd_shape_id']` [10] V.
- 39 operator selectors require `'Spline' in o.name`, so names like `Hole01_Bunker` are invisible to the V4 Blender tools [10] V. A name like `Spline_Hole01_Fairway_-_Mesh` would satisfy V4 and still contain `_Fairway`; this is untested [I].
- `intMaterialTypes` holds Tee, Fairway, Semi, Green, Rough, Deep, Pinestraw, Bunker, Concrete, Water_Base_Lake, Water_Base_Creek and Custom1-4, with Hole99 commented out. "GreenFringe", "Fringe" and "Water_Edge" never appear [10] V.
- Bunkers: V4 has no separate lip object. "Adjust Bunker" digs the lip into the bunker mesh (`bunker_lip_depth` 0.05, inner 0.04, concave) [10] V. In 2021 the lip was a separate `<name> Bunker_Lip` object about 0.035 m deep [3] V old. Our separate `Hole##_Bunker_Lip` objects follow the 2021 convention [38].
- `BatchExporter` exports every visible object as `<folder>/<clean_name>.fbx` with `bake_space_transform=True` [10] V. Unity then names a one-object FBX's GameObject after the file, while children of our multi-object FBX keep their object names [I].
- Vertex colour: V4 expects a `Col` attribute in the CORNER domain and paints red, green, blue, black and white with it. The water style is labelled "Hazard Line 3DG" [10] V. Unity has one vertex-colour stream per mesh (`Mesh.colors`) [24] V, and Stix "Vertex density" reads it [32] V. So our `Col` 3DG masks and OPCD vertex-paint (MAHS) blends cannot coexist on one mesh. Renaming the layer does not help [I].

### 2.4 SVG layers and palette

The exact 2021 palette from `OPCD Palette.gpl` [3] V old. The 2021 add-on names any other fill colour `ColorError`.

| Surface | Hex | Surface | Hex | Surface | Hex |
|---|---|---|---|---|---|
| Tee | `#A0E5B8` | Green | `#BCE5A4` | Concrete | `#BEBEBB` |
| Deep Rough | `#164B20` | Green Fringe | `#A4C88F` | Water | `#0000C0` |
| Rough | `#278438` | Bunker | `#E5E5AA` | Bulkhead Water | `#9534EB` |
| Semi Rough | `#36B74D` | Pot Bunker | `#E5BC97` | Custom1 | `#FCA328` |
| Fairway | `#43E561` | Pinestraw | `#BE751D` | Custom2 | `#FC28EB` |

- Layers (2021-23 docs): "you will want your layers to follow the HoleXX format". Hole99 is the outer mesh that "will get cut by every object on every hole", and Hole98 holds cart paths that "cut through the other objects". Use "move to layer", not copy and paste, and save a "no sat" copy [2] V old.
- The 06092021 add-on never implemented this. Its cut loop is `range(99)` (Hole00..Hole98) and cuts only within one hole [3] V old.
- In V4, osm2svg4opcd v9 fills the core 2021 colours and names its layers like `highway.residential-123456789-0`, and its output still meshes [11] V. Its README says converting `<polyline>` to `<path>` fixes Clender "Color Errors" [11] V. So the Clender appears to classify by fill colour and not by Hole layer [I]. The V4 hex codes for Custom3/4 and Lake vs Creek are not public [11, 12] I.
- Our `course_opcd.svg` [43]: a 2048 x 2048 mm document with layers Hole01..Hole18, Hole98, Hole99 and an `image` (satellite) layer. It has 1,809 `<path>` elements, no `<polyline>` and no strokes. Every fill comes from the 2021 palette, with Custom1 for courts and Custom2 for buildings (`scripts/export_gspro.py`). **It has not been tested against the Clender.** Before submitting, delete the `image` layer ("no sat" copy) [2] I.

### 2.5 Terrain import

Heightmaps come from OPCD's `.bat` files [4] V old:

```bat
gdal_translate.exe -of ENVI -ot UInt16 -scale MIN MAX 0 65535 -outsize 4097 4097 -r bilinear ...
rem then rename to .raw and: del *.hdr *.xml
```

| Setting | OPCD value | Ours [39, 40] |
|---|---|---|
| Import Raw: Depth, Width x Height | Bit 16, 4097 x 4097 [5] V | 16-bit unsigned, 4097 x 4097 |
| Byte Order / Flip Vertically | Windows / ticked [5] V | little-endian; first row = north, so tick Flip Vertically |
| Terrain Size | from MinMax.xlsx (example 1650 / 91.04 / 1650) [5] V | inner 2048 x 47 x 2048 (heights 327-374 m); outer 4096 x 74 x 4096 at (-1024, -11, -1024) |
| Inner / outer | inner "Needs to be a SQUARE plot"; outer about 2x [5] V | 2048 m / 4096 m |
| Heightmap / Detail Resolution | 4097 / 2048, Detail Resolution Per Patch 8 [5] V | 4097 set by the helper; detail not set (todo) |
| Control / Base Texture Resolution | 2048 / 2048 [5] V | not set by the helper (todo) |
| Overlay | 8192 JPEG, quality 95 [4]; Max Size 8192 [5]; compress before building, or "it will make your course filesize massive" [1] V | `overlay_8192.jpg`, `outer_overlay_8192.jpg` |

- Process [5] V (early 2023): create a project from the latest GSPBaseProject. Open the "ImportTerrain" scene and save it as `(Project_Name)_Lidar_Scene`. Create "Terrain (Inner)" and "Plot (Outer)". Lower the outer plot's Y until `lightblue.png` no longer shows through.
- Exporting the terrain to Blender (`Terrain/Export To Obj...`, at Half or Quarter resolution) is still a required V4 lesson [3] V old, [1] V. Our meshes already sit on our heightmap, and the terrain is sunk 0.05 m below them [39]. V4 also has a "Fixing Z-Fighting" lesson [1] V.
- Mesh size: Unity 2018.2's Index Format defaults to Auto, which uses 32-bit indices when needed. 16-bit "supports up to 65535 vertices" [25] V. A Clender-made V4 mesh has 97,133 vertices [14] V low. So do not force "16 bit". Our `Hole99_Rough` has 904,548 vertices [38], which is a performance and MeshCollider cost, not a hard limit [I].

## 3. Grass, trees and vegetation

### 3.1 Stix 3DG

- The V4 guide lists "3D Grass (optional paid asset but highly recommended)" with videos for Introduction, Installation, "Enabling 3DG on Your Meshes", "Experimenting with 3DG Settings (safely)" and "Removing 3DG with Vertex Painting Theory" [1, 8] V. The video contents are unread, because YouTube requires sign-in.
- Setup: "Add Component: Stix Games > General > Nature Mesh Filter", then "Stix Games > General > Grass Renderer", and select the grass material in the Grass Renderer's Material field [32] V. The shaders are `Stix Games / Grass` and `Stix Games / Grass Forward Only` (`Stix Games / Grass URP` for URP) [32] V.
- The old OPCD steps end with "Change the layer to 600m cull". OPCD's own Stix mods are "already included in base project we update it automatically" [2] V old. That GSPro culls this layer at 600 m (`Camera.layerCullDistances`, where 0 means the far plane [27] V) is I.
- Which surfaces: "if the lawn mower goes there, its usually better to use 3dg, if not, VSPro grasses are better" [2] V old (2022-06). This chooses between 3DG and planted grass; it is not a rule about fairways. We put 3DG only on `Hole99_SemiRough`, `Hole99_Rough` and `Hole99_DeepRough` [40, 42]. Keeping it off greens, fringes and tees is our choice [I]. The Perfect Lie's "start with greens" has no primary support [35] low.
- Density modes: "Texture density" needs UVs, and "Vertex density" will "Use the vertex color to set grass densities". In "1 - 4 textures" mode "each channel controls one grass type" [32] V.
- A designer's 2023 test [6] V: red, green and blue grew types 1-3 and black grew nothing. In 4-texture mode "Black ... actually goes everywhere". Painted colours applied only after baking to the mesh. Their advice: "three texture. Black is nothing." The tester was unsure of their setup.
- Our `grass_3dg.json` [42]: Vertex density; "2 textures" (R = green blades, G = dry blades, B = 0); layer `600m cull`; Density Falloff Start 12; Grass Fade End 90; Lighting Mode Default PBR. **Never use 4 textures.** Every non-grass vertex on our meshes is black, so a 4th type would grow there [6] I.
- Target Density: use "the highest value where the material still looks good". `_GlobalTargetDensityMultiplier` is inverse ("for historical reasons"). Never lower a whole material's density through the density mode: it "cost[s] performance, without any benefit" [32] V. Our `relative_density` values are hints for each material's Target Density [42] I.
- Floor colour: automatic floor colour "requires a unique material per mesh, or the different mesh filters will interfere" [32] V. The helper shares one material per surface [40]. Either duplicate the material per mesh or leave automatic floor colour off [I].
- Floor mesh: "an irregular mesh ... can cause artifacts in the grass density". Use regular polygons or "enable mesh normalization", and Target Density is capped by mesh density [32] V. Stix 2.9.0 skips a mesh only when it lies entirely beyond Grass Fade End, and splits terrains, not meshes [33] V. So a course-wide `Hole99_Rough` is never skipped; tile it [I].
- Version risk: AssetBundles hold serialized data, not code, which compiles into the project assemblies [30] V. GSPro ships its own grass-script changes ("New 3D grass script performance enhancements", 2.5.3.38) [20] V. So the runtime classes are GSPro's own copy [I]. Install 3DG only through the OPCD base project and the V4 video. Do not upgrade to Stix 2.12.0 (2026-07-30), which brings "minor breaking changes" (Random Seed, new random numbers) [33] V.
- The helper sets the first Material-typed serialized property on GrassRenderer, an undocumented field [40]. Confirm the material slot by eye, and note that Stix 2.5.4 added a material index option [33] V.
- Lighting settings are "not available in deferred rendering", and "4 shadow cascades quadruple the performance cost" [32] V. In game, "press Z to remove the 3D texture" [22] V.

### 3.2 Trees and vegetation

- Arborist: "the newly released OPCD Tool, available for free in the OPCD Downloads folder and is the recommended method for planting all vegetation". It "will vastly outperform Native Unity Planting", and assets not in Arborist can still be planted in Unity [1] V. GSPro 3.1.1 "Added support for OPCD Arborist" [20] V (2.9.11 beta notes: "Support for upcoming OPCD Arborist/v5 courses" [19] V). The Arborist written guide returns HTTP 401 [1] V.
- How Arborist works [7] V (2025-10-13): it loads the built course file and needs the satellite image and the terrain size from Unity. You draw biome masks ("MFM" follows an existing spline such as DeepRough) and fill them from its library. Spacing per item can go as low as 0.4. "Quick plant" places single trees. Plant forests only as far back as you can see them from a tee or green, and use more aggressive LODs for forest trees.
- KAustin Designs' 18-part "Field to Forest" series includes "Arborist Helper: Arborist to Unity" and "Importing VSPro and Game Object Trees" [9] V. What that import covers is unknown.
- Our trees: `trees.csv` has 10,746 LiDAR trees (archetype, prefab, Unity xyz, yaw, scale, height, crown) and `tree_prefabs.fbx` holds `Tree_<arch>_v<k>` objects with `_LOD0/1/2` children [44]. `Westmount/Place Trees` places them natively [40]. With Arborist, use `trees.csv` as a reference map for quick-plant and biome masks [I].
- LODs: meshes named `_LOD0`, `_LOD1` ... get a LOD group "automatically on import" [26] V. Whether this works for children nested in one multi-object FBX needs testing; the helper's `AddLodGroup` fallback covers it [40] I. V4 Appendix C has "Tree Optimization - LOD Level Removal and Adjustment" [1, 8] V.
- Batching: "Unity prioritizes Static batching over instancing" and turns instancing off on statically batched objects [29] V. The helper sets BatchingStatic | OccluderStatic | OccludeeStatic on every tree [40]. Prefer GPU instancing on tree materials and drop BatchingStatic. Occlusion culling "works best" where areas are separated by solid objects, which suits an open course poorly [29] V/I.
- Colliders: the in-game BLI shows "where the colliders are located" around trees, and "Carry (raw)" "ignores any obstruction like trees" [23] V old. GSPro 3.1.6.13 "Updated collider related scripts" [20] V. Old VSPro advice: spawn colliders "at least 300 meters", and give every LOD a mesh collider if colliders are LOD-based [2] V old. No public source specifies GSPro's tree collider shape, layer or PhysicMaterial [2, 20, 23] I.
- Our trunk CapsuleCollider (radius `trunk_radius_m`, height `crown_base_m`) sits on the already-scaled instance root [40]. The note in `tree_prefabs.json` saying to multiply by scale would double-scale it [44] I. The Beta Submission Assistant flags "Enabled collider has no assigned PhysicMaterial" [13] V. Our tree capsules have none [40], and whether that rule covers trees is I.

## 4. Water, lighting, performance

| | 2021 add-on [3] V old | V4 add-on [10] V | Ours [38, 40] |
|---|---|---|---|
| Water base | inset 0.15 m; outer ring `_Edge` joined into `_Base`, slots [Water_Base, Water_Edge] | `Water_Base_Lake` / `Water_Base_Creek`; lip 0.05, inner depth 2; no `Water_Edge` material | `Hole99_Water_Base`, slots [Water_Base, Water_Edge] |
| Water plane | duplicate, z scaled to 0, outset 2.0 m, remeshed at 3 m, `<name> WaterPlane` | lakes only: lowest boundary z minus 0.05, outset 2.0, `Spline <name> WaterPlane`, no remesh | 4 objects matching `_WaterPlane` |

- After SetMeshMaterials, slot 1 of `_Water_Base` holds `Dual Tex - BulkHead_Edge`, so drag the water-edge material in by hand [3] V old. Keep at least 2 slots on every `_Water_Base` (crash mode (a)) [3] V old. V4 lists "Adjusting Water Plane (required)" and "Reflection Probe Adjustments (optional)" [1] V.
- Probes (update of 2/24/2022): use "real-time" probes on "awake". GSPro refreshes them on time-of-day and weather changes, and baked probes add to bundle size [2] V old. Unity: "On Awake ... renders the probe only once when it first becomes active" [28] V. `Westmount/Water Reflection Probes` adds one realtime, OnAwake probe per `*_WaterPlane`, in an easily deleted group [40].
- Cameras and lighting: "GSPro will delete your camera on load" [2] V old. V4 post-processing ("Post Processing Selector Tool and Skybox Setting", 11/2025) is done in the base project [1, 8] V. Ship no cameras, lights or skybox [I]. Players get L (lighting settings), < / > (shadow quality), a Draw Distance slider and "Disable Gradient Fog" [22, 20] V.
- Performance: "The LOWEST FPS area on your course is all that matters". Fixes include more aggressive LODs, or a duplicated, less dense 3DG material for that hole [2] V old.
- For a large Hole99 outer mesh, "lower the resolution of the mesh or your course will have FPS issues" ("Change the Retopo to 4 from 0.90", unit unstated) [2] V old.
- No primary source gives triangle or FPS budgets. The Perfect Lie's figures (such as "<5 million triangles") are unverified [35] low. Measure with GreenKeeper's Flyover Benchmark and CPU_GPU Bounding checks instead [1, 8] V.
- Before building: compress the 8k overlays and "Unload/Purge Auto Fence Builder (if installed)" [1] V.

## 5. GreenKeeper metadata and our `greenkeeper.json`

**Workflow.** GSPro's third-party page lists "Golf courses created for GSPro using OPCD tools, GSPro 'GreenKeeper' tool" [21] V. V4 section 8 runs in this order [1] V: Installation (the "GreenKeeper V4 Launcher AutoUpdater"), Loading Up Your Course, Base Course Info, OOB, Hazards, Tees and Aim Points, Pin Placement and Conditions, Scorecards and Ratings/Slopes, and Finishing Up (Benchmark and Save). Pre-Beta Checks follow, with videos dated 2023-12-16, which may lag GreenKeeper 4.1 [8] V. GreenKeeper comes after "Building Your Course File" and after Arborist [1] V. One 2026 source names GreenKeeper 4.1.0 [12] low.

**Files.** The GKD is plain UTF-8 JSON, `<CourseFolder>.gkd`, read case-insensitively. A folder holding a `.gspcrse` is an OPCD v4 course [16] V. A course folder also holds `*.gspcrse.csv`, `*_benchmark.jpg`, `*_scorecard_imperial.jpg`, `*_scorecard_metric.jpg`, `arboristdata.dat`, `arboristspawnpositions.json`, `arboristversion.dat`, `arborist_postprocess.dat`, `coursedetails.txt` and optional `.GKD_BAK` / `.GKDalt` files [15] V. A 2026 GKD has `gkversion` 4.1 and new keys `SceneFolderName`, `IsArborist`, `HasAlternateLayouts`, `CameraDistance`, `AllowNonZeroTeeBoxes` and `CoursePar` [12] V low, [15] V (SceneFolderName). GKD data is versioned and shipped apart from the course build: the SGT manifest carries `GKDVersion` and `GKDDownloadURL` per course [18] V. The schema below comes from a snapshot of 1,119 real GKDs (2024-10-27) [16] V.

| GKD field [16] V | Rules seen in real files | Our `greenkeeper.json` [41] | Action |
|---|---|---|---|
| `Holes[].Par`, `Holes[].Index` | per hole; Index is a 1..N permutation in 1,086 of 1,119 courses | `par`, `handicap` | direct |
| `Holes[].Tees[]` `{TeeType, Enabled, Distance, Position}` | always 11 entries: Black, White, Green, Blue, Yellow, Red, Junior, Par3, AimPoint1, AimPoint2, GreenCenterPoint. All tee slots are `Enabled=true`, even unused ones, which have `Position` null and `Distance` 0 | `tees[]` Blue, White, Red, Gold | Blue, White and Red map directly; Gold goes to Yellow (or Green) [I]. Never use Junior or Par3: Par3 is a roughly 130 yd tee on every hole, and both slots are measured straight to the green |
| `AimPoint1`, `AimPoint2` (pseudo-tees) | at most 2 per hole; positioned on 74% / 20% of holes | `aim_points[]` (1 on 14 holes, 0 on 4) | order from the tee toward the green |
| `GreenCenterPoint` | always positioned, `Enabled=false`; median 2.4 m from the pin centroid, so it is a separate point | `green_center` | direct |
| `Pins[]` `{Day, Position}` | 4 per hole, Thursday to Sunday ("You can alternate the pin from Thursday, Friday, Saturday, or Sunday" [22] V) | 5 named pins | suggest Thu = middle, Fri = front, Sat = back, Sun = the harder of left/right, keeping the 5th as an alternate [I] |
| `Hazards[]` `{pointCount, coords:[{x,y,z}], DZpos, freeDrop, innerOOB, noAIL, hasDZ, islandGreen}` | course level; open rings; median 37 points about 5.9 m apart; y on the ground; median 7 per course; no stake colour, no link to a hole | per-hole `hazards[]` with `polygon` [[x, z]]: 3 water, 40 native_area, 49 bunker | give GreenKeeper the water (and native areas, if they should be penalised) with y sampled from the heightmap. Bunkers are probably not GK hazards [I]. Suggest drop zones (`DZpos`) for water near greens |
| `pOOB` `{pointCount, coords}` | one per course, an open ring (median 85 points) on the ground; internal OB is a hazard with `innerOOB=true` | not provided | trace the OSM property line, which is our OB line [45] |
| `BlackSR` ... `RedSR`, `JuniorSR`, `PAR3SR` | one free-text `rating/slope` string per slot. Typos such as `75,6/141` exist, and GSPro 3.1.1 "Fixed application error with malformed course GKD slope and rating" [20] V | `ratings` men / women | `BlueSR` `73.0/132`; `WhiteSR` `71.1/129` (women 76.9/135); `RedSR` `69.3/121` (women 75.1/130); `YellowSR` `66.3/113` (women 71.3/121). One value per slot, so the designer picks men's or women's |
| `TeeTypeTotalDistance[]` | sum over holes (matches in 8,949 of 8,952 tee types) | `total_yards` | computed by GreenKeeper |
| (no heading field) | in neither the 2024 nor the 4.1 files; the game derives aim ("A: Reset Aim" [22] V) | `heading_deg_from_north` | visual cross-check only |

**Yardage is computed, not typed.** The rule fitted to the community data [16] I matches 84,981 of 85,070 colour-slot tees within 0.5 m. Distance is in metres for both `unitOfMeasure` values:

```python
import math

def gk_distance_m(tee, aim_points, green_center):
    """Colour slots: horizontal path tee -> aim points nearer the green than the tee -> GreenCenterPoint."""
    d = lambda a, b: math.hypot(a[0] - b[0], a[2] - b[2])   # positions are (x, y, z); y is ignored
    path, cur = 0.0, tee
    for ap in aim_points:                                    # AimPoint1, then AimPoint2
        if d(ap, green_center) < d(tee, green_center):       # aim points behind the tee are skipped
            path, cur = path + d(cur, ap), ap
    return path + d(cur, green_center)                       # Par3 (and most Junior) tees: straight to the green
```

Applied to our file (re-run 2026-10-11) [41], every tee is within about 5.5 yd of the scorecard except three: **H5 Blue 566.6 vs 605 yd** (Blue and White share one position), **H8 Blue 286.5 vs 305** and **H2 Blue 365.2 vs 373**. Fix or flag those tees before entry. Do not copy the Stonehill approach of writing scorecard yards × 0.9144 into `Distance`; real GKDs compute it from geometry [12, 16] I.

**Coordinate frame.** GKD positions look like Unity world metres, with y measured from the terrain base: across 158,098 tees, z is never negative and y stays small whatever the course altitude [16] I. Our frame is x = E - 536504, z = N - 4809836, y = h - 327 [39]. It holds only if the inner terrain sits at world (0, 0, 0) with RAW zero = 327 m, which is what `Westmount/Build Terrains` does [40]. Do not apply the deprecated "Lowering Your Main Terrain" step [1] I.

**Base course info (all suggestions, confirm in GreenKeeper's dialogs)** [16, 45] I:

- `CourseName` "Westmount Golf & Country Club"; Location "Kitchener, Ontario, Canada".
- Designer: Stanley Thompson (1931).
- `unitOfMeasure` 2 (98 of 100 Canadian courses use it).
- Region 5 (mostly Canadian, though region 3 also holds Canadian courses).
- `altitudeV2` about 1,075-1,225 (it looks like feet; our heights are 327-374 m [39]).
- `HasRange` / `RangeTee` / `RangeAim` for the east-lobe driving range. Range support is changing in the 3.2.x betas [20] V.

Alternate layouts use `.GKDalt` (GSPro 3.1.1 "multiple GKD per course support") [20, 15] V.

## 6. What our package provides vs what the designer still does

Already in `output/gspro/`:

- [x] Inner and outer 16-bit RAW heightmaps, 8k overlays, and `terrain.json` with import settings and the frame [39].
- [x] `course_meshes.fbx` with `Hole##_<Surface>` names, Water_Base with 2 slots, 4 WaterPlanes, and `Col` 3DG masks [38].
- [x] `structures.fbx` (873 buildings), `backdrop.fbx`, `tree_prefabs.fbx` with LODs, and `trees.csv` [38, 44].
- [x] `course_opcd.svg` with the OPCD palette and layers, all paths, untested against the Clender [43].
- [x] `greenkeeper.json` (reference values to type into GreenKeeper, not an importable GKD) and `grass_3dg.json` [41, 42].
- [x] `WestmountSetup.cs` menus: Build Terrains, Place Trees, Water Reflection Probes, Add 3D Grass. It is Editor-only, so it ships no runtime code [40, 30].

Designer, on Windows:

- [ ] Install Unity 2018, confirming the patch (2018.2.8f1 expected), and create the project from the latest GSPBaseProject [1, 5, 12].
- [ ] Run Build Terrains, then set Detail 2048 / 8, Control 2048 and Base 2048 [5].
- [ ] Import `course_meshes.fbx` with Index Format Auto and Generate Colliders on, or add MeshColliders [25, 3].
- [ ] Run `GSP/SetMeshMaterials` or the V4 tool. Then fix Water_Base slot 1 by hand, and assign materials and PhysicMaterials to `Hole99_Road`, `Hole99_Court`, `Building_*` and `Backdrop_Terrain` [3, 13, 38].
- [ ] Adjust the water planes (required in V4), and run or keep the reflection probes [1, 40].
- [ ] Install 3DG through the base project, run Add 3D Grass, and check the material slot, the layer and the 2-texture mode [1, 32, 40].
- [ ] Plant trees with Arborist using `trees.csv` as a map, or keep Place Trees and switch to GPU instancing [1, 29, 40].
- [ ] Set post-processing and the skybox, and delete scene cameras [1, 2].
- [ ] Compress the overlays, purge Auto Fence Builder, and build the `.gspcrse` [1, 11].
- [ ] Work through the GreenKeeper steps in order using `greenkeeper.json`. Then run the Pre-Beta Checks and the Beta Submission Assistant [1, 13].

Gaps in our package (for future agents):

- [ ] `greenkeeper.json`:
  - use GKD vocabulary (Gold -> Yellow, 4 day pins, `rating/slope` strings);
  - add a `pOOB` ring and 3D hazard coordinates, and move bunkers into a separate list;
  - fix H2, H5 and H8 Blue [41].
- [ ] Rename `Hole99_Road` and `Hole99_Court` to one-token names (for example `Hole99_Concrete_Road` and `Hole99_Custom1_Court`), and rename the `Concrete.001` material to `Concrete` [38, 3] I.
- [ ] Tile or coarsen `Hole99_Rough` (904,548 vertices) into pieces a few hundred metres across [38, 32, 2] I.
- [ ] `WestmountSetup.cs`:
  - set the Terrain Settings above;
  - guard `SplatPrototype` (Obsolete in 2018.4 [31]) with `#if UNITY_2018_3_OR_NEWER` and use the TerrainLayer path;
  - drop BatchingStatic on trees;
  - decide on PhysicMaterials for tree colliders;
  - log which GrassRenderer property it set;
  - soften the header's "2018.2.8f1" claim [40].
- [ ] Fix the capsule-scaling note in `tree_prefabs.json` [44].
- [ ] Add a test that every `*_Water_Base` keeps 2 or more slots and that no renderer-less object carries a token [3].

## 7. Open questions to verify on the Windows side

1. Which Unity 2018 patch does the V4 BaseProject need? Check the "Unity Installation (required)" video or the OPCD Discord [1, 8, 35].
2. What does the V4 Set Mesh Material Tool (Themes) match? Which PhysicMaterial names does it use, does it need `Spline` or `_-_Mesh`, and does it know `_Bunker_Lip`, `_GreenFringe` and `_Water_Base`? [1, 10]
3. Does GSPro take the lie from the PhysicMaterial name, the GameObject name or the render material? Did Physics 2.0 and "Fixed incorrect surface being reported" (3.49.11.13 beta) change this? [20]
4. Which vertex-colour channels does the OPCD MAHS shader read? Can our R/G 3DG masks survive OPCD's vertex-paint tools? [1, 10]
5. In Stix 4-texture mode, is the 4th type alpha or the remainder? Do R and G densities add? [6, 32]
6. Which Stix version does GSPro's runtime embed, and does the OPCD base project's copy have Vertex density and the 2.5.4 material index? [20, 33]
7. Is `600m cull` applied by GSPro's camera, and are there other cull layers? [2, 27]
8. What tree collider setup does GSPro expect (shape, layer, PhysicMaterial)? Does the beta audit's PhysicMaterial rule cover tree capsules and buildings? [13, 23]
9. Can Arborist import GameObject tree positions or our `Tree_<arch>_v<k>` prefabs? [9]
10. Does the Clender use Hole## / 98 / 99 layers at all, and what are the V4 hex codes for Custom3/4 and Lake vs Creek? [11]
11. Does GreenKeeper 4.1 offer numeric entry, file import or snap-to-mesh for tees, pins and hazards? [1, 16]
12. Does GSPro display the GKD `Distance` or recompute it? Is `GreenCenterPoint` placed by hand or computed? [16]
13. What exactly do `noAIL`, `freeDrop`, `hasDZ`, `islandGreen` and `innerOOB` do? What labels does the region dropdown show? [16]
14. Will the BIRP/URP/HDRP engine (GSPro 3.5) need a new BaseProject or Unity version, and will 3DG and Arborist carry over? [20, 37 low]

## 8. Sources

OPCD primary (read or re-fetched 2026-10-11 unless noted):

1. OPCD "None to Done (V4 Toolset)", Google Doc. https://docs.google.com/document/d/1l8PRCyN-gvcBsufd3u_P1K_3y7y-pxMMrOn2XWEgU7w (live; entries "updated 11/2025").
2. OPCD Written Documentation. https://docs.google.com/document/d/1wUIrlnhrZ3b8nmOOkVFXuRQI0K5eaZuTEXmJtOUKonw (dated notes 10/5/2021 to 9/12/2023; **old**).
3. OPCD Conversion Tools zip: `OPCD Palette.gpl`, `OPCD_Conversion_Tool_06092021_1.py`, `Unity files/SetMeshMaterial.cs`, `ExportTerrain.cs`, "Outline of the OPCD Process for GSPro.pdf", `OPCD User Agreement.txt` (2021-05-14). https://drive.google.com/file/d/18GGBnKetnpP4RhaIZij3tYogQGK3Y6FE (2021; **old**).
4. QGIS_Support_Files.zip: INNER/OUTER `.bat`, `TIFtoJPG.bat`, `Lidar Classification.txt`. https://drive.google.com/file/d/1bU8j1SUKjcxVxCzw_ODe-tSyDAlIJJs5 (2022-12; **old**).
5. "Lidar to Terrain Free Process" PDF, pp. 21-22. https://drive.google.com/file/d/1HSzKdkHLQETDL7FKDgswsL1aaOpwuNdN (created 2023-01-11).
6. Loom "3DG and Vertex Painting" (linked from [1] as "Removing 3DG with Vertex Painting Theory"), captions. https://www.loom.com/share/2dbe389e8d734622af0bd701c7d3bd83 (2023-03-23).
7. Loom "Getting Started with Arborist: A Quick Guide", captions. https://www.loom.com/share/f93b8d20cfac401ca6a30abe76e7766b (2025-10-13).
8. Videos linked from [1]; titles via YouTube oEmbed, contents unread (sign-in required): https://youtu.be/O-8oT-Ma9KI (Stix 3DG Enabling), https://youtu.be/pafeRuFn8DY (Unity Installation), https://www.youtube.com/watch?v=TycrhDLZV6g (Collider Inspector), https://youtu.be/tVyKuXYR0Hc (Flyover Benchmark), https://youtu.be/tE-KZRA5Ock (CPU_GPU Bounding), https://youtu.be/RR_xZJUnQ_k (Reflection Probes), https://youtu.be/dlT4BsTV7CE (Post Processing), https://youtu.be/D57NF4_ZceQ (Tree LOD), Pre-Beta playlist https://www.youtube.com/feeds/videos.xml?playlist_id=PLOHx7fwaLyc-1LFaPjoznYr-eW_vw-c3X (2023-12-16).
9. KAustin Designs "Field to Forest" Arborist playlist. https://www.youtube.com/playlist?list=PLSVaNhf_G64UbnnnX3C2es9leVJve6RvD and https://www.youtube.com/watch?v=lK1VRFCnxYo (2025-2026; titles only).

Community repositories and data:

10. opcd-erosion-recipes, including the stock V4 add-on `patches/afrod_operators.stock.py`. https://github.com/Parfect66/opcd-erosion-recipes (add-on 2026-01-13).
11. osm2svg4opcd (README, `styles.json`, `Linux4OPCD.txt`). https://github.com/csites/osm2svg4opcd (2025-2026; Linux4OPCD undated).
12. GSPro-Stonehill (ProjectVersion.txt, `Scripts/build-front-nine-metadata.ps1`, `GSPro/Stonehill_9H/`). https://github.com/flashdancee/GSPro-Stonehill (2026-09; AI-agent project, **low** for prose).
13. opcd-beta-submission-check. https://github.com/Parfect66/opcd-beta-submission-check (2026).
14. OPCD_Recipes (`references/courses.md`, skills). https://github.com/Parfect66/OPCD_Recipes (2026; AI-assisted, **low**).
15. course-renamer. https://github.com/Parfect66/course-renamer (2026-08-26).
16. sig-gsp (`coursedir-script/collect-data.js`, `src/course-data-types.ts`, `src/teebox-data.ts`, `frontend/src/types.ts`, `data/gspro.db.old` with 1,119 GKDs). https://github.com/marcusta/sig-gsp (data 2024-10-27; scripts 2024-11 to 2026-06).
17. Ubuntu_OPCD_Tools ("GreenKeeper (Runs under Wine64)"). https://github.com/csites/Ubuntu_OPCD_Tools (2024-12-23).
18. SGT course manifest. https://simulatorgolftour.com/course_manifest.json (fetched 2026-10-11).
19. Golf Simulator Forum thread quoting the GSPro 2.9.11 beta notes. https://golfsimulatorforum.com/forum/skytrak/408170-gspro (2024-09-20).

GSPro official:

20. GSPro change log. https://gsprogolf.com/change-log.html (fetched 2026-10-11; latest 3.49.11.13 public beta, 2026-10-01).
21. GSPro third-party page. https://gsprogolf.com/3rdparty.html (read 2026-10-11).
22. GSPro Knowledge Base: https://gspro.gitbook.io/gspro-knowledge-base/in-game-information/keyboard-shortcuts, https://gspro.gitbook.io/gspro-knowledge-base/settings-main-menu/visual-settings-settings, https://gspro.gitbook.io/gspro-knowledge-base/local-match-main-menu/local-match-setup, https://gspro.gitbook.io/gspro-knowledge-base/sitemap-pages.xml (undated; read 2026-10-11).
23. GSPro User Guide V2.0.2. https://www.golfinsim.com/wp-content/uploads/2023/11/GSPro-Users-Guide-V2.0.2.pdf (2022-11-01; **old**).

Unity documentation:

24. Mesh.colors (2018.2). https://docs.unity3d.com/2018.2/Documentation/ScriptReference/Mesh-colors.html
25. FBX Importer, Model tab, and ModelImporterIndexFormat (2018.2). https://docs.unity3d.com/2018.2/Documentation/Manual/FBXImporter-Model.html, https://docs.unity3d.com/2018.2/Documentation/ScriptReference/ModelImporterIndexFormat.html
26. Level of Detail (2018.2). https://docs.unity3d.com/2018.2/Documentation/Manual/LevelOfDetail.html
27. Camera.layerCullDistances (2018.2). https://docs.unity3d.com/2018.2/Documentation/ScriptReference/Camera-layerCullDistances.html
28. Reflection Probe (2018.2). https://docs.unity3d.com/2018.2/Documentation/Manual/class-ReflectionProbe.html
29. GPU instancing and Occlusion culling (2018.4). https://docs.unity3d.com/2018.4/Documentation/Manual/GPUInstancing.html, https://docs.unity3d.com/2018.4/Documentation/Manual/OcclusionCulling.html
30. AssetBundles intro (2018.4). https://docs.unity3d.com/2018.4/Documentation/Manual/AssetBundlesIntro.html
31. TerrainData.splatPrototypes (2018.4, Obsolete). https://docs.unity3d.com/2018.4/Documentation/ScriptReference/TerrainData-splatPrototypes.html

Stix Games and Asset Store:

32. Stix Games docs, under https://docs.stixgames.com: `/general/quick-start.md`, `/general/grass-renderer-components/nature-mesh-filter.md`, `/general/grass-renderer-components/grass-renderer.md`, `/general/material-settings.md`, `/general/material-settings/shader-variants.md`, `/general/material-settings/visual-settings.md`, `/general/material-settings/performance-settings.md`, `/guides/performance-optimization.md`, `/guides/improve-visuals.md`, `/guides/render-pipelines.md`, `/advanced-features/global-shader-variables.md`, `/advanced-features/grass-painter.md` (undated; read 2026-10-11).
33. Stix "DirectX 11 Grass Shader", Asset Store (release notes 2.0.0-2.12.0). https://assetstore.unity.com/packages/vfx/shaders/directx-11/directx-11-grass-shader-36335 (v2.12.0, 2026-07-30).
34. Vegetation Studio Pro, Asset Store (deprecated; last version 1.4.9). https://assetstore.unity.com/packages/tools/terrain/vegetation-studio-pro-131835 (2022-09-08; **old**).

Low-trust secondary:

35. The Perfect Lie guides. https://tpl.realitysportsonline.com/articles/guides/gspro-getting-started, https://tpl.realitysportsonline.com/articles/guides/gspro-vegetation (2026, no author or date; **low**).
36. Zeros and Ones, "OPCD course creation" ("Unity 2018.2.8f1", as of March 2021). https://zerosandonesgcd.com/opcd-course-creation/ (**old**).
37. Home Golf Hero GSPro review (claims a Unity 6 migration; not confirmed officially). https://homegolfhero.com/reviews/gspro-software-review/ (2026; **low**).

Local files (this repo, 2026-10-11):

38. `output/gspro/fbx_manifest.json` (object names, materials, vertex counts).
39. `output/gspro/terrain.json`.
40. `output/gspro/unity/Editor/WestmountSetup.cs`.
41. `output/gspro/greenkeeper.json`.
42. `output/gspro/grass_3dg.json`.
43. `output/gspro/course_opcd.svg` and `scripts/export_gspro.py` (Custom1 = court, Custom2 = building).
44. `output/gspro/trees.csv` and `output/gspro/tree_prefabs.json`.
45. `research/NOTES.md` (course facts, OB line, driving range).
