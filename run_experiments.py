"""Flood mapping of Cyclone Ditwah (Sri Lanka, 30 Nov 2025) with Sentinel-2 NDWI,
validated against the Copernicus EMS delineation EMSR851 AOI02 (Kelani Ganga).

Usage: python run_experiments.py   (input files in data/, outputs written to results/)
"""
import csv
import itertools
import math
import os

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.windows import Window
from scipy import ndimage

DATA, OUT = "data", "results"
POST = [f"{DATA}/postflood_202511/T44NLN_20251130T050049_{b}_10m.jp2" for b in ("B03", "B08")]  # flood image
PRE = [f"{DATA}/preflood_202401/T44NLN_20240125T050101_{b}_10m.jp2" for b in ("B03", "B08")]   # dry-season reference (EMS also used Jan 2024)
EMS_FLOOD = f"{DATA}/EMS/EMSR851_AOI02_DEL_PRODUCT_observedEventA_v1.shp"
EMS_AOI = f"{DATA}/EMS/EMSR851_AOI02_DEL_PRODUCT_areaOfInterestA_v1.shp"
THRESHOLDS = [0.0, -0.05, -0.10, -0.15, -0.20]
MIN_PATCH = [0, 10, 25, 50]    # pixels, 1 px = 100 m2
FINAL = dict(thr=-0.10, closing=True, min_patch=25)


def read(path, window):
    with rasterio.open(path) as src:
        return src.read(1, window=window).astype("float32")


def ndwi(paths, window):
    green, nir = [read(p, window) for p in paths]
    nodata = (green == 0) | (nir == 0)
    green, nir = np.clip(green - 1000, 1, None), np.clip(nir - 1000, 1, None)  # L2A offset
    out = (green - nir) / (green + nir)
    out[nodata] = np.nan
    return out


def flood_map(post, pre_water, thr, closing, min_patch):
    flood = (post > thr) & ~pre_water
    if closing:
        flood = ndimage.binary_closing(flood, np.ones((3, 3))) & ~pre_water
    if min_patch:
        labels, _ = ndimage.label(flood, np.ones((3, 3)))
        flood &= np.bincount(labels.ravel())[labels] >= min_patch
    return flood


def scores(flood, ems, valid):
    tp = np.sum(flood & ems & valid)
    fp = np.sum(flood & ~ems & valid)
    fn = np.sum(~flood & ems & valid)
    return dict(IoU=tp / (tp + fp + fn), F1=2 * tp / (2 * tp + fp + fn), Precision=tp / (tp + fp),
                Recall=tp / (tp + fn), Flood_km2=(tp + fp) / 1e4, Extra_km2=fp / 1e4, Missed_km2=fn / 1e4)


def main():
    os.makedirs(OUT, exist_ok=True)

    # read only the part of the Sentinel-2 tile that covers the EMS area
    with rasterio.open(POST[0]) as src:
        crs = src.crs
        aoi = gpd.read_file(EMS_AOI).to_crs(crs)
        left, bottom, right, top = aoi.total_bounds
        c0, r0 = ~src.transform * (left, top)
        c1, r1 = ~src.transform * (right, bottom)
        c0, r0 = max(math.floor(c0), 0), max(math.floor(r0), 0)
        c1, r1 = min(math.ceil(c1), src.width), min(math.ceil(r1), src.height)
        window = Window(c0, r0, c1 - c0, r1 - r0)
        transform = src.window_transform(window)
    shape = (window.height, window.width)

    def burn(gdf):
        return rasterize(gdf.geometry, out_shape=shape, transform=transform).astype(bool)

    post = ndwi(POST, window)
    pre_water = ndwi(PRE, window) > 0
    ems = burn(gpd.read_file(EMS_FLOOD).to_crs(crs))
    valid = burn(aoi) & ~np.isnan(post)  # inside the EMS area and covered by the image
    print(f"evaluated area {valid.sum() / 1e4:.1f} km2, EMS flood {(ems & valid).sum() / 1e4:.1f} km2")

    rows = []
    no_pre = np.zeros(shape, bool)
    for remove_pre, thr, closing, min_patch in itertools.product([False, True], THRESHOLDS, [False, True], MIN_PATCH):
        flood = flood_map(post, pre_water if remove_pre else no_pre, thr, closing, min_patch)
        rows.append(dict(remove_pre=remove_pre, threshold=thr, closing=closing, min_patch=min_patch,
                         **scores(flood, ems, valid)))

    with open(os.path.join(OUT, "results.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({k: round(v, 4) if isinstance(v, float) else v for k, v in r.items()} for r in rows)

    print("remove_pre   thr  closing  min_patch    IoU     F1   prec    rec")
    for r in sorted(rows, key=lambda r: -r["IoU"])[:10]:
        print(f"{r['remove_pre']!s:10} {r['threshold']:5.2f}  {r['closing']!s:7}  {r['min_patch']:9}  "
              f"{r['IoU']:.3f}  {r['F1']:.3f}  {r['Precision']:.3f}  {r['Recall']:.3f}")

    flood = flood_map(post, pre_water, **FINAL)
    print("final method:", {k: round(float(v), 3) for k, v in scores(flood, ems, valid).items()})
    profile = dict(driver="GTiff", width=shape[1], height=shape[0], count=1, dtype="uint8",
                   crs=crs, transform=transform, nodata=255, compress="deflate")
    for name, arr in [("flood_final.tif", flood), ("compare_final.tif", flood + 2 * ems)]:
        with rasterio.open(os.path.join(OUT, name), "w", **profile) as dst:
            dst.write(np.where(valid, arr, 255).astype("uint8"), 1)


if __name__ == "__main__":
    main()