"""NRCan CanElevation point clouds: 1 km COPC tiles on S3, one folder per acquisition project (Open Government Licence
- Canada / the province's). Tile names: 1km<zone><E/100 m, 4 digits><N/100 m, 5 digits><suffix>.copc.laz, at the tile's
south-west corner.

  [sources.lidar]
  provider = "nrcan_copc"
  zone = 17
  projects = [{ folder = "ON/Lake_Erie_2018", suffix = "2018LLAKEERIE" }, ...]

A tile is taken from the first project folder that has it (HTTP HEAD), so a course on the seam of two projects gets
both. Folder names do not tell the flight date (Deer Ridge's Lake_Erie_2018 tiles hold 2017-11-21 points): read the
GPS times.
"""
import math
from sources import http
from sources.http import requests  # noqa: F401 (tests patch requests.head through here)

BUCKET = "https://canelevation-lidar-point-clouds.s3.ca-central-1.amazonaws.com/pointclouds_nuagespoints"


def tiles(ext, margin=15.0):
    """Federal 1 km tile names (SW corner / 100 m) intersecting the extent + margin."""
    e0 = int(math.floor((ext["xmin"] - margin) / 1000)); e1 = int(math.floor((ext["xmax"] + margin) / 1000))
    n0 = int(math.floor((ext["ymin"] - margin) / 1000)); n1 = int(math.floor((ext["ymax"] + margin) / 1000))
    return [(e * 10, n * 10) for e in range(e0, e1 + 1) for n in range(n0, n1 + 1)]


def url(spec, project, e, n):
    return f"{BUCKET}/{project['folder']}/1km{spec['zone']}{e:04d}{n:05d}{project['suffix']}.copc.laz"


def fetch(spec, ext, out, margin=15.0):
    """Download every tile reaching the extent into `out`; returns the number of tiles."""
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for e, nn in tiles(ext, margin):
        for p in spec["projects"]:
            u = url(spec, p, e, nn)
            size = http.size(u)
            if size:
                http.download(u, out / u.split("/")[-1], size); n += 1
                break
        else:
            print(f"lidar: no tile {e} {nn} in", ", ".join(p["folder"] for p in spec["projects"]), flush=True)
    return n
