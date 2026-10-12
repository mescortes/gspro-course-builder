"""Build terrain rasters from the USGS 2025 LiDAR point cloud, tile by tile.

Pass 1 streams every LAZ file once: ground returns are bucketed into processing tiles (C.TILE m + margin);
first returns update a global 0.5 m DSM (max z); ground hits update global count / intensity grids.
Pass 2 triangulates each tile's ground returns (TIN) and writes the tile interior into the global DEM.

Outputs (GeoTIFF, EPSG:32611) in build/:
  dem.tif        bare-earth elevation (TIN of ground returns, de-noised), DEM_RES spacing
  dem_raw.tif    TIN without smoothing (for QA)
  dsm.tif        first-return surface (max z per cell), 0.5 m
  bdsm.tif       building-class (6) surface (max z per cell, NaN without building returns), 0.5 m
  chm.tif        canopy/object height above ground (dsm - dem), 0.5 m
  intensity.tif  mean ground-return intensity, DEM_RES spacing (NaN where no ground hit)
  ground_count.tif  ground returns per DEM cell
"""
import sys, time
import numpy as np
import laspy
import rasterio
from rasterio.transform import from_origin
from scipy.spatial import Delaunay, cKDTree
from scipy.interpolate import LinearNDInterpolator
from scipy import ndimage

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import config as C

MARGIN = 15.0        # extent margin for reading points
TILE_MARGIN = 12.0   # overlap around each processing tile for the TIN


def grid_spec(ext, res):
    W = int(round((ext["xmax"] - ext["xmin"]) / res))
    H = int(round((ext["ymax"] - ext["ymin"]) / res))
    T = from_origin(ext["xmin"], ext["ymax"], res, res)
    xc = ext["xmin"] + (np.arange(W) + 0.5) * res
    yc = ext["ymax"] - (np.arange(H) + 0.5) * res
    return W, H, T, xc, yc


def write(path, arr, T, nodata=np.nan):
    arr = np.asarray(arr, np.float32)
    with rasterio.open(path, "w", driver="GTiff", width=arr.shape[1], height=arr.shape[0], count=1,
                       dtype="float32", crs=C.CRS, transform=T, nodata=nodata, compress="deflate",
                       predictor=3, tiled=True, BIGTIFF="IF_SAFER") as d:
        d.write(arr, 1)
    print("wrote", path, arr.shape, flush=True)


def tiles(ext):
    nx = int(np.ceil((ext["xmax"] - ext["xmin"]) / C.TILE)); ny = int(np.ceil((ext["ymax"] - ext["ymin"]) / C.TILE))
    for j in range(ny):
        for i in range(nx):
            x0 = ext["xmin"] + i * C.TILE; y0 = ext["ymin"] + j * C.TILE
            yield (i, j), dict(xmin=x0, ymin=y0, xmax=min(x0 + C.TILE, ext["xmax"]), ymax=min(y0 + C.TILE, ext["ymax"]))


def surface_returns(cls, rn):
    """(first, building) masks: non-noise first returns feed dsm.tif; every building-class (6) return feeds bdsm.tif,
    the roof surface without the crowns of overhanging trees."""
    first = (rn == 1) & (cls != 7) & (cls != 18)
    return first, cls == 6


def pass1(ext, res):
    """Stream LAZ once. Returns ground buckets per tile + global count/intensity grids + DSM."""
    W, H, T, _, _ = grid_spec(ext, res)
    W2, H2, T2, _, _ = grid_spec(ext, 0.5)
    cnt = np.zeros(H * W, np.int32)
    isum = np.zeros(H * W, np.float32)
    dsm = np.full(H2 * W2, -np.inf, np.float32)
    bdsm = np.full(H2 * W2, -np.inf, np.float32)
    tl = list(tiles(ext))
    buckets = {k: [] for k, _ in tl}
    nx = int(np.ceil((ext["xmax"] - ext["xmin"]) / C.TILE))
    for f in C.LIDAR_TILES:
        with laspy.open(f) as r:
            h = r.header
            if h.maxs[0] < ext["xmin"] - MARGIN or h.mins[0] > ext["xmax"] + MARGIN or \
               h.maxs[1] < ext["ymin"] - MARGIN or h.mins[1] > ext["ymax"] + MARGIN:
                continue
            t0 = time.time(); n_in = 0
            for ch in r.chunk_iterator(5_000_000):
                x = ch.x.array * h.scales[0] + h.offsets[0]
                y = ch.y.array * h.scales[1] + h.offsets[1]
                m = (x >= ext["xmin"] - MARGIN) & (x <= ext["xmax"] + MARGIN) & (y >= ext["ymin"] - MARGIN) & (y <= ext["ymax"] + MARGIN)
                if not m.any():
                    continue
                x, y = x[m], y[m]
                z = (ch.z.array * h.scales[2] + h.offsets[2])[m]
                cls = np.asarray(ch.classification)[m]
                rn = np.asarray(ch.return_number)[m]
                inten = np.asarray(ch.intensity)[m].astype(np.float32)
                n_in += len(x)
                g = cls == 2
                gx, gy, gz, gi = x[g], y[g], z[g], inten[g]
                # global ground count / intensity
                col = np.floor((gx - ext["xmin"]) / res).astype(np.int64)
                row = np.floor((ext["ymax"] - gy) / res).astype(np.int64)
                inb = (col >= 0) & (col < W) & (row >= 0) & (row < H)
                lin = row[inb] * W + col[inb]
                if len(lin):
                    lo = lin.min()
                    cnt[lo:lo + (lin.max() - lo + 1)] += np.bincount(lin - lo).astype(np.int32)
                    isum[lo:lo + (lin.max() - lo + 1)] += np.bincount(lin - lo, weights=gi[inb]).astype(np.float32)
                # tile buckets (with overlap) for the TIN
                ti0 = np.floor((gx - TILE_MARGIN - ext["xmin"]) / C.TILE).astype(int)
                ti1 = np.floor((gx + TILE_MARGIN - ext["xmin"]) / C.TILE).astype(int)
                tj0 = np.floor((gy - TILE_MARGIN - ext["ymin"]) / C.TILE).astype(int)
                tj1 = np.floor((gy + TILE_MARGIN - ext["ymin"]) / C.TILE).astype(int)
                pts = np.c_[gx, gy, gz]
                for di in (0, 1):
                    for dj in (0, 1):
                        ti = ti0 if di == 0 else ti1; tj = tj0 if dj == 0 else tj1
                        sel = np.ones(len(gx), bool)
                        if di == 1:
                            sel &= ti1 != ti0
                        if dj == 1:
                            sel &= tj1 != tj0
                        if not sel.any():
                            continue
                        keys = tj[sel] * nx + ti[sel]
                        sp = pts[sel]
                        order = np.argsort(keys, kind="stable"); keys = keys[order]; sp = sp[order]
                        bnd = np.flatnonzero(np.r_[True, keys[1:] != keys[:-1], True])
                        for a, b in zip(bnd[:-1], bnd[1:]):
                            k = int(keys[a]); kj, ki = divmod(k, nx)
                            if (ki, kj) in buckets:
                                buckets[(ki, kj)].append(sp[a:b])
                # DSM from first returns (non-noise)
                f1, b6 = surface_returns(cls, rn)
                cb = np.floor((x[b6] - ext["xmin"]) / 0.5).astype(np.int64)
                rb = np.floor((ext["ymax"] - y[b6]) / 0.5).astype(np.int64)
                okb = (cb >= 0) & (cb < W2) & (rb >= 0) & (rb < H2)
                np.maximum.at(bdsm, rb[okb] * W2 + cb[okb], z[b6][okb].astype(np.float32))
                c2 = np.floor((x[f1] - ext["xmin"]) / 0.5).astype(np.int64)
                r2 = np.floor((ext["ymax"] - y[f1]) / 0.5).astype(np.int64)
                ok = (c2 >= 0) & (c2 < W2) & (r2 >= 0) & (r2 < H2)
                np.maximum.at(dsm, r2[ok] * W2 + c2[ok], z[f1][ok].astype(np.float32))
            print(f"  {f.name}: {n_in:,} pts in {time.time() - t0:.0f}s", flush=True)
    return buckets, cnt.reshape(H, W), isum.reshape(H, W), dsm.reshape(H2, W2), bdsm.reshape(H2, W2)


def filter_ground(P):
    """Drop isolated ground returns that deviate from a robust local surface (vegetation leaks / pits)."""
    gx, gy, gz = P[:, 0], P[:, 1], P[:, 2]
    tree = cKDTree(np.c_[gx, gy])
    _, idx = tree.query(np.c_[gx, gy], k=16, distance_upper_bound=1.5)
    valid = idx < len(gx)
    nz = np.where(valid, gz[np.minimum(idx, len(gx) - 1)], np.nan)
    med = np.nanmedian(nz, axis=1)
    mad = np.nanmedian(np.abs(nz - med[:, None]), axis=1)
    dev = np.abs(gz - med)
    return ~((dev > 0.25) & (dev > 4 * 1.4826 * np.maximum(mad, 0.01)))


def main(ext=C.CORE, res=C.DEM_RES):
    t0 = time.time()
    buckets, cnt, isum, dsm, bdsm = pass1(ext, res)
    W, H, T, xc, yc = grid_spec(ext, res)
    write(C.BUILD / "ground_count.tif", cnt, T, nodata=-1)
    inten = np.where(cnt > 0, isum / np.maximum(cnt, 1), np.nan).astype(np.float32)
    del isum
    write(C.BUILD / "intensity.tif", inten, T)
    del inten
    dem_raw = np.full((H, W), np.nan, np.float32)
    removed = 0
    for (i, j), te in tiles(ext):
        parts = buckets.pop((i, j))
        if not parts:
            continue
        P = np.concatenate(parts)
        P = np.unique(P, axis=0)  # a point may be bucketed twice through the overlap logic
        keep = filter_ground(P); removed += (~keep).sum(); P = P[keep]
        c0 = int(round((te["xmin"] - ext["xmin"]) / res)); c1 = int(round((te["xmax"] - ext["xmin"]) / res))
        r0 = int(round((ext["ymax"] - te["ymax"]) / res)); r1 = int(round((ext["ymax"] - te["ymin"]) / res))
        ox, oy = te["xmin"], te["ymin"]
        tri = Delaunay(np.c_[P[:, 0] - ox, P[:, 1] - oy])
        XX, YY = np.meshgrid(xc[c0:c1] - ox, yc[r0:r1] - oy)
        dem_raw[r0:r1, c0:c1] = LinearNDInterpolator(tri, P[:, 2])(XX, YY)
        print(f"  tile {i},{j}: {len(P):,} ground pts", flush=True)
    print(f"ground filter removed {removed:,}", flush=True)
    if np.isnan(dem_raw).any():
        nanm = np.isnan(dem_raw)
        idx = ndimage.distance_transform_edt(nanm, return_distances=False, return_indices=True)
        dem_raw = dem_raw[tuple(idx)]
        del idx
    write(C.BUILD / "dem_raw.tif", dem_raw, T)

    # De-noise: light Gaussian (sigma 0.3 m) everywhere; stronger where sampling was sparse (TIN facets
    # under canopy / buildings) so long flat facets do not show.
    dist_to_hit = ndimage.distance_transform_edt(cnt == 0).astype(np.float32) * res
    light = ndimage.gaussian_filter(dem_raw, 0.30 / res)
    heavy = ndimage.gaussian_filter(dem_raw, 1.25 / res)
    w = np.clip((dist_to_hit - 0.5) / 2.0, 0, 1)
    del dist_to_hit
    dem = (1 - w) * light + w * heavy
    del light, heavy, w
    write(C.BUILD / "dem.tif", dem, T)

    W2, H2, T2, _, _ = grid_spec(ext, 0.5)
    dem2 = dem.reshape(H2, 2, W2, 2).mean(axis=(1, 3))
    empty = ~np.isfinite(dsm)
    dsm[empty] = dem2[empty]
    chm = np.clip(dsm - dem2, 0, None)
    med = ndimage.median_filter(chm, 3)
    chm = np.where(chm - med > 6, med, chm)  # single-cell spikes (birds / wires)
    write(C.BUILD / "dsm.tif", dsm, T2)
    write(C.BUILD / "bdsm.tif", np.where(np.isfinite(bdsm), bdsm, np.nan).astype(np.float32), T2)
    write(C.BUILD / "chm.tif", chm, T2)
    print(f"rasters done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
