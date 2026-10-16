"""Facteur K (érodibilité) à partir de SoilGrids 2.0, 0–5 cm (ISRIC, CC BY 4.0, ≈ 250 m).

1. Lecture sable, limon, argile (g/kg) et carbone organique (dg/kg) ; 0 = sans donnée (eau).
2. Contrôle : sable + limon + argile ≈ 1000 g/kg.
3. K = Williams/EPIC (engine/k_factor.py), en t·ha·h/(ha·MJ·mm), calculé sur la grille SoilGrids.
4. Reprojection bilinéaire sur la grille de travail UTM 33S à 30 m (NaN hors données, jamais 0).
5. Statistiques par commune, bassin, sous-bassin, unité géologique 1963 et autour des ravines.
Hypothèses : la couche 0–5 cm représente l'horizon de surface exposé ; SoilGrids est une
prédiction statistique (non mesurée) peu représentative des sols urbains remaniés.
"""
import json
import sys
from pathlib import Path

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.warp import reproject

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.k_factor import k_williams  # noqa: E402

SG = ROOT / "data/raw/soilgrids"
OUTD = ROOT / "data/processed/sols"
OUTD.mkdir(parents=True, exist_ok=True)

arr = {}
for p in ("sand", "silt", "clay", "soc"):
    with rasterio.open(SG / f"{p}_0-5cm_mean.tif") as s:
        a = s.read(1).astype("float64")
        src_tr, src_crs = s.transform, s.crs
    a[a <= 0] = np.nan
    arr[p] = a
tot = arr["sand"] + arr["silt"] + arr["clay"]
sand, silt, clay = (100 * arr[p] / tot for p in ("sand", "silt", "clay"))  # % normalisés à 100
oc = arr["soc"] / 100.0  # dg/kg -> %
k_sg = k_williams(sand, silt, clay, oc).astype("float32")

with rasterio.open(ROOT / "data/processed/topo/pente_deg.tif") as g:
    prof, tr, crs, shp = g.profile.copy(), g.transform, g.crs, (g.height, g.width)
prof.update(dtype="float32", nodata=np.nan, compress="deflate", predictor=3)


def to30(a):
    o = np.full(shp, np.nan, "float32")
    reproject(a.astype("float32"), o, src_transform=src_tr, src_crs=src_crs, dst_transform=tr,
              dst_crs=crs, src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.bilinear)
    return o


k30 = to30(k_sg)
with rasterio.open(OUTD / "facteur_k_williams_30m.tif", "w", **prof) as o:
    o.write(k30, 1)
    o.update_tags(UNITE="t.ha.h/(ha.MJ.mm)", METHODE="Williams (1995) EPIC, SoilGrids 2.0 0-5 cm",
                  STATUT="estime (non calibre localement)", RESAMPLING="bilineaire 250 m -> 30 m")
for name, a in (("sable_pct", sand), ("limon_pct", silt), ("argile_pct", clay), ("carbone_org_pct", oc)):
    with rasterio.open(OUTD / f"soilgrids_{name}_0-5cm_30m.tif", "w", **prof) as o:
        o.write(to30(a), 1)

B = ROOT / "data/processed/georiskin_vecteurs_utm33s.gpkg"
H = ROOT / "data/processed/georiskin_hydro_utm33s.gpkg"


def zonal(gdf):
    lab = rasterize(((g, i + 1) for i, g in enumerate(gdf.geometry)), out_shape=shp, transform=tr,
                    fill=0, dtype="int32")
    ok = (lab > 0) & np.isfinite(k30)
    n = len(gdf) + 1
    s = np.bincount(lab[ok], weights=k30[ok], minlength=n)
    c = np.bincount(lab[ok], minlength=n)
    with np.errstate(invalid="ignore", divide="ignore"):
        gdf["k_moyen"] = (s / c)[1:]
    return gdf


com = zonal(gpd.read_file(B, layer="communes"))
com.to_file(B, layer="communes", driver="GPKG")
for lay in ("bassins_versants", "sous_bassins"):
    zonal(gpd.read_file(H, layer=lay)).to_file(H, layer=lay, driver="GPKG")

prov = gpd.read_file(B, layer="province")
pm = rasterize(((g, 1) for g in prov.geometry), out_shape=shp, transform=tr, fill=0, dtype="uint8") > 0
kv = k30[pm & np.isfinite(k30)]
rep = {
    "source": "SoilGrids 2.0 (ISRIC), 0-5 cm, moyenne ; CC BY 4.0",
    "identification_out_tif": "identique à sand_0-5cm_mean (sable, g/kg)",
    "somme_texture_g_kg_p1_p50_p99": np.nanpercentile(tot, [1, 50, 99]).round(0).tolist(),
    "texture_province_mediane_pct": {n: round(float(np.nanmedian(to30(a)[pm])), 1)
                                     for n, a in (("sable", sand), ("limon", silt), ("argile", clay), ("carbone_org", oc))},
    "k_province": {"min": float(kv.min()), "p5": float(np.percentile(kv, 5)), "mediane": float(np.median(kv)),
                   "p95": float(np.percentile(kv, 95)), "max": float(kv.max())},
    "part_province_sans_k_pct": round(float(100 * np.mean(~np.isfinite(k30[pm]))), 2),
    "k_communes": {r.nom: round(float(r.k_moyen), 4) for r in com.itertuples()},
}
gp = ROOT / "data/processed/geologie/geologie_1963_30m.tif"
if gp.exists():
    geo = rasterio.open(gp).read(1)
    noms = ["Ho", "Q", "QPs", "QSo", "So", "Gp", "Ccb/Cca", "Cc/I2", "I2", "I1/P", "Eau/non carto."]
    rep["k_median_par_unite_geologique"] = {noms[k - 1]: round(float(np.nanmedian(k30[(geo == k)])), 4)
                                            for k in range(1, 11) if np.isfinite(k30[geo == k]).any()}
rav = gpd.read_file(B, layer="ravines_observees")
rm = rasterize(((g, 1) for g in rav.geometry), out_shape=shp, transform=tr, fill=0, dtype="uint8") > 0
rep["k_median_ravines_indicatives"] = round(float(np.nanmedian(k30[rm])), 4)
rep["k_median_province_hors_ravines"] = round(float(np.nanmedian(k30[pm & ~rm])), 4)
(ROOT / "outputs/facteur_k_rapport.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(rep, indent=1, ensure_ascii=False))

# --- Variante comblée (HYPOTHÈSE, fichier séparé) -------------------------------------------
# SoilGrids ne prédit pas les zones bâties denses ni l'eau : ces cellules restent NaN dans le K
# de référence. Pour permettre un calcul RUSLE complet, une variante distincte attribue aux cellules
# terrestres sans donnée la valeur du plus proche voisin disponible (distance enregistrée).
from scipy import ndimage as ndi  # noqa: E402
eau = rasterio.open(ROOT / "data/processed/topo/eau_libre.tif").read(1) > 0
gap = ~np.isfinite(k30) & pm & ~eau
dist, (iy, ix) = ndi.distance_transform_edt(~np.isfinite(k30), return_indices=True)
kf = k30.copy()
kf[gap] = k30[iy[gap], ix[gap]]
with rasterio.open(OUTD / "facteur_k_comble_hypothese_30m.tif", "w", **prof) as o:
    o.write(kf, 1)
    o.update_tags(STATUT="HYPOTHESE : cellules sans SoilGrids comblees par le plus proche voisin")
dprof = prof.copy()
with rasterio.open(OUTD / "facteur_k_distance_comblement_m.tif", "w", **dprof) as o:
    o.write(np.where(gap, dist * 30, np.nan).astype("float32"), 1)
rep["variante_comblee"] = {"cellules_comblees_km2": round(float(gap.sum() * 900 / 1e6), 1),
                           "distance_comblement_m_mediane_max": [float(np.median(dist[gap]) * 30),
                                                                 float(dist[gap].max() * 30)]}
(ROOT / "outputs/facteur_k_rapport.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
print(rep["variante_comblee"])
