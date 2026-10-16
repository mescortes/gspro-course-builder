# Contributing

How courses and engine changes get into `main`. The repository owner ([@mescortes](https://github.com/mescortes))
reviews and merges every pull request. So far the engine has built courses in Ontario and Northern California only. A
course somewhere else will find new problems. When it does, write them down in the PR.

## Read first

1. [README.md](README.md): what the engine makes, the courses so far, the repository layout.
2. [docs/PLAYBOOK.md](docs/PLAYBOOK.md): building a course step by step. §0 covers setup on macOS, on Linux and in a
   Claude cloud session, and the multi-agent workflows (research, QA) with what they cost.
3. The course folder closest to yours: [courses/brambles/](courses/brambles/) for California (USGS 3DEP LiDAR, NAIP
   photo, no OSM), or [courses/westmount/](courses/westmount/) for a finished course with its README and QA verdicts.
4. [TODO.md](TODO.md): engine problems QA has found and left open. Read [docs/LESSONS.md](docs/LESSONS.md) when the
   engine does something you don't expect.

With Claude Code, "read instructions.md and build course XYZ" starts from the playbook.

## Branches

* **One branch per course**, named after its slug (`brambles`, `whistle-bear`, `deer-ridge`), cut from `main`. It
  carries only `courses/<slug>/`. When `main` moves, merge it into the course branch (`git merge origin/main`)
  rather than rebasing.
* **Engine fixes get their own branch and PR**, named for the fix (`osm-golf-pitch`, `mesh-memory`), even when one
  course found them. Write the test first: it fails before the fix and passes after. A course that needs the fix is
  stacked on it: merge the engine branch into the course branch and point the course PR at the engine branch. It
  moves to `main` once the fix merges. Deer Ridge ([#12]) was stacked on its two fixes ([#11]) this way.
* **Regions** (`regions/<name>.toml`) are shared by every course in the area. A new region, or a change to one, goes
  in an engine PR. The unit tests check every region against `scripts/region_spec.py`.
* Nobody pushes to `main`. It moves only by merged PRs.

## Pull requests and commits

* Open every PR as a **draft**.
* PRs are **merged with a merge commit, never squashed or rebased**. Branches are stacked (a course on its engine
  fix, one engine fix on another), and squashing rewrites the commits the branch above is built on.
* **No AI attribution** anywhere in commit messages or PR bodies: no "Claude", no `Co-Authored-By` trailer, no
  "Generated with Claude Code" line. Claude Code adds them by default. Turn them off in `~/.claude/settings.json`:

  ```json
  { "attribution": { "commit": "", "pr": "", "sessionUrl": false } }
  ```

  A cloud session doesn't read that file: it reads only the repository's `.claude/settings.json`, and this
  repository has none yet. Check each commit message and PR body before you push.
* Commit each step once it works. The subject line says what changed in plain words. A course commit starts with
  the course's name ("Brambles: QA round 2 overrides (...)").
* `data/`, `build/` and `output/` are not tracked. Commit everything the course needs in `courses/<slug>/`,
  including the OSM snapshot.

## What a course PR reports

Follow [#7] (Brambles) and [#9] (Whistle Bear):

* **Data**: the LiDAR project and its flight date (leaf-on or leaf-off), the photo (source, date, resolution,
  bands), the backdrop DEM, what OSM maps, where the scorecard came from, and what changed on the course since the
  LiDAR was flown.
* **Registration**: the `[imagery] shift` and how many bunkers `measure_registration.py` used.
* **QA**: which rounds ran, how many override features each added, what they fixed, and the verifier scores.
* **Course limits** in `course.toml [tests]` and why each is needed. Give each `known_tee_gaps` entry its reason in
  `research/NOTES.md`.
* **Verification**: the result of `pytest --course <slug> tests/test_course.py` (passed, failed, skipped; 4 tests are
  Westmount-only and skip elsewhere), the unit tests, and the build's peak memory with its step and the machine.
  `build_all.py` prints each step's peak.
* **Not done**: what is left for the course, and problems seen on several holes. Those belong to the engine, so
  add them to [TODO.md](TODO.md).

## What an engine PR reports

Follow [#8], [#10] and [#11]:

* **Why**: the course and the symptom that exposed the problem.
* **What changed**, and the tests that failed before the fix.
* **Effect**: before and after figures for each course you rebuilt.
* **Verification**: the unit tests, `test_course` for each rebuilt course, and the Westmount fingerprint check with
  the machine it ran on. The golden fingerprint reproduces exactly only on the owner's Mac.
  [docs/PLAYBOOK.md §10](docs/PLAYBOOK.md#10-rules) says what to run on any other machine and how to read the
  differences. The owner re-runs the Westmount check on that Mac before merging.

[#7]: https://github.com/mescortes/gspro-course-builder/pull/7
[#8]: https://github.com/mescortes/gspro-course-builder/pull/8
[#9]: https://github.com/mescortes/gspro-course-builder/pull/9
[#10]: https://github.com/mescortes/gspro-course-builder/pull/10
[#11]: https://github.com/mescortes/gspro-course-builder/pull/11
[#12]: https://github.com/mescortes/gspro-course-builder/pull/12
