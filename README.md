# Course-builder skeleton (snapshot 2026-10-11)

A **plain copy** of the reusable core of the MountainGate build, taken while GSPro cosmetics (task #2) was in
progress. Nothing has been refactored, so the files still carry MountainGate's settings. To start a new course:

1. Copy this folder to a new project and create the venv (see the main README's "Rebuilding" section).
2. Follow `instructions.md`. §3 lists every file with course-specific constants: `scripts/config.py`,
   `fetch_data.py` (`LIDAR_PROJECT`), `fetch_backdrop.py` (`URLS`), `export_fbx_blender.py` (`model_origin`),
   `hole_data.py` (`AIM_OVERRIDES`), `make_views.py`, titles, and course-specific tests in `tests/test_course.py`.
3. `features/overrides/` starts empty: the QA workflows (`workflows/hole_qa_round*.js`) fill it.

Not included (one-off debugging or MountainGate-only):

* scripts: `osm_summary.py`, `preview_trees.py`, `qa_trees.py`, `qa_rasters.py`, `render_blender.py`;
* data: the data, research and output folders.

Before reusing, also pull in later fixes from the main repo: this copy predates the rest of task #2 and task #3.
