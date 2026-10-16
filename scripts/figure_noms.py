"""Figure de contrôle : réseau calculé nommé superposé à la carte fournie (calée)."""
from pathlib import Path
import numpy as np, geopandas as gpd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
H = ROOT / "data/processed/georiskin_hydro_utm33s.gpkg"
img = np.asarray(Image.open(ROOT / "data/raw/carte_cours_eau/carte_cours_eau_kinshasa.png").convert("RGB"))
E0, N0 = Transformer.from_crs(4326, 32733, always_xy=True).transform(15.5, -4.5)
s = 5000 / 127
left, top = E0 - 965.5 * s, N0 + 744.5 * s
ext = (left, left + img.shape[1] * s, top - img.shape[0] * s, top)
net = gpd.read_file(H, layer="reseau_hydrographique").cx[ext[0]:ext[1], ext[2]:ext[3]]
lab = gpd.read_file(H, layer="etiquettes_cours_eau")
bas = gpd.read_file(H, layer="bassins_versants")
fig, ax = plt.subplots(figsize=(16, 12.4), dpi=130)
ax.imshow(img, extent=ext, alpha=0.45)
bas.boundary.plot(ax=ax, color="k", lw=0.6)
net[net.nom.isna()].plot(ax=ax, color="#9ca3af", lw=0.8)
named = net[net.nom.notna()]
cmap = plt.get_cmap("tab20")
for i, (nm, g) in enumerate(named.groupby("nom")):
    g.plot(ax=ax, color=cmap(i % 20), lw=2.2)
    p = g.geometry.union_all().representative_point()
    ax.annotate(nm, (p.x, p.y), fontsize=7, color="k", weight="bold",
                bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.7))
ok = lab[lab.accroche]
ax.scatter(ok.geometry.x, ok.geometry.y, s=12, c="lime", edgecolors="k", zorder=5, label="étiquette accrochée")
ko = lab[~lab.accroche]
ax.scatter(ko.geometry.x, ko.geometry.y, s=30, c="red", marker="x", zorder=5, label="étiquette non accrochée (> 300 m)")
ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3]); ax.legend(loc="lower right", fontsize=8)
ax.set_title("Noms transférés de la carte fournie (fond, calé) vers le réseau calculé à 30 m — couleurs : tronçons nommés ; gris : non nommés ; traits noirs : bassins", fontsize=9)
ax.set_xticks([]); ax.set_yticks([])
fig.tight_layout(); fig.savefig(ROOT / "outputs/fig5_noms_cours_eau.png")
