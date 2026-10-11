export const meta = {
  name: 'gspro-cosmetics-research',
  description: 'Research current GSPro/OPCD cosmetic practice (3D grass, vegetation, lips/curbs, water, trees, props, lighting), verify, and write a sourced build spec (text-only web research, no browser)',
  phases: [
    { title: 'Sweep', detail: 'six researchers, each a different angle (local OPCD docs, 3DG shader, current GSPro practice, vegetation/props, water/lighting, benchmarks)' },
    { title: 'Verify', detail: 'adversarial check of each researcher\'s load-bearing claims' },
    { title: 'Synthesize', detail: 'write research/GSPRO_COSMETICS.md + build spec' },
  ],
}

const CONTEXT = `
HARD RULE - BROWSER: NEVER use any browser tools (anything named mcp__Claude_Browser__*, mcp__claude-in-chrome__*, preview_start, navigate, computer, tabs_*). They drive the user's visible browser and play video and audio. Do not load them with ToolSearch. Research ONLY with WebSearch and WebFetch (text only; load them with ToolSearch if deferred). For YouTube videos use only what WebSearch/WebFetch return as text (title, description); never try to play a video or fetch a transcript through a browser. Do not start servers.

PROJECT CONTEXT (read carefully):
We are building a GSPro golf-simulator course of MountainGate Country Club North/South (Los Angeles) in /Users/daniele/Development/mountain-gate.
We work on macOS and CANNOT run Unity, GSPro, GreenKeeper or Windows tools. Our pipeline is Python + Blender (headless) and produces:
- output/mountain_gate_ns.glb (textured glTF, viewed in our three.js viewer viewer/index.html) and
- an OPCD hand-off package in output/gspro/: Unity terrain heightmap (4097^2 RAW over 2048 m), satellite overlay, OPCD SVG (layers Hole01..Hole27, Hole98 paths, Hole99 outer),
  course_meshes.fbx with objects named Hole##_<Surface> (e.g. Hole01_Fairway, Hole01_Bunker, Hole01_Bunker_Lip, Hole99_Water_Base, Hole99_WaterPlane, Hole98_Concrete, Hole99_DeepRough), structures.fbx, backdrop.fbx,
  trees.csv (68,750 LiDAR trees: archetype oak/pine/sycamore/eucalyptus/shrub, position, height, crown radius), greenkeeper.json (tees/pins/aim points/hazards).
GSPro courses are Unity asset bundles built with the community OPCD toolchain (Inkscape SVG -> GSProSVGConvert -> Blender OPCD add-on -> FBX -> Unity "OPCD base project" with SetMeshMaterial.cs) and annotated in GreenKeeper.
Local reference material (ALREADY DOWNLOADED, read-only, do not redistribute):
- research/opcd_docs.txt and research/opcd.txt (~385 KB each: text export of the OPCD documentation Google Doc; very long lines, use grep/sed with cut)
- research/opcd_toolset_dl/x/ (OPCD toolset v06-2021: "Outline of the OPCD Process for GSPro.pdf", Blender Files/OPCD_Conversion_Tool_06092021_1.py, Unity files/SetMeshMaterial.cs, ExportTerrain.cs)
- research/NOTES.md (our own notes)
Already established from those local files: grass blades in GSPro are the Stix Games "DirectX 11 Grass Shader" (Unity Asset Store 36335), nicknamed 3DG, added to surface meshes via "Grass Renderer" + "Nature Mesh Filter" components with materials from the OPCD base project, layer "600m cull";
VSPro (Vegetation Studio Pro) for fescue/native grasses/trees ("if the lawn mower goes there use 3DG, otherwise VSPro"), but the doc says VSPro is no longer sold;
SetMeshMaterial.cs matches object-name substrings: _Tee _Fairway _GreenFringe _Green _SemiRough _Rough _DeepRough _Concrete _Bunker_Lip _Pot_Wall _Pot _WaterPlane _Bulkhead_Base _Curb _Pinestraw _Bunker _Water_Base Stone_Wall Wood_Wall Custom1 Custom2, and sets PhysicMaterials (waterPhMat only on _WaterPlane; _Water_Base gets rough physics);
the Blender add-on makes a Bunker_Lip band (insets 5 cm/2 cm/1 cm, depths -2/-2/+0.5 cm), Curbs (0.12 m band extruded 0.15 m, sunk 0.13 m), WaterPlane (flat, 2 m outset, 3 m remesh) and Water_Base/Water_Edge (0.15 m edge band). We have ALREADY implemented Bunker_Lip, Water_Base(+Water_Edge slot) and WaterPlane objects following these.
The user's own question that started this task: "when I play in GSPro I see grass blades and I don't know whether there are specific assets that GSPro uses for that or whether they are simply regular meshes".
Our TODO for this task: research GSPro grass rendering; per-surface 3DG settings + density masks; bunker lips, cart-path curbs, green collars, tee-box edges; satellite shader for distant terrain; Unity tree prefabs per archetype (LODs, wind); ground clutter; water (_WaterPlane, reflections); structures (roofs, facades, fences, OB stakes, benches, ball washers, signage, yardage markers); lighting/post-processing presets.

RESEARCH RULES: Cite every claim with a source (URL, or local file + line/section). Prefer primary sources (asset docs, OPCD docs, GSPro official site/forum/changelogs, designer videos' descriptions). Note dates — practice changes over time; flag anything older than 2023 as possibly outdated. Distinguish "verified from source" vs "inferred". Do not invent property names or settings. Do not write any files in the project.`

const FINDINGS = {
  type: 'object',
  properties: {
    angle: { type: 'string' },
    claims: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          topic: { type: 'string', description: 'grass | vegetation | trees | edges | water | lighting | terrain | props | pipeline | performance | other' },
          claim: { type: 'string' },
          source: { type: 'string', description: 'URL or local file + line/section' },
          source_date: { type: 'string' },
          confidence: { type: 'string', description: 'high | medium | low' },
          load_bearing: { type: 'boolean', description: 'true if our build decisions depend on it' },
        },
        required: ['topic', 'claim', 'source', 'confidence', 'load_bearing'],
      },
    },
    implications: { type: 'array', items: { type: 'string' }, description: 'concrete things our pipeline should produce or change, given we cannot run Unity' },
    open_questions: { type: 'array', items: { type: 'string' } },
  },
  required: ['angle', 'claims', 'implications', 'open_questions'],
}

const VERDICTS = {
  type: 'object',
  properties: {
    checked: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          claim: { type: 'string' },
          verdict: { type: 'string', description: 'confirmed | corrected | refuted | unverifiable' },
          correction: { type: 'string' },
          evidence: { type: 'string' },
        },
        required: ['claim', 'verdict', 'evidence'],
      },
    },
    missed: { type: 'array', items: { type: 'string' }, description: 'important facts the researcher missed, with sources' },
  },
  required: ['checked', 'missed'],
}

const ANGLES = [
  { key: 'local-docs', prompt: `ANGLE: exhaustive read of the LOCAL OPCD material (no web needed). Read research/opcd_docs.txt end to end (it is long: page through it with sed -n in chunks, cut long lines), plus the toolset PDF (pdftotext if available, else skip) and the Blender/Unity scripts. Extract EVERY convention and recommendation relevant to cosmetics and visual quality: 3DG grass (components, layers, material names, settings, density/colour textures, which surfaces get it, performance), Vegetation Studio Pro usage (biomes, masks, rules), Unity terrain details, satellite shader for distant terrain, bunker lips/edges, pot bunker walls, curbs, bulkheads/walls, water (Water_Base/Edge/WaterPlane, shaders, reflection probes), trees (assets recommended, colliders, LODs, wind, billboards), props/assets (SketchUp import, Nature Manufacture, polygon budgets), lighting (probes, lighting engine update), FPS/performance budgets, base project versions, recommended Unity version, cull layers, anything about green collars, tee edges, mowing stripes, divots, flowers, fescue. Give line numbers.` },
  { key: 'web-3dg', prompt: `ANGLE: the Stix Games "DirectX 11 Grass Shader" (a.k.a. 3DG / Stixx grass) as used in GSPro. Find its official documentation/manual as TEXT (Stix Games website, Asset Store page 36335, PDF manual, Unity forum thread) and describe precisely: how it renders (geometry/tessellation shader on the mesh surface vs instanced meshes), the components (Grass Renderer, Nature Mesh Filter, etc.), material properties and their exact names (grass types, height/width ranges, density, density texture/mask, colour texture, colour variation, wind, LOD/tessellation distance, culling), how density and colour maps are authored (UV-mapped textures? vertex colours? which channels), how GSPro/OPCD designers configure it for fairway/semi-rough/rough/deep rough (typical blade heights, density), the "3dg_OPCD" package, and any GSPro-specific constraints (Unity version, DX11, performance). Also check whether GSPro itself (not the course) adds grass. Search GSPro forums (gsprogolf.com), theperfectlie.net, reddit r/GSProGolf; for YouTube use only search-result text.` },
  { key: 'web-gspro-current', prompt: `ANGLE: the CURRENT (2024-2026) state of GSPro course building. What Unity version and OPCD base project version are current? Has the toolchain changed (new OPCD tools, new Blender add-on versions, "Course Forge", new GreenKeeper features, new lighting engine, HDRP/URP, new grass system replacing 3DG, VSPro replacement after it was discontinued)? What do GSPro's official course-quality guidelines or "featured/OPCD course" standards require visually? How are courses distributed (GSPro course list / OPCD server)? Search gsprogolf.com (forum, news, changelogs, course creation sections), theperfectlie.net, opcd-related sites, reddit. Give dates for everything.` },
  { key: 'web-vegetation-props', prompt: `ANGLE: vegetation and props in GSPro courses. Trees: which tree assets designers use (Nature Manufacture, SpeedTree, Tree assets from the OPCD base project, custom), LOD/billboard setup, wind (Unity WindZone, shader), colliders for ball physics (do trees need colliders? capsule colliders on trunks? how GSPro handles leaves), placement tools (VSPro, terrain trees, scripts that place from CSV/GIS). Grasses/flowers/ground clutter: fescue, native grass, leaf litter, pine straw decals, flowers, rocks. Course props: tee markers (are they provided by GSPro at runtime or modelled by the designer?), flagstick/cup (runtime or designer?), OB stakes (white), hazard/penalty stakes (red/yellow), yardage markers/plates, ball washers, benches, signs, cart path curbs, fences, rakes in bunkers. Clarify what GSPro renders at runtime (pin, tee markers, ball, golfer?) vs what the course designer must model. Cite sources.` },
  { key: 'web-water-lighting', prompt: `ANGLE: water, lighting, sky and distant terrain in GSPro courses. Water: which shaders (OPCD base project water, Lux Water, R.A.M. River Auto Material), WaterPlane conventions, reflection probes vs realtime reflections, how the water hazard is detected (collider/physic material). Lighting: what the course provides (directional light, skybox, reflection/light probes, baked GI?) vs what GSPro controls at runtime (time of day, weather, the 2022 "new lighting engine", graphics settings), post-processing (does the course ship a post-process profile? colour grading?), fog/atmosphere. Distant terrain: satellite shader / far terrain with imagery, background mountains, horizon. Give specific settings designers recommend where available. Cite sources with dates.` },
  { key: 'web-benchmarks', prompt: `ANGLE: visual quality benchmarks. Identify the GSPro courses most praised for visuals (2023-2026) and their designers, and what reviewers/players single out (3D grass density and colour, mowing stripes, fescue and native areas, bunker edges/lips/faces, tree quality, water, lighting, distant backgrounds, clubhouse/structures, ground detail). Also common complaints about low-quality courses (flat textures, no 3D grass, floating trees, visible seams, bad FPS). Turn this into a concrete checklist of visual features a high-quality GSPro course has, ranked by how much players notice them. Cite sources (forum threads, reviews, articles).` },
]

phase('Sweep')
const results = await pipeline(
  ANGLES,
  a => agent(`${CONTEXT}\n\n${a.prompt}\n\nReturn structured findings. Mark load_bearing=true on claims our build decisions would depend on.`,
             { label: `sweep:${a.key}`, phase: 'Sweep', schema: FINDINGS }),
  (f, a) => {
    if (!f) return null
    const lb = f.claims.filter(c => c.load_bearing).slice(0, 14)
    return agent(`${CONTEXT}\n\nYou are an adversarial fact-checker. A researcher (angle: ${a.key}) made the load-bearing claims below. For EACH claim, independently re-open the cited source (or find a better one) with WebSearch/WebFetch or the local files, and try to REFUTE it: wrong property names, outdated practice, misattributed source, overgeneralisation. Default to "unverifiable" if you cannot find evidence. Also list important facts for this angle that the researcher missed (with sources).\n\nCLAIMS:\n${JSON.stringify(lb, null, 1)}`,
                 { label: `verify:${a.key}`, phase: 'Verify', schema: VERDICTS })
      .then(v => ({ angle: a.key, findings: f, verdicts: v }))
  },
)

const good = results.filter(Boolean)
log(`${good.length}/${ANGLES.length} angles researched and verified`)

phase('Synthesize')
const spec = await agent(`${CONTEXT}

You are the lead researcher. Below are the findings from ${good.length} independent research angles, each followed by an adversarial verifier's verdicts (confirmed/corrected/refuted/unverifiable) and facts the researcher missed. Weigh them: drop refuted claims, apply corrections, mark unverifiable ones as such.

Write the file research/GSPRO_COSMETICS.md (this is the ONLY file you may write). Structure:
1. "Short answer" — how GSPro renders grass blades (answering the user's question directly), in plain words.
2. How a GSPro course's visuals are put together today: what GSPro renders at runtime vs what the course designer ships (grass, vegetation, trees, edges, water, lighting/sky, distant terrain, props), with the current toolchain/Unity version and dates.
3. Conventions we must follow (object names, materials, layers, physic materials, geometry of lips/curbs/water planes, cull distances), each with source.
4. A visual-quality checklist ranked by player impact.
5. BUILD SPEC for our pipeline, given we cannot run Unity: a prioritised list of concrete deliverables, each with: what to produce (files, object names, textures, data), how (algorithm sketch using our data: course_surfaces.geojson surfaces, dem_final.tif, imagery, LiDAR CHM, trees.csv), how to verify it automatically (tests we can write), and what the Unity-side designer does with it. Include both (a) the OPCD/Unity hand-off (e.g. Curb meshes, 3DG per-surface material settings + density/colour masks, vegetation/clutter density masks, tree prefab FBX with LODs, prop meshes + placements, Unity editor scripts to apply them) and (b) matching improvements to our own glTF/three.js viewer so it previews the GSPro look (instanced grass blades on rough surfaces, curbs, reflective water, props, lighting). Be explicit about which settings are verified vs our best estimate.
6. Sources (numbered list with dates).

Keep it factual and specific. Then return a short summary (<= 25 lines) of the spec's prioritised deliverables and any important corrections to what we believed.

FINDINGS:
${JSON.stringify(good, null, 1)}`, { label: 'synthesize', phase: 'Synthesize' })

return { spec, angles: good.map(g => ({ angle: g.angle, n_claims: g.findings.claims.length, verdicts: g.verdicts ? g.verdicts.checked.map(c => c.verdict) : [] })) }
