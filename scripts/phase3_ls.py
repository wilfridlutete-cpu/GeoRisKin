"""Phase 3a — Facteur topographique LS (RUSLE) à 30 m sur toute la ville-province.

Usage : python scripts/phase3_ls.py [--canal-km2 0.1]

Entrées : data/processed/topo/{pente_deg, exposition_deg, aire_drainee_km2, eau_libre}.tif (phase 2)
Sorties : data/processed/topo/ls_rusle.tif (+ facteur_l, facteur_s, variantes, masque),
          statistiques LS par bassin, sous-bassin et commune (GPKG), outputs/phase3_ls_rapport.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.features import rasterize

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine import ls_factor as lsf  # noqa: E402

PROC, OUT = ROOT / "data/processed", ROOT / "outputs"
TOPO = PROC / "topo"
ap = argparse.ArgumentParser()
ap.add_argument("--canal-km2", type=float, default=0.1,
                help="aire drainée au-delà de laquelle l'écoulement est concentré (hors RUSLE)")
args = ap.parse_args()
t0 = time.perf_counter()


def read(name):
    with rasterio.open(TOPO / f"{name}.tif") as s:
        a = s.read(1).astype("float64")
        if s.nodata is not None and not np.isnan(s.nodata):
            a[a == s.nodata] = np.nan
        return a, s.profile.copy(), s.transform


slope, prof, tr = read("pente_deg")
aspect, _, _ = read("exposition_deg")
area_km2, _, _ = read("aire_drainee_km2")
eau, _, _ = read("eau_libre")
D = abs(tr.a)
area_m2 = area_km2 * 1e6
area_m2[np.nan_to_num(eau) > 0] = np.nan  # eau libre : hors calcul

LS, L, S, chan = lsf.ls_factor(area_m2, D, slope, aspect, args.canal_km2 * 1e6, "mccool")
LS_n, _, _, _ = lsf.ls_factor(area_m2, D, slope, aspect, args.canal_km2 * 1e6, "nearing")
mb = lsf.ls_moore_burch(area_m2, D, np.deg2rad(slope), aspect)
LS_mb = np.where(chan | np.isnan(LS), np.nan, mb).astype("float32")


def write(name, arr, desc, units, dtype="float32", nodata=np.nan):
    p = prof.copy()
    p.update(dtype=dtype, nodata=nodata, compress="deflate", predictor=1)
    with rasterio.open(TOPO / f"{name}.tif", "w", **p) as d:
        d.write(arr.astype(dtype), 1)
        d.update_tags(DESCRIPTION=desc, UNITS=units, ENGINE="georiskin phase 3",
                      CANAL_KM2=str(args.canal_km2))


write("ls_rusle", LS, "LS RUSLE : L Desmet-Govers 1996 x S McCool 1987 ; NaN = ecoulement concentre ou eau",
      "sans dimension")
write("facteur_l", np.where(np.isnan(LS), np.nan, L), "L Desmet-Govers 1996, m McCool 1989", "sans dimension")
write("facteur_s", np.where(np.isnan(slope), np.nan, S), "S McCool 1987", "sans dimension")
write("ls_variante_nearing", LS_n, "LS avec S de Nearing 1997 (sensibilite)", "sans dimension")
write("ls_variante_moore_burch", LS_mb, "LS Moore & Burch 1986 (sensibilite)", "sans dimension")
write("ecoulement_concentre", np.where(np.isnan(slope), 255, chan.astype("uint8")),
      f"1 = aire drainee >= {args.canal_km2} km2 (hors domaine RUSLE)", "0/1", "uint8", 255)

valid = np.isfinite(LS)


def stats(v):
    v = v[np.isfinite(v)]
    return {"n": int(v.size), "moyenne": float(v.mean()), "mediane": float(np.median(v)),
            "p90": float(np.percentile(v, 90)), "p99": float(np.percentile(v, 99)), "max": float(v.max())}


rep = {"parametres": vars(args), "cellule_m": D,
       "ls_desmet_govers_mccool": stats(LS), "ls_nearing": stats(LS_n), "ls_moore_burch": stats(LS_mb),
       "part_ecoulement_concentre_pct": float(100 * np.nanmean(chan[~np.isnan(slope)])),
       "correlation_spearman_dg_vs_moore_burch": None}
from scipy.stats import spearmanr  # noqa: E402
idx = np.flatnonzero(valid & np.isfinite(LS_mb))
sample = np.random.default_rng(0).choice(idx, size=min(200_000, idx.size), replace=False)
rep["correlation_spearman_dg_vs_moore_burch"] = float(spearmanr(LS.ravel()[sample], LS_mb.ravel()[sample])[0])
rep["correlation_spearman_mccool_vs_nearing"] = float(spearmanr(LS.ravel()[sample], LS_n.ravel()[sample])[0])

# Sensibilité au seuil d'écoulement concentré
sens = {}
for thr in (0.05, 0.1, 0.5, 1.0):
    l2, *_ = lsf.ls_factor(area_m2, D, slope, aspect, thr * 1e6, "mccool")
    v = l2[np.isfinite(l2)]
    sens[str(thr)] = {"moyenne": float(v.mean()), "p90": float(np.percentile(v, 90))}
rep["sensibilite_seuil_canal_km2"] = sens


# --- Statistiques zonales
def zonal(gdf, key):
    lab = rasterize(((g, i + 1) for i, g in enumerate(gdf.geometry)), out_shape=LS.shape, transform=tr,
                    fill=0, dtype="int32")
    n = len(gdf) + 1
    ok = valid & (lab > 0)
    cnt = np.bincount(lab[ok], minlength=n)
    tot = np.bincount(lab[ok], weights=LS[ok], minlength=n)
    land = np.bincount(lab[~np.isnan(slope) & (lab > 0)], minlength=n)
    chn = np.bincount(lab[chan & (lab > 0)], minlength=n)
    med, p90 = [], []
    order = np.argsort(lab[ok], kind="stable")
    vals, labs = LS[ok][order], lab[ok][order]
    bounds = np.searchsorted(labs, np.arange(n + 1))
    for i in range(1, n):
        v = vals[bounds[i]:bounds[i + 1]]
        med.append(float(np.median(v)) if v.size else np.nan)
        p90.append(float(np.percentile(v, 90)) if v.size else np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        gdf["ls_moyen"] = (tot / cnt)[1:]
        gdf["ls_median"] = med
        gdf["ls_p90"] = p90
        gdf["part_ecoulement_concentre_pct"] = (100 * chn / land)[1:]
    return gdf


H = PROC / "georiskin_hydro_utm33s.gpkg"
B = PROC / "georiskin_vecteurs_utm33s.gpkg"
bas = zonal(gpd.read_file(H, layer="bassins_versants"), "code")
sb = zonal(gpd.read_file(H, layer="sous_bassins"), "id_noeud")
com = zonal(gpd.read_file(B, layer="communes"), "nom")
bas.to_file(H, layer="bassins_versants", driver="GPKG")
sb.to_file(H, layer="sous_bassins", driver="GPKG")
com.to_file(B, layer="communes", driver="GPKG")
rep["communes"] = com.sort_values("ls_moyen", ascending=False)[
    ["nom", "ls_moyen", "ls_median", "ls_p90", "part_ecoulement_concentre_pct"]].round(2).to_dict("records")
rep["bassins_nommes"] = bas[bas.nom.notna()].sort_values("ls_moyen", ascending=False)[
    ["code", "nom", "superficie_km2", "ls_moyen", "ls_p90"]].round(2).to_dict("records")

# Association avec les ravines observées (indicatif) : LS dans un tampon de 60 m autour des ravines
rav = gpd.read_file(B, layer="ravines_observees")
m_rav = rasterize(((g.buffer(60), 1) for g in rav.geometry), out_shape=LS.shape, transform=tr, fill=0,
                  dtype="uint8").astype(bool)
zone = rasterize(((g, 1) for g in com[com.nom.isin(["Kisenso", "Lemba"])].geometry), out_shape=LS.shape,
                 transform=tr, fill=0, dtype="uint8").astype(bool)
rep["ravines_indicatives"] = {
    "ls_median_autour_ravines": float(np.nanmedian(LS[m_rav & valid])),
    "ls_median_reste_Kisenso_Lemba": float(np.nanmedian(LS[zone & ~m_rav & valid])),
    "ls_p90_autour_ravines": float(np.nanpercentile(LS[m_rav & valid], 90)),
    "ls_p90_reste_Kisenso_Lemba": float(np.nanpercentile(LS[zone & ~m_rav & valid], 90)),
    "note": "association descriptive sur données indicatives ; pas une validation"}
rep["temps_s"] = round(time.perf_counter() - t0, 1)
(OUT / "phase3_ls_rapport.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps({k: rep[k] for k in rep if k not in ("communes", "bassins_nommes")}, indent=1, ensure_ascii=False))
