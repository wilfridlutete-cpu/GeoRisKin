"""Figure de contrôle de la numérisation géologique 1963 + test alluvions / fonds de vallée."""
import json
from pathlib import Path
import numpy as np, rasterio, geopandas as gpd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from rasterio.features import rasterize
from scipy import ndimage as ndi
ROOT = Path(__file__).resolve().parents[1]
with rasterio.open(ROOT/"data/processed/geologie/geologie_1963_30m.tif") as s:
    geo = s.read(1); tr = s.transform; ext = (s.bounds.left, s.bounds.right, s.bounds.bottom, s.bounds.top)
hs = rasterio.open(ROOT/"data/processed/topo/ombrage.tif").read(1)
acc = rasterio.open(ROOT/"data/processed/topo/aire_drainee_km2.tif").read(1)
cols = ["#00000000","#b1c198","#a88f60","#a4a862","#faf966","#f8e12a","#aac62b","#448155","#7d682d","#9f7330","#683e1e","#e8e8de"]
noms = ["Ho","Q","QPs","QSo","So","Gp","Ccb/Cca","Cc/I2","I2","I1/P","Eau/non carto."]
# test : part des cellules Ho à moins de 150 m d'un drain >= 1 km²
stream = acc >= 1
dist = ndi.distance_transform_edt(~stream) * 30
rep = {}
for k, n in enumerate(noms, 1):
    m = geo == k
    if m.any(): rep[n] = round(float(100*np.mean(dist[m] <= 150)), 1)
B = ROOT/"data/processed/georiskin_vecteurs_utm33s.gpkg"
com = gpd.read_file(B, layer="communes"); rav = gpd.read_file(B, layer="ravines_observees")
fig, ax = plt.subplots(figsize=(11, 10))
ax.imshow(np.where(np.isfinite(hs), hs, np.nan), cmap="gray", extent=ext)
g = np.ma.masked_equal(geo, 0)
ax.imshow(g, cmap=ListedColormap(cols[1:]), vmin=1, vmax=11, alpha=0.6, extent=ext, interpolation="nearest")
com.boundary.plot(ax=ax, color="k", lw=0.5); rav.plot(ax=ax, color="red")
from matplotlib.patches import Patch
ax.legend(handles=[Patch(color=c, label=n) for c, n in zip(cols[1:], noms)], loc="lower right", fontsize=8)
ax.set_title("Géologie 1963 (feuille Léopoldville S.5/15) – numérisation automatique, à vérifier\nrouge : ravines indicatives")
fig.savefig(ROOT/"outputs/fig7_geologie_1963.png", dpi=110, bbox_inches="tight")
p = ROOT/"outputs/geologie_1963_rapport.json"; r = json.loads(p.read_text())
r["part_cellules_a_moins_de_150m_dun_drain_1km2_pct"] = rep
p.write_text(json.dumps(r, indent=2, ensure_ascii=False)); print(rep)
