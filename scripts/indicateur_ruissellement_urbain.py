"""Indicateur de ruissellement urbain (option C, complément de RUSLE pour les ravines).

Hypothèse : la part bâtie WorldCover (10 m, agrégée à 30 m) approxime la surface imperméable.
1. A_imp (m²) = surface bâtie cumulée vers l'aval selon D8 (accumulation pondérée par la fraction bâtie).
2. IPRU = (A_imp / largeur de cellule) · tan(pente)  [m] : indice de puissance d'écoulement
   (forme du « stream power index », Moore et al. 1991) calculé avec la seule surface imperméable amont.
   Indice RELATIF, sans seuil calibré : ce n'est ni une perte de sol ni une probabilité de ravine.
3. Contrôle : pouvoir discriminant (AUC) des cellules des ravines indicatives vs autres cellules des
   communes concernées, comparé à la pente, à LS et au SPI calculé sur toute la surface drainée.
Limites : D8 sur MNT 30 m ignore caniveaux, collecteurs et routes ; WorldCover bâti ≠ imperméable.
Le calcul est fait sur la fenêtre province + 2 km (surfaces bâties hors fenêtre ignorées).
"""
import json
from pathlib import Path

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.features import rasterize
from scipy.stats import rankdata

import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.flow_analysis import flow_accumulation  # noqa: E402

T = ROOT / "data/processed/topo"
with rasterio.open(T / "direction_d8.tif") as s:
    fdir = s.read(1); prof = s.profile.copy(); tr = s.transform; shp = fdir.shape
cell = abs(tr.a)
slope = rasterio.open(T / "pente_deg.tif").read(1)
atot = rasterio.open(T / "aire_drainee_km2.tif").read(1) * 1e6
ls = rasterio.open(T / "ls_rusle.tif").read(1)
fb = rasterio.open(ROOT / "data/processed/occupation/worldcover_frac_bati.tif").read(1)
valid = (fdir != 255) & np.isfinite(slope)
w = np.where(np.isfinite(fb), fb, 0.0) * cell * cell
aimp = flow_accumulation(fdir, valid, w)
tanb = np.tan(np.radians(np.maximum(slope, 0.1)))  # pente minimale 0,1° (évite 0 en zone plane)
ipru = (aimp / cell) * tanb
spi = (atot / cell) * tanb
part = np.where(atot > 0, aimp / atot, np.nan)

prof.update(dtype="float32", nodata=np.nan, compress="deflate", predictor=3)
OUT = ROOT / "data/processed/ruissellement_urbain"; OUT.mkdir(parents=True, exist_ok=True)
for name, a, unit in (("surface_impermeable_amont_m2", aimp, "m2"), ("part_impermeable_amont", part, "0-1"),
                      ("ipru_m", ipru, "m (indice relatif)")):
    with rasterio.open(OUT / f"{name}.tif", "w", **prof) as o:
        o.write(a.astype("float32"), 1)
        o.update_tags(UNITE=unit, STATUT="indicateur calcule, non calibre",
                      HYPOTHESE="fraction batie WorldCover = surface impermeable ; D8 MNT 30 m")

B = ROOT / "data/processed/georiskin_vecteurs_utm33s.gpkg"
rav = gpd.read_file(B, layer="ravines_observees")
com = gpd.read_file(B, layer="communes")
rm = rasterize(((g, 1) for g in rav.geometry), out_shape=shp, transform=tr, fill=0, dtype="uint8") > 0
cz = com[com.intersects(rav.geometry.make_valid().union_all())]
cm = rasterize(((g, 1) for g in cz.geometry), out_shape=shp, transform=tr, fill=0, dtype="uint8") > 0


def auc(x, pos, neg):
    a, b = x[pos & np.isfinite(x)], x[neg & np.isfinite(x)]
    r = rankdata(np.concatenate([a, b]))
    return float((r[:a.size].sum() - a.size * (a.size + 1) / 2) / (a.size * b.size))


neg = cm & ~rm & valid
pos = rm & valid
rep = {"communes_de_controle": sorted(cz["nom"].tolist()),
       "cellules_ravines": int(pos.sum()), "cellules_temoins": int(neg.sum()),
       "AUC_ravines_vs_temoins": {"IPRU (surface bâtie amont)": round(auc(ipru, pos, neg), 3),
                                  "SPI (toute surface amont)": round(auc(spi, pos, neg), 3),
                                  "LS RUSLE": round(auc(ls, pos, neg), 3),
                                  "pente": round(auc(slope, pos, neg), 3),
                                  "part imperméable amont": round(auc(part, pos, neg), 3)},
       "lecture_AUC": "0,5 = aucun pouvoir discriminant ; 1 = séparation parfaite. Ravines = polygones indicatifs (Kisenso/Lemba…), non exhaustifs.",
       "medianes": {k: {"ravines": float(np.nanmedian(a[pos])), "temoins": float(np.nanmedian(a[neg]))}
                    for k, a in (("ipru_m", ipru), ("surface_impermeable_amont_m2", aimp), ("pente_deg", slope))}}
lab = rasterize(((g, i + 1) for i, g in enumerate(com.geometry)), out_shape=shp, transform=tr, fill=0, dtype="int32")
rep["ipru_p95_par_commune"] = {r.nom: round(float(np.nanpercentile(ipru[(lab == i + 1) & valid], 95)), 1)
                               for i, r in enumerate(com.itertuples()) if ((lab == i + 1) & valid).any()}
(ROOT / "outputs/ruissellement_urbain_rapport.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps({k: rep[k] for k in rep if k != "ipru_p95_par_commune"}, indent=1, ensure_ascii=False))
print(sorted(rep["ipru_p95_par_commune"].items(), key=lambda x: -x[1])[:10])
