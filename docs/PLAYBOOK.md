# Playbook: build a new course

From nothing to a GSPro hand-off package and a reviewed model, the way Westmount, Brambles and Whistle Bear were
built. Each phase ends with a checkpoint; do not move on until it holds. Commands run from the repository root. Times
are for an Apple M-series laptop; the downloads depend on the servers.

The multi-agent steps (research, QA) use Claude Code workflows (`workflows/*.js`). Everything else is plain Python and
can be run by hand.

## 0. Setup (once)

* Python 3.12 and [uv](https://github.com/astral-sh/uv); headless Blender 4.2 LTS for the FBX step (`BLENDER=` its
  binary). About 15 GB of RAM at peak and 5-10 GB of disk per course.
* `uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-lock.txt` (the exact
  packages of the golden Westmount build; `requirements.txt` lists the direct dependencies unpinned)
* `COURSE= .venv/bin/python -m pytest -q tests --ignore=tests/test_course.py` must pass (no data needed).

### Linux and Claude cloud sessions

`tools/setup_linux.sh` sets up Ubuntu 24.04 x86_64: the X11 / GL libraries Blender's Linux build loads even with `-b`,
Blender 4.2.23 LTS (checksum-verified) and the golden Python environment, linked as `.venv` in the checkout. As root it
installs into `/opt`, otherwise into `~/.local/share/gspro-course-builder`; it prints the `BLENDER=` path.

A Claude Code cloud session (claude.ai/code) is a fresh Ubuntu 24.04 VM per session with about 4 vCPUs, 16 GB of RAM
and 30 GB of disk, and no GPU (code.claude.com/docs/en/cloud-environments). For this engine that means:

* **Setup script**: use `tools/setup_linux.sh` as the environment's setup script; what it installs is cached with the
  environment (when it finishes within about 5 minutes). Set `BLENDER=/opt/blender-4.2.23-linux-x64/blender` in the
  environment's variables. Each session starts from a fresh clone, so add a SessionStart hook (or run once per
  session) `ln -sfn /opt/gspro-venv .venv`.
* **Network**: set the environment's network access to Custom, keep the default package-manager list, and add the
  hosts the downloads use: `tnmaccess.nationalmap.gov`, `rockyweb.usgs.gov` (USGS LiDAR; `prd-tnm.s3.amazonaws.com`
  for the 1 m DEM is in the default `*.amazonaws.com`), `apps.geo.fpac.usda.gov` (NAIP), `overpass-api.de`,
  `api.openstreetmap.org` (OSM), `api.polyhaven.com`, `dl.polyhaven.org` (textures), `download.blender.org` (setup),
  and for Ontario courses `ws.geoservices.lrc.gov.on.ca`. A blocked host answers HTTP 403 with
  `x-deny-reason: host_not_allowed`.
* **Nothing in `data/`, `build/` or `output/` survives the session** (they are not in git): download and build in one
  session, and commit what the course needs (`courses/<slug>/`) before it ends.
* **Memory**: 16 GB is at the edge for an 18-hole build; `build_all.py` prints each step's peak memory. Prefer your
  own machine (or Remote Control to it) for full builds when a course peaks above about 14 GB.
* **Long steps**: run builds as background commands with an explicit timeout (a background command gets 30 min by
  default and up to 2 h); run `build_all.py` in ranges of steps rather than all at once.
* **Commit attribution**: cloud sessions add a session link to commits and PR bodies; the `attribution` settings
  (settings reference) turn it off.

## 1. Is the course buildable?

Before any work, find out what public data covers it. This decides everything else.

| Need | What to look for | Engine provider |
|---|---|---|
| LiDAR point cloud over the whole course | National / regional catalogues (USGS 3DEP via the National Map, NRCan CanElevation, national mapping agencies). Note the **flight date** (read the points' GPS times: folder names lie) and whether it predates any construction. Leaf-off or leaf-on. | `usgs_3dep`, `nrcan_copc` |
| Orthophoto | Ideally 0.1-0.3 m with a near-infrared band, from a service whose licence allows derived textures to be redistributed (not Esri World Imagery). Note its date and season. 0.6 m (USDA NAIP) works but is coarse. | `arcgis_imageserver` |
| 1 m DEM (and DSM) for a 5 km square | Usually from the same survey. | `cog_dem` |
| OSM | A `leisure=golf_course` outline and `golf=hole` lines for every hole; greens, tees, fairways, bunkers. | (built in) |
| Scorecard | Par, yards per tee, stroke index, ratings. | course.toml |

Data from somewhere the providers do not cover needs a new provider in `scripts/sources/` (see the four existing
ones: each is a few functions; `__init__.provider(kind)` picks them by the `provider` key of `[sources.*]`).

Run the research workflow for the facts (scorecard, holes, history, data), each claim re-checked by a verifier:

```
Workflow workflows/course_research.js, args {name, location, slug, root: <absolute repo path>, notes?}
```

**Checkpoint:** LiDAR, photo and DEM sources named with their dates; scorecard found; you know whether OSM maps the
course and what changed on the course since the LiDAR was flown.

## 2. Scaffold

```bash
.venv/bin/python scripts/new_course.py <slug> "Course name" --region <region> --osm way/<id> [--osm way/<practice id>]
# or, for a course OSM does not map:
.venv/bin/python scripts/new_course.py <slug> "Course name" --region <region> --bbox=<w>,<s>,<e>,<n>
```

It writes `courses/<slug>/course.toml`: the frame (UTM CRS from the region's datum, origin, base height, build extent
CORE = outline + 100 m in 256 m tiles, the 2048 m GSPro terrain square) and the likely `[sources]`. `--crs EPSG:<code>`
sets another frame, such as the national metre grid the LiDAR is delivered in. It is written as its EPSG code. A
compound CRS, Web Mercator, or a grid whose metres are more than 0.5 % off ground metres at the course is refused
(`new_course.py` MAX_SCALE_ERROR: yardages would be off by as much).

**A region** (`regions/<name>.toml`) holds what is true of a whole area: tree archetypes and the rules that sort LiDAR
crowns into them, foliage cards, 3D grass, the turf colour target, building palettes, backdrop vegetation, viewer sky,
and scaffold defaults (datum, providers, photo service). Use an existing one if the trees and the data sources match;
otherwise copy the closest and edit it (`regions/TEMPLATE.toml.example` lists the keys; `check_course.py` and
`tests/test_robustness.py` validate a region).

Fill in `course.toml` by hand from the research:

* `[course]`: name, short name, model name.
* `[[tees]]` back to front: key, name, colour, `gkd_slot` (GreenKeeper tee slot: Black, White, Green, Blue, Yellow, Red;
  at most six sets).
* `[scorecard]` `hole = [par, yards per tee...]`, `[stroke_index]` men / women, `[ratings]`.
* `[holes]`: playable holes, nines; `osm_ref` if the OSM refs differ from the card's holes.
* `[osm]`: `outline` (the course's own leisure=golf_course ways; a practice area can be a second one), `exclude` (OSM
  elements that are wrong or gone: a disused runway, a demolished building, a neighbour's hole line).
* `[lidar] leaf_off`, `[imagery] leaf_off`: from the flight and photo dates. They change how trees are segmented and how
  ground under canopy is treated, and the region's tree classifier expects one of them.
* `[structures] parking`: OSM parking ids that get parked cars.

```bash
COURSE=<slug> .venv/bin/python scripts/check_course.py
```

**Checkpoint:** check_course reports nothing missing in course.toml; every hole has a line, a green and a tee (or the
course goes the no-OSM route, §4).

## 3. Download

```bash
export COURSE=<slug>
.venv/bin/python scripts/fetch_data.py lidar osm imagery
.venv/bin/python scripts/fetch_textures.py
.venv/bin/python scripts/fetch_backdrop.py
.venv/bin/python scripts/check_course.py      # the data section: coverage, bands, empty pixels
```

The OSM snapshot is saved in `courses/<slug>/research/` and is what the model is built from: commit it. Delete it and
fetch again to refresh. LiDAR goes to `data/<slug>/lidar/`; keep only the tiles of the chosen project there.

**Checkpoint:** check_course's data section shows LiDAR covering CORE, the photo 0 % empty, the backdrop DTM present.

## 4. Courses OSM does not map

Draw the lines of play and draft the rest (Brambles):

1. `courses/<slug>/features/golf.geojson`: one `golf=hole` LineString per hole (properties `ref`, `par`), back tee ->
   turning points -> green centre, in the course CRS. GPS course layouts (GolfNow / 18Birdies feeds) give tee and
   green points; check them against the photo.
2. `courses/<slug>/research/layout.geojson`: GPS points (`kind` tee with `tee` key, `green_front`, `green_center`,
   `green_back`, `hole`).
3. After the rasters step (§5), draft the features:
   `COURSE=<slug> .venv/bin/python scripts/draft_features.py`. It writes greens, tees, fairways, bunkers, ponds, gravel
   paths and the course outline into golf.geojson (tagged `draft=yes`; hand-drawn features are kept) and review sheets
   to `build/<slug>/draft/hole_NN.jpg`. Thresholds are in `[draft]` (see `draft_features.DEFAULTS`); tune them on
   the sheets, then commit the draft. It only has to be good enough to train the classifier: the QA rounds correct
   the model.
4. Set `[tuning] trace_paths = false` if the photo's path tracer follows turf edges instead of paths (look at
   `build/<slug>/paths_detected.geojson` after the paths step).

## 5. First build

```bash
MG_PROFILE=test .venv/bin/python scripts/build_all.py          # optional: a small extent around [test_profile] holes
.venv/bin/python scripts/build_all.py register prefabs        # every step up to the GSPro package
BLENDER=/path/to/blender .venv/bin/python scripts/build_all.py fbx fbx
.venv/bin/python scripts/build_all.py maps views
```

`build_all.py <first> <last>` runs a range of steps (names in `scripts/build_all.py` STEPS). The longest are rasters,
classify, vectorize, export and the first backdrop (it downloads a 5 km photo; some image servers take an hour).

**Registration:** the photo is rarely exactly on the LiDAR.

```bash
.venv/bin/python scripts/measure_registration.py    # bunker sand vs LiDAR hollows, per quarter of the course
```

Put the shift in `[imagery] shift` (metres east, north) when the quarters agree, then rebuild from `register`
(and redraft, §4, if the features were drafted from the photo). The printed `shift = [...]` line is the shift the
registered photo already carries plus the measurement, so it stays right when you measure again; a `!!` line says
when course.toml's shift has changed since `register` last ran. Westmount: 0.25 m south; Brambles: 0.75 m east;
Whistle Bear: 0.25 m east.

**Checkpoint:** `build_all.py` ends without error; `measure_registration.py` shows no shift beyond a pixel.

## 6. Tests

```bash
.venv/bin/python -m pytest -q --course <slug> tests/test_course.py
```

Read failures as data: a tee yardage gap means a wrong or missing pad, or a card that disagrees with the ground; a
green size or slope failure means a green outline that takes in banks or misses half the putting surface; "no
fairway" means a fairway that carries another hole's number. Course-dependent limits go in `course.toml [tests]`
(`green_area`, `min_bunkers`, `green_slope_max`, `known_tee_gaps = { "7.back" = 40 }` with the reason in
research/NOTES.md); fix the rest.

## 7. QA rounds

```bash
.venv/bin/python scripts/qa_hole.py $(seq 1 18)     # build/<slug>/qa/holeNN/{overview,surfaces,hillshade,tees,green}.png
```

Write `courses/<slug>/research/qa_brief.md` (see Westmount's): the course in two lines, tee sets and their marker
labels, what the LiDAR and the photo look like (season, resolution, NIR), what OSM maps, what changed since the LiDAR,
open card questions. Then:

```
Workflow workflows/hole_qa.js, args {root: <absolute repo path>, course: <slug>, round: 1}
```

Inspectors propose overrides per hole; adversarial verifiers keep what the photo and the LiDAR support and write
`courses/<slug>/features/overrides/holeNN.geojson` (and `holeNN_meta.json` for tee markers and aim points).
Rebuild from `assemble`, regenerate the QA images, run the tests, then round 2 (`round: 2`), which also removes
round-1 overrides that turned out wrong. **Problems that recur across holes are engine bugs**: fix them in the
engine with a test, not with overrides.

**Checkpoint:** every hole scores at least 8 of 10 from its verifier; the tests pass or each failure is documented.

## 8. Look at it

```bash
python3 scripts/devserver.py 8765   # http://localhost:8765/viewer/?course=<slug>&v=1#h1-tee
```

Fly every hole. `docs/LESSONS.md` (Viewer) explains the capture helpers for headless renders.

## 9. Hand-off and documentation

* `output/<slug>/gspro/` is the package for the Windows side (Unity 2018.2 + OPCD + GreenKeeper):
  research/GSPRO_COSMETICS.md.
* Write `courses/<slug>/README.md` (Westmount's is the model; `scripts/readme_table.py` fills its per-hole table),
  add the course to the table in the top-level README, keep research/NOTES.md current.

## 10. Rules

* Commit `courses/<slug>/` (course.toml, features, research, README): it is the course's source. `data/`, `build/`
  and `output/` are not tracked.
* An engine change (`scripts/`, `regions/`) is tested first, keeps course facts out of the code, and must rebuild
  Westmount to `courses/westmount/fingerprint.json` (`scripts/fingerprint.py check`) or explain each difference.

## Definition of done

- [ ] Research verified; course.toml complete (check_course reports nothing missing); leaf flags match the data.
- [ ] Data fetched; the photo registered to the LiDAR (`[imagery] shift` measured).
- [ ] Full build OK; QA rounds 1 and 2 applied; problems that recurred across holes fixed in the engine with tests.
- [ ] `pytest --course <slug> tests/test_course.py` green, with only documented `[tests] known_tee_gaps`, each with a
      reason in research/NOTES.md.
- [ ] Viewer checked: every hole's tee and green, a bunker lip, water, rough grass.
- [ ] GSPro package in `output/<slug>/gspro/`: `heightmap_4097.raw`, `outer_heightmap_4097.raw`, overlays,
      `course_opcd.svg`, `course_meshes.fbx` (+ `fbx_manifest.json`), `structures.fbx`, `backdrop.fbx`,
      `tree_prefabs.fbx/.json`, `trees.csv`, `grass_3dg.json`, `greenkeeper.json`, `terrain.json`, the Unity helper.
- [ ] `courses/<slug>/README.md` written and the course added to the top-level README.

Rough timings for an 18-hole course on a laptop: research about 1 h; downloads 0.5-1.5 h (the first backdrop photo
can take an hour on a slow server); first build 0.5-1 h; two QA rounds with rebuilds about 3-4 h.

## Troubleshooting

* **Blender crashes at start on macOS** in a sandboxed shell (it opens a Metal device even with `-b`): run the `fbx`
  step outside the sandbox.
* **Overpass is down** (HTTP 500 / 504): fetch_data falls back to the OSM API.
* **An image server is slow or times out**: the downloads are chunked and retried; rerun the step.
* **The course is wider than about 1.85 km**: the build extent no longer fits the 2048 m terrain square;
  check_course says so.
* **Changing `[osm]`, `[frame]` or a source** takes effect on the next run of the steps that read it; rebuild from the
  first step that reads the changed input (`build_all.py <step> ...`).
