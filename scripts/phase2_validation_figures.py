"""Contrôles et figures de la phase 2.

1. Réseau calculé vs rivières digitalisées (shap commune : Kisenso, Lemba, Limete,
   Matete, Ngaba) : distance de chaque point des rivières (tous les 30 m) au réseau
   calculé, comparée à la même mesure pour des points tirés au hasard dans la même
   emprise (référence « sans information »).
2. Figures : carte provinciale des bassins et du réseau ; zoom sur la ville.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import geopandas as gpd
import rasterio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from shapely.geometry import Point, box

ROOT = Path(__file__).resolve().parents[1]
PROC, RAW, OUT = ROOT / "data/processed", ROOT / "data/raw", ROOT / "outputs"
H = PROC / "georiskin_hydro_utm33s.gpkg"
B = PROC / "georiskin_vecteurs_utm33s.gpkg"
bas = gpd.read_file(H, layer="bassins_versants")
net = gpd.read_file(H, layer="reseau_hydrographique")
eau = gpd.read_file(H, layer="eau_libre_srtm")
prov = gpd.read_file(B, layer="province")
com = gpd.read_file(B, layer="communes")
rav = gpd.read_file(B, layer="ravines_observees")

# --- 1. Validation du réseau --------------------------------------------------
riv = []
for f in sorted((RAW / "rivieres").glob("*.shp")):
    g = gpd.read_file(f)
    g = (g.set_crs(4326) if g.crs is None else g).to_crs(32733)
    g["source"] = f.stem
    riv.append(g[["source", "geometry"]])
riv = gpd.GeoDataFrame(np.concatenate([r.values for r in riv]), columns=["source", "geometry"], crs=32733)
pts = []
for _, r in riv.iterrows():
    L = r.geometry.length
    for d in np.arange(0, L, 30.0):
        pts.append((r.source, r.geometry.interpolate(d)))
P = gpd.GeoDataFrame({"source": [p[0] for p in pts]}, geometry=[p[1] for p in pts], crs=32733)
area = box(*riv.total_bounds).buffer(500)
netc = net.clip(area)
union = netc.geometry.union_all()
P["dist_m"] = P.geometry.distance(union)
rng = np.random.default_rng(42)
x0, y0, x1, y1 = riv.total_bounds
R = gpd.GeoSeries([Point(x, y) for x, y in zip(rng.uniform(x0, x1, 3000), rng.uniform(y0, y1, 3000))], crs=32733)
rdist = R.distance(union)
val = {
    "points_rivieres": int(len(P)),
    "distance_mediane_m": float(P.dist_m.median()),
    "part_a_moins_de_60m_pct": float(100 * (P.dist_m <= 60).mean()),
    "part_a_moins_de_120m_pct": float(100 * (P.dist_m <= 120).mean()),
    "reference_aleatoire_mediane_m": float(np.median(rdist)),
    "reference_aleatoire_moins_de_120m_pct": float(100 * (rdist <= 120).mean()),
    "par_source_mediane_m": P.groupby("source").dist_m.median().round(0).to_dict(),
}
(OUT / "phase2_validation_reseau.json").write_text(json.dumps(val, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(val, indent=1, ensure_ascii=False))

# --- 2. Figures ------------------------------------------------------------------
with rasterio.open(PROC / "topo/ombrage.tif") as s:
    RES_M = s.res[0]
    hs = s.read(1).astype(float)
    hs[hs == 0] = np.nan
    ext = (s.bounds.left, s.bounds.right, s.bounds.bottom, s.bounds.top)


def km(ax):
    ax.set_xticks(ax.get_xticks())
    ax.set_yticks(ax.get_yticks())
    ax.set_xticklabels([f"{v/1000:.0f}" for v in ax.get_xticks()], fontsize=7)
    ax.set_yticklabels([f"{v/1000:.0f}" for v in ax.get_yticks()], fontsize=7)
    ax.set_xlabel("UTM 33S – X (km)", fontsize=8)
    ax.set_ylabel("UTM 33S – Y (km)", fontsize=8)


fig, ax = plt.subplots(figsize=(13, 10), dpi=150)
ax.imshow(hs, cmap="gray", extent=ext, alpha=0.9)
bc = bas.clip(prov.buffer(2000))
cmap = ListedColormap(plt.get_cmap("tab20").colors)
bc.plot(ax=ax, column="code", cmap=cmap, alpha=0.35, edgecolor="k", lw=0.4)
eau.plot(ax=ax, color="#2b6cb0", alpha=0.9)
n3 = net[net.ordre_strahler >= 3]
n3.plot(ax=ax, color="#1d4ed8", lw=n3.ordre_strahler / 3)
prov.boundary.plot(ax=ax, color="crimson", lw=1.2)
for _, r in bas[bas.superficie_km2 >= 150].iterrows():
    p = r.geometry.intersection(prov.geometry.iloc[0])
    if p.is_empty:
        continue
    q = p.representative_point()
    ax.annotate(r.code, (q.x, q.y), fontsize=7, ha="center", weight="bold")
ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3]); km(ax)
ax.set_title(f"Bassins versants calculés (D8, MNT SRTM {RES_M:g} m ; nord de Maluku : Copernicus GLO-30) et réseau d'ordre ≥ 3\n"
             "rouge : limite de la ville-province ; bleu foncé : fleuve Congo tracé + eau aplanie SRTM", fontsize=10)
fig.tight_layout(); fig.savefig(OUT / "fig3_bassins_kinshasa.png"); plt.close(fig)

# Zoom ville : réseau calculé vs rivières digitalisées
zoom = box(*riv.total_bounds).buffer(4000)
zx0, zy0, zx1, zy1 = zoom.bounds
fig, ax = plt.subplots(figsize=(11, 9), dpi=150)
ax.imshow(hs, cmap="gray", extent=ext)
net.clip(zoom).plot(ax=ax, color="#2563eb", lw=1.2, label="réseau calculé (≥ 1 km²)")
riv.plot(ax=ax, color="#f97316", lw=1.0, label="rivières digitalisées (shap commune)")
com.boundary.clip(zoom).plot(ax=ax, color="k", lw=0.4)
rav.plot(ax=ax, color="#dc2626", markersize=4, label="ravines (indicatif)")
eau.clip(zoom).plot(ax=ax, color="#1e3a8a", alpha=0.8)
ax.set_xlim(zx0, zx1); ax.set_ylim(zy0, zy1); km(ax)
ax.legend(loc="lower left", fontsize=8)
ax.set_title(f"Contrôle du réseau : médiane {val['distance_mediane_m']:.0f} m entre rivières digitalisées et réseau calculé "
             f"(référence aléatoire : {val['reference_aleatoire_mediane_m']:.0f} m)", fontsize=9)
fig.tight_layout(); fig.savefig(OUT / "fig4_controle_reseau.png"); plt.close(fig)
