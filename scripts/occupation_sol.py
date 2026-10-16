"""Occupation du sol ESA WorldCover 2021 (10 m) ramenée sur la grille de travail 30 m.

Sorties (data/processed/occupation/) :
  worldcover_classe_30m.tif      classe majoritaire (rééchantillonnage « mode »)
  worldcover_frac_<classe>.tif   fraction (0–1) de chaque classe dans la cellule de 30 m
Statistiques par commune et par bassin (GPKG) + outputs/occupation_sol_rapport.json.

Les fractions servent au facteur C : un C de cellule = moyenne des C de classe pondérée par
les fractions (évite de perdre le bâti diffus ou les jardins quand on garde la seule majorité).
Source : ESA WorldCover 10 m 2021 v200, CC BY 4.0 (Zanaga et al., 2022).
"""
import json
from pathlib import Path

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.warp import reproject
from rasterio.windows import from_bounds

ROOT = Path(__file__).resolve().parents[1]
SRC = Path("/mnt/user-data/uploads/ESA_WorldCover_10m_2021_v200_S06E015_Map.tif")
LOCAL = ROOT / "data/raw/worldcover/ESA_WorldCover_10m_2021_v200_S06E015_Map.tif"
src_path = LOCAL if LOCAL.exists() else SRC
OUTD = ROOT / "data/processed/occupation"
OUTD.mkdir(parents=True, exist_ok=True)
CLASSES = {10: "arbres", 20: "arbustes", 30: "herbacees", 40: "cultures", 50: "bati",
           60: "sol_nu", 80: "eau", 90: "zones_humides"}

with rasterio.open(ROOT / "data/processed/topo/pente_deg.tif") as g:
    dst_prof, dst_tr, dst_crs, shape = g.profile.copy(), g.transform, g.crs, (g.height, g.width)
    dst_bounds_wgs = rasterio.warp.transform_bounds(g.crs, "EPSG:4326", *g.bounds)

with rasterio.open(src_path) as s:
    win = from_bounds(*dst_bounds_wgs, transform=s.transform).round_offsets().round_lengths()
    wc = s.read(1, window=win)
    wtr = s.window_transform(win)
    src_crs = s.crs
    tags = s.tags()

prof = dst_prof.copy()
prof.update(dtype="uint8", nodata=0, compress="deflate", predictor=1)
mode = np.zeros(shape, "uint8")
reproject(wc, mode, src_transform=wtr, src_crs=src_crs, dst_transform=dst_tr, dst_crs=dst_crs,
          src_nodata=0, dst_nodata=0, resampling=Resampling.mode)
with rasterio.open(OUTD / "worldcover_classe_30m.tif", "w", **prof) as d:
    d.write(mode, 1)
    d.update_tags(SOURCE="ESA WorldCover 10m 2021 v200 (CC BY 4.0)", RESAMPLING="mode 10 m -> 30 m",
                  LEGEND=tags.get("legend", ""))

fprof = dst_prof.copy()
fprof.update(dtype="float32", nodata=np.nan, compress="deflate", predictor=3)
fracs = {}
for code, name in CLASSES.items():
    ind = (wc == code).astype("float32")
    ind[wc == 0] = np.nan
    f = np.full(shape, np.nan, "float32")
    reproject(ind, f, src_transform=wtr, src_crs=src_crs, dst_transform=dst_tr, dst_crs=dst_crs,
              src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.average)
    with rasterio.open(OUTD / f"worldcover_frac_{name}.tif", "w", **fprof) as d:
        d.write(f, 1)
        d.update_tags(DESCRIPTION=f"fraction de la classe {code} {name} dans la cellule de 30 m")
    fracs[name] = f
del wc

# Statistiques zonales (fractions moyennes = parts de surface)
def zonal(gdf):
    lab = rasterize(((geom, i + 1) for i, geom in enumerate(gdf.geometry)), out_shape=shape,
                    transform=dst_tr, fill=0, dtype="int32")
    n = len(gdf) + 1
    for name, f in fracs.items():
        ok = (lab > 0) & np.isfinite(f)
        s = np.bincount(lab[ok], weights=f[ok], minlength=n)
        c = np.bincount(lab[ok], minlength=n)
        with np.errstate(invalid="ignore", divide="ignore"):
            gdf[f"pct_{name}"] = (100 * s / c)[1:]
    return gdf

B = ROOT / "data/processed/georiskin_vecteurs_utm33s.gpkg"
H = ROOT / "data/processed/georiskin_hydro_utm33s.gpkg"
com = zonal(gpd.read_file(B, layer="communes"))
com.to_file(B, layer="communes", driver="GPKG")
bas = zonal(gpd.read_file(H, layer="bassins_versants"))
bas.to_file(H, layer="bassins_versants", driver="GPKG")
sb = zonal(gpd.read_file(H, layer="sous_bassins"))
sb.to_file(H, layer="sous_bassins", driver="GPKG")

prov = gpd.read_file(B, layer="province")
lab = rasterize(((g, 1) for g in prov.geometry), out_shape=shape, transform=dst_tr, fill=0, dtype="uint8") > 0
rep = {"source": str(src_path.name), "province_pct": {n: float(100 * np.nanmean(f[lab])) for n, f in fracs.items()},
       "communes": com[["nom"] + [c for c in com.columns if c.startswith("pct_")]].round(1).to_dict("records")}
(ROOT / "outputs/occupation_sol_rapport.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(rep["province_pct"], indent=1))
for r in sorted(rep["communes"], key=lambda r: -r["pct_bati"])[:24]:
    print(r["nom"], "bâti", r["pct_bati"], "arbres", r["pct_arbres"], "herbacées", r["pct_herbacees"], "sol nu", r["pct_sol_nu"])
