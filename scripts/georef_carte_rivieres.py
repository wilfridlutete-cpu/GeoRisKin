"""Géoréférence la carte des cours d'eau nommés (image fournie) et vérifie le calage.

Points de calage lus sur l'image : intersection du méridien 15°30'E (colonne 965) et du
parallèle 4°30'S (ligne 744) ; échelle graphique 0–5 km = colonnes 47–174 (39,37 m/pixel).
Hypothèse : carte orientée au nord, échelle uniforme (convergence des méridiens ≈0,04° à
15,5°E en UTM 33S, négligeable). Le calage est ensuite affiné par une recherche de décalage
et d'échelle qui maximise la superposition des lignes bleues de la carte avec le réseau calculé.
"""
import json
from pathlib import Path

import numpy as np
import geopandas as gpd
from PIL import Image
from pyproj import Transformer
from scipy import ndimage as ndi
from rasterio.features import rasterize
from rasterio.transform import Affine

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "data/raw/carte_cours_eau/carte_cours_eau_kinshasa.png"
a = np.asarray(Image.open(IMG).convert("RGB")).astype(int)
H, W = a.shape[:2]
# lignes bleues foncées (cours d'eau) ; on exclut le cadre et la légende
blue = (a[..., 2] > 150) & (a[..., 0] < 90) & (a[..., 1] < 120)
blue[:, :40] = blue[:, 1105:] = False
blue[:45] = blue[835:] = False
blue[40:160, 40:290] = False  # légende

x0px, y0px = 965.5, 744.5
E0, N0 = Transformer.from_crs(4326, 32733, always_xy=True).transform(15.5, -4.5)
s0 = 5000 / (174 - 47)

net = gpd.read_file(ROOT / "data/processed/georiskin_hydro_utm33s.gpkg", layer="reseau_hydrographique")
net = net[net.aire_drainee_km2 >= 2]


def score(dx, dy, s):
    tr = Affine(s, 0, E0 - x0px * s + dx, 0, -s, N0 + y0px * s + dy)
    r = rasterize(((g, 1) for g in net.geometry), out_shape=(H, W), transform=tr, all_touched=True)
    d = ndi.distance_transform_edt(r == 0)  # distance en pixels au réseau calculé
    return float(np.median(d[blue])) * s, tr


best = None
for ds in (-0.02, -0.01, 0, 0.01, 0.02):
    for dx in range(-300, 301, 60):
        for dy in range(-300, 301, 60):
            m, tr = score(dx, dy, s0 * (1 + ds))
            if best is None or m < best[0]:
                best = (m, dx, dy, ds, tr)
m0, _ = score(0, 0, s0)
m, dx, dy, ds, tr = best
# affinage local
for ddx in range(dx - 50, dx + 51, 10):
    for ddy in range(dy - 50, dy + 51, 10):
        mm, t2 = score(ddx, ddy, s0 * (1 + ds))
        if mm < m:
            m, dx, dy, tr = mm, ddx, ddy, t2
rep = {"distance_mediane_m_calage_initial": m0, "distance_mediane_m_apres_affinage": m,
       "decalage_x_m": dx, "decalage_y_m": dy, "facteur_echelle": 1 + ds, "m_par_pixel": tr.a,
       "transform": list(tr)[:6], "pixels_bleus": int(blue.sum())}
(ROOT / "outputs/georef_carte_rivieres.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
print(json.dumps(rep, indent=1))
