"""Downloaded files on disk: written atomically, and recorded with the request they were made from.

A download is written to <file>.part and renamed into place only once complete, so a crash, a Ctrl-C or a truncated
transfer never leaves a file that a rerun trusts because it exists.

<file>.source.json records what the file was made from (provider, URL, extent, resolution, bands ...). A rerun after
course.toml changed compares the two and refetches, or stops naming the setting, instead of silently building on
the old file. A file fetched before records existed has none: it is accepted as it is (and recorded by its fetch).

LiDAR tiles are recorded together, in <folder>/tiles.json, which config.lidar_tiles() checks the folder against.
"""
import json, os
from contextlib import contextmanager
from pathlib import Path

TILES = "tiles.json"


def part(dst):
    return Path(dst).with_name(Path(dst).name + ".part")


@contextmanager
def atomic(dst):
    """A temporary path next to `dst` to write: it replaces `dst` when the block ends, and is removed when the block
    raises (KeyboardInterrupt included), leaving any earlier `dst` as it was."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = part(dst)
    try:
        yield tmp
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, dst)


def write_text(dst, text):
    with atomic(dst) as tmp:
        tmp.write_text(text)


def write_bytes(dst, data):
    with atomic(dst) as tmp:
        tmp.write_bytes(data)


def normal(obj):
    """`obj` as it reads back from JSON (tuples become lists), so that a request compares equal to its record."""
    return json.loads(json.dumps(obj))


def record_path(dst):
    return Path(dst).with_name(Path(dst).name + ".source.json")


def write_record(dst, request):
    write_text(record_path(dst), json.dumps(normal(request), indent=1) + "\n")


def read_record(dst):
    """The request `dst` was made from; None when it has no record (fetched before records existed) or an unreadable one."""
    try:
        return json.loads(record_path(dst).read_text())
    except (FileNotFoundError, ValueError):
        return None


def changes(dst, request, ignore=()):
    """[(key, recorded, now)] for every value of `request` that differs from `dst`'s record; None without a record."""
    rec = read_record(dst)
    if rec is None:
        return None
    req = normal(request)
    return [(k, rec.get(k), req.get(k)) for k in sorted(set(rec) | set(req))
            if k not in ignore and rec.get(k) != req.get(k)]


def write_tiles(folder, spec, ext, names):
    """Record the LiDAR tiles a fetch asked for (folder/tiles.json: the [sources.lidar] table, the extent, the file
    names) and move every other *.laz of the folder into folder/unused/. A switched project (or a reordered NRCan
    folder list) used to leave the old tiles next to the new ones, and the build streamed both flights."""
    folder = Path(folder)
    keep = sorted(set(names))
    for p in sorted(folder.glob("*.laz")):
        if p.name not in keep:
            (folder / "unused").mkdir(exist_ok=True)
            os.replace(p, folder / "unused" / p.name)
            print(f"lidar: {p.name} is not a tile of this fetch: moved to {folder / 'unused'}", flush=True)
    write_text(folder / TILES, json.dumps(normal(dict(spec=spec, extent=ext, tiles=keep)), indent=1) + "\n")
