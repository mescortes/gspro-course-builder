# Engine TODO

These problems were seen on several holes of a course during QA and left for the engine rather than fixed with
overrides. Each item names the course where it was seen and where that is recorded. Some may have been fixed since,
so check an item against the current engine before starting on it. Fix it test first, on its own branch
([CONTRIBUTING.md](CONTRIBUTING.md)). Open items for a single course are in that course's folder
([courses/westmount/TODO.md](courses/westmount/TODO.md)).

## Surfaces

* Dry tan meadow and bare soil are classified as fairway or native. Seen on Brambles (NAIP 0.6 m, summer, leaf-on),
  QA round 2.
* Tree shadows are classified as water. Seen on Brambles, QA round 2.
* False green and fringe appear under forest canopy (holes 17, 18) and on a green metal roof. Seen on Whistle Bear,
  QA round 1, before [#11] turned classifier green more than 15 m off the course outline into rough.
* Small false native blobs appear on mown rough. Seen on Whistle Bear holes 13-15, QA round 1.
* Bare soil with 0.1 m of relief passes the bunker hollow test. Seen on Brambles, QA round 2.
* The clubhouse road and parking are modelled as rough, and QA overrides have no road surface to correct them with.
  Seen on Brambles, QA round 2 and [#7].
* `trace_paths.py` traces cart paths along shadows and forest edges. Seen on Whistle Bear, QA round 1.

## Tees, pins and aim points

* Tee pads take in the banks around their decks, and markers are placed on deck rims. Seen on Brambles, QA round 2.
* The middle vertices of OSM hole lines are kept as aim points on straight holes. Seen on Whistle Bear, QA round 1.
* Front pin yardages are measured from a bunker cut-in. Seen on Whistle Bear holes 7 and 10, QA round 1.
* The practice green behind the 18th green gets two of the pins. Seen on Brambles, [#7].

## GSPro package and mesh

* Bunker islands are drawn as sand in the OPCD SVG (`course_opcd.svg`). `export_gspro.svg()` draws each surface as
  its filled outline, without its holes. Seen on Whistle Bear hole 5, QA round 1.
* The mesh step prints a Triangle "ran out of precision" message on Brambles, though the mesh tests pass. Recorded
  in [#7].

## Regions and platforms

* `southern_california` has no palm model. Palms land in one of its five archetypes, and course buildings keep the
  engine's grey roof tiles (see the region file's header). Its turf tint, buildings, grass, backdrop and sky are first
  estimates, to be tuned on the region's first course.
* A full 18-hole build's memory has not been measured on Linux yet ([docs/PLAYBOOK.md](docs/PLAYBOOK.md) §0).

The QA findings are recorded in `courses/brambles/research/qa_brief.md` and `courses/whistle-bear/research/qa_brief.md`
("Left for the engine") and in the PRs' "Known issues" sections.

[#7]: https://github.com/mescortes/gspro-course-builder/pull/7
[#11]: https://github.com/mescortes/gspro-course-builder/pull/11
