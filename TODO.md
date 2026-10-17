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
* Small false native blobs appear on mown rough, and holes.json lists some of them as hazards. Seen on Whistle Bear
  holes 5, 10 and 12-15, QA rounds 1-2.
* Bare soil with 0.1 m of relief passes the bunker hollow test. Seen on Brambles, QA round 2.
* The clubhouse road and parking are modelled as rough, and QA overrides have no road surface to correct them with.
  Seen on Brambles, QA round 2 and [#7].
* `trace_paths.py` traces cart paths along shadows, forest edges and fences. Seen on Whistle Bear, QA rounds 1-2.
* Classifier greens grow fingers along mown approach strips, and dense conifer shadows take the fairway class off
  mown turf. Seen on Deer Ridge, QA rounds 1-2.

## Tees, pins and aim points

* Tee pads take in the banks around their decks, and markers are placed on deck rims. Seen on Brambles, QA round 2.
* The middle vertices of OSM hole lines are kept as aim points on straight holes. Seen on Whistle Bear, QA rounds 1-2
  (holes 3, 6, 12 and 18 in round 2, each under 0.3 yd).
* Front pin yardages are measured from a bunker cut-in. Seen on Whistle Bear holes 7, 10 and 16, QA rounds 1-2.
* The practice green behind the 18th green gets two of the pins. Seen on Brambles, [#7].

## Water

* A water body cut in reaches is flat at each band's lower end, so a reach whose shoreline is level sits up to
  `water_step` (0.3 m) below it: Whistle Bear's upper pond (OSM way 936553651) is at 307.73 m under LiDAR water at
  308.05 m, with 0.3 m of bank showing round it. Measured on Whistle Bear when its cascade cut was fixed.
* A high bank along one side of a wide river lifts the water beside it, and the reach is cut lengthwise: Deer Ridge's
  Grand River north of the island (E 546900-547000) has a 2,761 m2 reach at 280.77 m beside one at 280.48 m, 0.3 m
  above the LiDAR water. The shoreline's local level comes from one bank where the river is wider than 60 m.
  Measured on Deer Ridge when the cascade cut was fixed.

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
