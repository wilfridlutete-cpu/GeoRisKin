"""Figures de contrôle du facteur LS."""
import json
from pathlib import Path
import numpy as np, geopandas as gpd, rasterio, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
P, OUT = ROOT / "data/processed", ROOT / "outputs"
with rasterio.open(P / "topo/ls_rusle.tif") as s:
    ls = s.read(1); b = s.bounds; ext = (b.left, b.right, b.bottom, b.top); tr = s.transform
with rasterio.open(P / "topo/ombrage.tif") as s:
    hs = s.read(1).astype(float); hs[hs == 0] = np.nan
with rasterio.open(P / "topo/pente_deg.tif") as s:
    sl = s.read(1)
steep = float(100 * np.nanmean(sl > 26.57))
prov = gpd.read_file(P / "georiskin_vecteurs_utm33s.gpkg", layer="province")
com = gpd.read_file(P / "georiskin_vecteurs_utm33s.gpkg", layer="communes")
rav = gpd.read_file(P / "georiskin_vecteurs_utm33s.gpkg", layer="ravines_observees")
net = gpd.read_file(P / "georiskin_hydro_utm33s.gpkg", layer="reseau_hydrographique")

fig, axs = plt.subplots(1, 2, figsize=(20, 9), dpi=130, gridspec_kw={"width_ratios": [1.35, 1]})
for ax, zoom in zip(axs, (None, box(*rav.total_bounds).buffer(3500))):
    ax.imshow(hs, cmap="gray", extent=ext)
    im = ax.imshow(np.where(ls > 0, ls, np.nan), cmap="magma_r", norm=LogNorm(0.1, 100), extent=ext, alpha=0.85)
    prov.boundary.plot(ax=ax, color="#0ea5e9", lw=1)
    if zoom is not None:
        com.boundary.plot(ax=ax, color="k", lw=0.6)
        net.clip(zoom).plot(ax=ax, color="#2563eb", lw=0.8)
        rav.plot(ax=ax, facecolor="none", edgecolor="#22c55e", lw=1.2)
        x0, y0, x1, y1 = zoom.bounds
        ax.set_xlim(x0, x1); ax.set_ylim(y0, y1)
        ax.set_title("Zoom Lemba–Kisenso : LS, réseau (bleu), ravines indicatives (vert)", fontsize=10)
    else:
        ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3])
        ax.set_title("Facteur LS RUSLE à 30 m (Desmet & Govers 1996 × McCool 1987)\n"
                     "blanc : écoulement concentré (≥ 0,1 km²) ou eau, hors domaine RUSLE", fontsize=10)
    ax.set_xticks([]); ax.set_yticks([])
fig.colorbar(im, ax=axs, shrink=0.7, label="LS (sans dimension, échelle log)")
fig.savefig(OUT / "fig6_facteur_ls.png", bbox_inches="tight")
r = json.loads((OUT / "phase3_ls_rapport.json").read_text())
r["part_pentes_sup_50pct"] = steep
(OUT / "phase3_ls_rapport.json").write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
print("pentes > 50 % :", round(steep, 2), "%")
