"""Facteur R à 30 m à partir du fichier CHIRPS mensuel fourni par l'utilisateur
(data/raw/chirps/chirps_mensuel_kinshasa_<debut>-<fin>.tif, produit par
scripts/utilisateur/chirps_kinshasa.py). Usage : python scripts/facteur_r.py [fichier]
Sorties : data/processed/pluie/{pluie_annuelle_mm, fournier_modifie, facteur_r_<methode>}_30m.tif
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
from engine.r_factor import METHODES, fournier_modifie  # noqa: E402

src = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted((ROOT / "data/raw/chirps").glob("chirps_mensuel_kinshasa_*.tif"))[-1]
PERIODES = [(int(a), int(b)) for a, b in (x.split("-") for x in sys.argv[2:])] or [(1991, 2020), (1991, 2025), (2011, 2025)]
with rasterio.open(src) as s:
    a = s.read().astype("float64")
    a[a == s.nodata] = np.nan
    str_, scrs = s.transform, s.crs
    names = [s.descriptions[i] or f"b{i}" for i in range(s.count)]
if len(names) % 12:
    raise SystemExit(f"{len(names)} bandes : la période doit compter des années complètes")
ny_all = len(names) // 12
y_all = a.reshape(ny_all, 12, *a.shape[1:])
first_year = int(names[0][:4])

with rasterio.open(ROOT / "data/processed/topo/pente_deg.tif") as g:
    prof, tr, crs, shp = g.profile.copy(), g.transform, g.crs, (g.height, g.width)
prof.update(dtype="float32", nodata=np.nan, compress="deflate", predictor=3)
OUT = ROOT / "data/processed/pluie"; OUT.mkdir(parents=True, exist_ok=True)


B = ROOT / "data/processed/georiskin_vecteurs_utm33s.gpkg"
pm = rasterize(((g, 1) for g in gpd.read_file(B, layer="province").geometry), out_shape=shp, transform=tr,
               fill=0, dtype="uint8") > 0

def save(name, arr, tags):
    o30 = np.full(shp, np.nan, "float32")
    reproject(arr.astype("float32"), o30, src_transform=str_, src_crs=scrs, dst_transform=tr, dst_crs=crs,
              src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.bilinear)
    with rasterio.open(OUT / f"{name}_30m.tif", "w", **prof) as d:
        d.write(o30, 1)
        d.update_tags(**tags)
    return o30


rapport = {"source": src.name, "statut": "R estimé par relations empiriques non calées à Kinshasa", "periodes": {}}
for y0, y1 in PERIODES:
    i0, i1 = y0 - first_year, y1 - first_year + 1
    if i0 < 0 or i1 > ny_all:
        raise SystemExit(f"période {y0}-{y1} hors du fichier")
    y = y_all[i0:i1]
    annual = y.sum(axis=1)
    p_mean = annual.mean(axis=0)
    mfi = fournier_modifie(y.mean(axis=0))
    period = f"{y0}-{y1}"
    rep = {"annees": int(i1 - i0)}
    p30 = save(f"pluie_annuelle_mm_{period}", p_mean, {"UNITE": "mm/an", "PERIODE": period, "SOURCE": "CHIRPS 2.0"})
    save(f"fournier_modifie_{period}", mfi, {"UNITE": "mm", "METHODE": "Arnoldus 1980"})
    v = p30[pm & np.isfinite(p30)]
    sp = np.nanmean(annual, axis=(1, 2))
    rep["pluie_annuelle_mm"] = {"min": round(float(v.min())), "mediane": round(float(np.median(v))), "max": round(float(v.max())),
                                "annee_la_plus_seche": [int(y0 + sp.argmin()), round(float(sp.min()))],
                                "annee_la_plus_humide": [int(y0 + sp.argmax()), round(float(sp.max()))]}
    rep["part_province_sans_pluie_pct"] = round(float(100 * np.mean(~np.isfinite(p30[pm]))), 2)
    rep["R_MJ_mm_ha_h_an"] = {}
    for m, f in METHODES.items():
        r30 = save(f"facteur_r_{m}_{period}", f(p_mean), {"UNITE": "MJ.mm/(ha.h.an)", "METHODE": m, "PERIODE": period,
                                                           "STATUT": "estime, relation empirique calee hors Kinshasa"})
        rv = r30[pm & np.isfinite(r30)]
        rep["R_MJ_mm_ha_h_an"][m] = {"min": round(float(rv.min())), "mediane": round(float(np.median(rv))),
                                     "max": round(float(rv.max()))}
    rapport["periodes"][period] = rep
(ROOT / "outputs/facteur_r_rapport.json").write_text(json.dumps(rapport, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(rapport, indent=1, ensure_ascii=False))
