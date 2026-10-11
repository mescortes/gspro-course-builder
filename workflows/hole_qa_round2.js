export const meta = {
  name: 'mountaingate-hole-qa-r2',
  description: 'QA round 2: check the rebuilt (LiDAR-registered) 18-hole model for regressions and residual issues; verify and apply fixes',
  phases: [
    { title: 'Inspect', detail: '6 inspectors x 3 holes on the rebuilt model' },
    { title: 'Verify', detail: 'adversarial verifier per group; appends approved overrides' },
  ],
}

const ROOT = '/Users/daniele/Development/mountain-gate'
const GROUPS = [[1, 2, 3], [4, 5, 6], [7, 8, 9], [10, 11, 12], [13, 14, 15], [16, 17, 18]]

const COMMON = `HARD RULE - BROWSER: NEVER use any browser tools (mcp__Claude_Browser__*, mcp__claude-in-chrome__*, preview_*, navigate, computer, tabs_*); they drive the user's visible browser and can play audio. Research only with WebSearch/WebFetch (text). You are working on a survey-grade 3D model of MountainGate Country Club (Los Angeles) for the GSPro golf simulator.
Project root: ${ROOT}. Python: ${ROOT}/.venv/bin/python (run from the project root). Coordinates: UTM 11N metres (EPSG:32611).
Course = North/South: holes 1-9 North, 10-18 South. Lake holes (scenery) are 19-27; 98 = cart paths, 99 = background.
This is QA ROUND 2. Read build/qa/round2_context.md first: it explains what changed since round 1 (imagery registered to the LiDAR,
automatic tee/bunker validation, deep rough, overrides shifted, tee decisions). Round-1 verdicts: build/qa/qa_round1_verdicts.json.

FILES: build/qa/holeNN/{overview,surfaces,hillshade,tees,green}.png + info.json (freshly generated from the rebuilt model),
output/holes.json, features/course_surfaces.geojson (surfaces; property "source": "override" marks QA overrides), features/overrides/,
research/hole_descriptions.json, research/NOTES.md, output/maps/holeNN_map.png and holeNN_green.png.
IMAGE LEGEND: outlines green=cyan, fringe=pale teal, fairway=bright green, semirough/rough=green shades, deep rough=dark green, tee=magenta,
bunker=yellow, cart path=light grey, native/mulch=orange, water=blue, building=red, road=dark grey. THICK = this hole, thin = other/background.
Tee dots gold/blue/white "C 343/342" = measured/card yards. Red circles = aim points, white line = line of play, red dots = pins.
GRID: 25 m lines (overview/surfaces/hillshade) or 10 m (tees/green), labelled with the last 3 digits of the easting/northing. info.json ->
image_bounds_utm gives exact bounds; pixel (px, py) -> E = xmin + px*(xmax-xmin)/width, N = ymax - py*(ymax-ymin)/height.
The imagery now IS registered to the LiDAR, so photo features, LiDAR hollows/decks and model outlines should coincide (within ~0.5 m).
YARDAGE: |tee -> aim1| + ... + |aimN -> green centre| in metres / 0.9144. Documented accepted tee gaps: hole 10 Forward (~8 yd short),
hole 11 Forward (~6 yd long), hole 17 all tees (~15-20 yd short, markers on the real OSM decks), hole 18 Forward (~35 yd short, only real pad).
OVERRIDES: features/overrides/holeNN.geojson (FeatureCollection; Polygon in UTM; properties surface, hole, reason, frame). An override is burned
on top of the automatic map (later overrides win). Valid surfaces: green, fringe, fairway, semirough, rough, deeprough, tee, bunker, cartpath,
native, water. Meta: features/overrides/holeNN_meta.json {"aim_points_utm": [[e, n], ...], "tees_utm": {"championship"|"middle"|"forward": [e, n]},
"notes": "...", "frame": "lidar"}. NEW geometry must carry "frame": "lidar" (it is drawn on the registered imagery).
Never edit scripts or any other file. Be conservative: only fix what is clearly wrong in the imagery/LiDAR.`

const INSPECT = {
  type: 'object',
  properties: {
    holes: { type: 'array', items: { type: 'object', properties: {
      hole: { type: 'integer' },
      verdict: { type: 'string', enum: ['good', 'minor_issues', 'major_issues'] },
      summary: { type: 'string' },
      round1_regressions: { type: 'array', items: { type: 'string' }, description: 'round-1 overrides that are now misaligned or harmful' },
      issues: { type: 'array', items: { type: 'object', properties: {
        category: { type: 'string' }, severity: { type: 'string', enum: ['high', 'medium', 'low'] },
        description: { type: 'string' }, location_utm: { type: ['array', 'null'], items: { type: 'number' } } },
        required: ['category', 'severity', 'description'] } },
      proposed_feature_count: { type: 'integer' }, proposed_meta: { type: 'boolean' } },
      required: ['hole', 'verdict', 'summary', 'issues', 'proposed_feature_count', 'proposed_meta'] } },
  },
  required: ['holes'],
}
const VERIFY = {
  type: 'object',
  properties: {
    holes: { type: 'array', items: { type: 'object', properties: {
      hole: { type: 'integer' },
      approved: { type: 'array', items: { type: 'object', properties: { index: { type: 'integer' }, surface: { type: 'string' }, reason: { type: 'string' } } } },
      rejected: { type: 'array', items: { type: 'object', properties: { index: { type: 'integer' }, reason: { type: 'string' } } } },
      overrides_removed: { type: 'array', items: { type: 'string' }, description: 'round-1 override features deleted because they are now wrong' },
      meta_applied: { type: 'string' },
      remaining_issues: { type: 'array', items: { type: 'string' } },
      quality_score: { type: 'integer', description: '1-10 overall fidelity of this hole after your changes' } },
      required: ['hole', 'approved', 'rejected', 'meta_applied', 'remaining_issues', 'quality_score'] } },
  },
  required: ['holes'],
}

return await pipeline(GROUPS,
  (holes) => agent(`${COMMON}

YOUR TASK: inspect holes ${holes.join(', ')} of the REBUILT model. For each hole look at all five images, info.json and the green map, then check:
(a) registration: bunker outlines sit on the sand AND in the LiDAR hollows, cart paths on the paths, greens on the pads;
(b) round-1 overrides (source "override" in course_surfaces.geojson) still line up after the +2.75 m shift and are still right; list any that are
    now misaligned or harmful under round1_regressions;
(c) green outline and greenside bunkers; (d) every real tee pad present and assigned to this hole, markers on pads, yardages vs card
    (respect the documented gaps); (e) fairway outline; aim points on doglegs; (f) water, deep rough (chaparral only, not mown rough), native;
(g) anything else that would look or play wrong in GSPro.
Write fixes ONLY to build/qa/holeNN/proposal_r2.geojson (and proposal_r2_meta.json); to remove a harmful round-1 override, list it in your
summary instead (the verifier edits the override file). Render a proposal with
.venv/bin/python scripts/qa_overlay.py xmin ymin xmax ymax 0.1 build/qa/holeNN/proposal_r2_check.png build/qa/holeNN/proposal_r2.geojson
and look at it. Return the structured summary.`, { label: `inspect-r2:${holes.join('-')}`, phase: 'Inspect', schema: INSPECT }),
  (insp, holes) => agent(`${COMMON}

YOUR TASK: adversarially verify the round-2 findings for holes ${holes.join(', ')} and apply what survives.
Inspector report: ${JSON.stringify(insp)}
1. For each proposal in build/qa/holeNN/proposal_r2.geojson / proposal_r2_meta.json: render it over the imagery, check the LiDAR, try to refute it.
2. For each round-1 regression the inspector reported: confirm it, and if confirmed edit features/overrides/holeNN.geojson to delete or correct
   that feature (keep every other feature intact).
3. APPEND the approved new features (with "frame": "lidar") to features/overrides/holeNN.geojson (create it if missing; never drop existing
   features unless removing a confirmed regression), and MERGE approved meta into features/overrides/holeNN_meta.json (keep existing keys unless
   you are replacing them on purpose; set "frame": "lidar" only if the file has no other un-shifted coordinates, i.e. if it already has
   "frame": "lidar" or you are writing all coordinates yourself).
4. Give each hole a 1-10 quality score for how faithfully the model now represents it.
Return the structured verdicts.`, { label: `verify-r2:${holes.join('-')}`, phase: 'Verify', schema: VERIFY }),
)
