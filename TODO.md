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
* Every semirough polygon carries hole 99, including the rings round fairways, though `vectorize` says fringe and
  semirough adopt the hole they surround. Seen on Deer Ridge, QA rounds 1-2.
* Small OSM fairways (collection areas and drop zones under 150 m2) are dropped, classifier greens grow fingers along
  mown approach strips, and dense conifer shadows take the fairway class off mown turf. Seen on Deer Ridge, QA rounds
  1-2.

## OSM features

* A river mapped as a multipolygon relation whose snapshot has geometry for only some members is never polygonised,
  so it is built as rough. Seen on Deer Ridge: the Grand River (relation 222351) has geometry for 5 of its 47 members.
* A wetland lateral hazard (`golf=lateral_water_hazard` + `natural=wetland`) is carved as an open water plane 0.3-1.5 m
  below the reed ground, so it looks like a pond (it plays right as a penalty area). Seen on Deer Ridge (relation
  11198160).
* OSM `highway=cycleway` trails are not modelled. Seen on Deer Ridge.

## Tees, pins and aim points

* Tee pads take in the banks around their decks, and markers are placed on deck rims. Seen on Brambles, QA round 2.
* OSM forward tees that sit off the `golf=hole` line are assigned to hole 99 instead of the nearest hole's tee set.
  Seen on Deer Ridge, QA rounds 1-2.
* Markers of a set with no deck (Deer Ridge's Copper) go on the back tee's first leg at the card distance, whatever
  the surface or hazards there: a lake bank, rough, beside bunkers. Seen on Deer Ridge, QA rounds 1-2.
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

The QA findings are recorded in the "Left for the engine" lists of `courses/<slug>/research/qa_brief.md` (Brambles,
Whistle Bear, Deer Ridge) and in the course PRs' "Known issues" sections.

[#7]: https://github.com/mescortes/gspro-course-builder/pull/7
[#11]: https://github.com/mescortes/gspro-course-builder/pull/11
