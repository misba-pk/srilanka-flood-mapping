"""Convert the final flood map and the EMS layers to GeoJSON for the web map (web/index.html).

Usage: python make_webmap.py   (run after run_experiments.py)
"""
import os

import geopandas as gpd
import rasterio
from rasterio.features import shapes
from shapely.geometry import shape

DATA, OUT = "data", "web/data"
EMS_FLOOD = f"{DATA}/EMS/EMSR851_AOI02_DEL_PRODUCT_observedEventA_v1.shp"
EMS_AOI = f"{DATA}/EMS/EMSR851_AOI02_DEL_PRODUCT_areaOfInterestA_v1.shp"
SIMPLIFY = 5  # metres, keeps the files small

os.makedirs(OUT, exist_ok=True)

with rasterio.open("results/flood_final.tif") as src:
    flood = src.read(1)
    polygons = [shape(g) for g, v in shapes(flood, mask=flood == 1, transform=src.transform)]
    crs = src.crs

flood = gpd.GeoDataFrame(geometry=polygons, crs=crs)
flood["area_ha"] = (flood.area / 1e4).round(2)
ems = gpd.read_file(EMS_FLOOD)[["geometry"]].to_crs(crs)

for name, gdf in [("flood", flood), ("ems_flood", ems), ("aoi", gpd.read_file(EMS_AOI)[["geometry"]])]:
    gdf = gdf.to_crs(crs)
    gdf["geometry"] = gdf.simplify(SIMPLIFY)
    gdf.to_crs(4326).to_file(f"{OUT}/{name}.geojson", driver="GeoJSON", COORDINATE_PRECISION=6)
    print(f"{name}.geojson: {len(gdf)} polygons, {os.path.getsize(f'{OUT}/{name}.geojson') / 1e6:.1f} MB")