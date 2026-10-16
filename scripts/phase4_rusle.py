"""Phase 4 – première carte de perte de sol RUSLE (ensemble d'hypothèses).

Ensemble de 18 combinaisons : R {Lo 1985, Renard & Freimund 1994, Roose 1977 a=0,5} (CHIRPS 1991-2020)
× C {bas, central, haut} × LS {Desmet & Govers, Moore & Burch}. K = Williams/SoilGrids (référence, non comblé).
P = 1 (aucune pratique de conservation cartographiée). Sorties par cellule : médiane, P10, P90 de l'ensemble.
Domaine : cellules où tous les facteurs existent (hors bâti dense, eau, écoulement concentré, sans SoilGrids).
"""
import json
import time
from itertools import product
from pathlib import Path
import sys

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.features import rasterize
from scipy.stats import rankdata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.rusle import rusle  # noqa: E402

t0 = time.time()
PER = "1991-2020"
P = ROOT / "data/processed"
R_SET = {"lo1985": P / f"pluie/facteur_r_lo1985_{PER}_30m.tif",
         "renard_freimund1994": P / f"pluie/facteur_r_renard_freimund1994_{PER}_30m.tif",
         "roose1977": P / f"pluie/facteur_r_roose1977_a0.50_{PER}_30m.tif"}
C_SET = {v: P / f"occupation/facteur_c_{v}_30m.tif" for v in ("bas", "central", "haut")}
LS_SET = {"desmet_govers": P / "topo/ls_rusle.tif", "moore_burch": P / "topo/ls_variante_moore_burch.tif"}
rd = lambda f: rasterio.open(f).read(1).astype("float32")  # noqa: E731
with rasterio.open(LS_SET["desmet_govers"]) as s:
    prof, tr, shp = s.profile.copy(), s.transform, (s.height, s.width)
K = rd(P / "sols/facteur_k_williams_30m.tif")
conc = rd(P / "topo/ecoulement_concentre.tif") > 0
Rs = {k: rd(f) for k, f in R_SET.items()}
Cs = {k: rd(f) for k, f in C_SET.items()}
LSs = {k: np.where(conc, np.nan, rd(f)).astype("float32") for k, f in LS_SET.items()}

runs, names = [], []
for (rn, R), (cn, C), (ln, LS) in product(Rs.items(), Cs.items(), LSs.items()):
    runs.append(rusle(R, K, LS, C, 1.0)); names.append(f"R={rn}|C={cn}|LS={ln}")
stack = np.stack(runs)
del runs
valid = np.all(np.isfinite(stack), axis=0)
q = np.full((3, *shp), np.nan, "float32")
q[:, valid] = np.percentile(stack[:, valid], [10, 50, 90], axis=0)
ref_idx = names.index("R=renard_freimund1994|C=central|LS=desmet_govers")
ref = stack[ref_idx]

OUT = P / "erosion"; OUT.mkdir(parents=True, exist_ok=True)
prof.update(dtype="float32", nodata=np.nan, compress="deflate", predictor=3)
tags = {"UNITE": "t/ha/an", "MODELE": "RUSLE (erosion en nappe et rigoles)", "PERIODE_PLUIE": PER,
        "STATUT": "ESTIMATION NON VALIDEE ; facteurs empiriques non cales a Kinshasa", "P": "1 (aucune pratique)"}
for name, arr in (("perte_sol_mediane", q[1]), ("perte_sol_p10", q[0]), ("perte_sol_p90", q[2]),
                  ("perte_sol_reference_renard_ccentral_dg", ref)):
    with rasterio.open(OUT / f"{name}_t_ha_an_30m.tif", "w", **prof) as o:
        o.write(arr.astype("float32"), 1); o.update_tags(**tags, ENSEMBLE=json.dumps(names) if "reference" not in name else names[ref_idx])

# Statistiques
B = P / "georiskin_vecteurs_utm33s.gpkg"; H = P / "georiskin_hydro_utm33s.gpkg"
prov = gpd.read_file(B, layer="province")
pm = rasterize(((g, 1) for g in prov.geometry), out_shape=shp, transform=tr, fill=0, dtype="uint8") > 0
cell_ha = abs(tr.a * tr.e) / 1e4


def zonal(gdf):
    lab = rasterize(((g, i + 1) for i, g in enumerate(gdf.geometry)), out_shape=shp, transform=tr, fill=0, dtype="int32")
    n = len(gdf) + 1
    tot = np.bincount(lab.ravel(), minlength=n)
    ok = (lab > 0) & valid
    cnt = np.bincount(lab[ok], minlength=n)
    with np.errstate(invalid="ignore", divide="ignore"):
        for tag, arr in (("med", q[1]), ("p10", q[0]), ("p90", q[2])):
            s_ = np.bincount(lab[ok], weights=arr[ok].astype("float64"), minlength=n)
            gdf[f"a_moy_{tag}_t_ha_an"] = (s_ / cnt)[1:]
            gdf[f"perte_{tag}_t_an"] = (s_ * cell_ha)[1:]
        gdf["part_domaine_rusle_pct"] = (100 * cnt / np.maximum(tot, 1))[1:]
    return gdf


com = zonal(gpd.read_file(B, layer="communes")); com.to_file(B, layer="communes", driver="GPKG")
bas = zonal(gpd.read_file(H, layer="bassins_versants")); bas.to_file(H, layer="bassins_versants", driver="GPKG")
sb = zonal(gpd.read_file(H, layer="sous_bassins")); sb.to_file(H, layer="sous_bassins", driver="GPKG")

v = q[1][pm & valid]
rep = {"statut": tags["STATUT"], "periode_pluie": PER, "ensemble": names, "reference": names[ref_idx],
       "part_province_dans_domaine_rusle_pct": round(float(100 * valid[pm].mean()), 1),
       "province_mediane_ensemble_t_ha_an": {"p10_cellules": round(float(np.percentile(v, 10)), 2),
                                             "mediane_cellules": round(float(np.median(v)), 2),
                                             "moyenne": round(float(v.mean()), 2),
                                             "p90_cellules": round(float(np.percentile(v, 90)), 1),
                                             "p99_cellules": round(float(np.percentile(v, 99)), 1)},
       "province_moyenne_par_hypothese_t_ha_an": {n_: round(float(np.nanmean(stack[i][pm & valid])), 2) for i, n_ in enumerate(names)},
       "ratio_p90_sur_p10_median": round(float(np.median((q[2] / q[0])[pm & valid & (q[0] > 0)])), 1),
       "communes": {r.nom: {"a_moy_med": round(float(r.a_moy_med_t_ha_an), 2) if np.isfinite(r.a_moy_med_t_ha_an) else None,
                            "a_moy_p10": round(float(r.a_moy_p10_t_ha_an), 2) if np.isfinite(r.a_moy_p10_t_ha_an) else None,
                            "a_moy_p90": round(float(r.a_moy_p90_t_ha_an), 2) if np.isfinite(r.a_moy_p90_t_ha_an) else None,
                            "domaine_pct": round(float(r.part_domaine_rusle_pct), 1)} for r in com.itertuples()}}
rav = gpd.read_file(B, layer="ravines_observees")
rm = rasterize(((g, 1) for g in rav.geometry), out_shape=shp, transform=tr, fill=0, dtype="uint8") > 0
buf = rasterize(((g.buffer(150), 1) for g in rav.geometry.make_valid()), out_shape=shp, transform=tr, fill=0, dtype="uint8") > 0
cz = com[com.intersects(rav.geometry.make_valid().union_all())]
cm = rasterize(((g, 1) for g in cz.geometry), out_shape=shp, transform=tr, fill=0, dtype="uint8") > 0


def auc(x, pos, neg):
    a, b = x[pos & np.isfinite(x)], x[neg & np.isfinite(x)]
    if a.size == 0 or b.size == 0:
        return None
    r = rankdata(np.concatenate([a, b]))
    return round(float((r[:a.size].sum() - a.size * (a.size + 1) / 2) / (a.size * b.size)), 3)


rep["controle_ravines_indicatives"] = {
    "communes": sorted(cz.nom), "cellules_ravines_dans_domaine": int((rm & valid).sum()),
    "cellules_ravines_total": int(rm.sum()),
    "AUC_A_mediane_ravines_vs_reste_des_communes": auc(q[1], rm, cm & ~buf),
    "AUC_A_mediane_bande_150m_vs_reste": auc(q[1], buf & ~rm, cm & ~buf),
    "A_mediane_ravines": float(np.nanmedian(np.where(rm, q[1], np.nan))),
    "A_mediane_bande_150m": float(np.nanmedian(np.where(buf & ~rm, q[1], np.nan))),
    "A_mediane_reste": float(np.nanmedian(np.where(cm & ~buf, q[1], np.nan)))}
rep["duree_s"] = round(time.time() - t0)
(ROOT / "outputs/phase4_rusle_rapport.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps({k: rep[k] for k in rep if k not in ("communes", "ensemble", "province_moyenne_par_hypothese_t_ha_an")}, indent=1, ensure_ascii=False))
for k_, v_ in sorted(rep["communes"].items(), key=lambda x: -(x[1]["a_moy_med"] or 0)): print(k_, v_)
