"""Transfère les noms des cours d'eau de la carte fournie vers le réseau et les bassins calculés.

Entrées :
  data/raw/carte_cours_eau/carte_cours_eau_kinshasa.png  carte nommée (image)
  data/raw/carte_cours_eau/etiquettes.csv                position (pixels) de chaque nom, relevée
                                                         sur l'image à côté du trait qu'il désigne
  outputs/georef_carte_rivieres.json                     calage de l'image (graticule + échelle)
  data/processed/topo/direction_d8.tif, aire_drainee_km2.tif, georiskin_hydro_utm33s.gpkg

Méthode (documentée, sans invention de cours d'eau) :
 1. le point d'étiquette est déplacé sur le trait bleu le plus proche de l'image (≤ 10 px) ;
 2. il est géoréférencé puis accroché à la cellule du réseau calculé la plus proche (≤ 300 m) ;
    colonne `contrainte` (levée d'ambiguïté manuelle, documentée) : « principal » = plus grande
    aire drainée dans le rayon (Ndjili, Lukaya) ; « affluent » = cellules > 100 km² exclues
    (Mumfu, dont l'étiquette touche le tronc de la Ndjili) ;
 3. le nom est propagé vers l'amont en suivant la branche de plus grande aire drainée, et vers
    l'aval jusqu'à la confluence avec un cours d'eau plus grand (aire des autres apports > aire
    du cours d'eau nommé) ;
 4. un tronçon prend le nom majoritaire de ses cellules ; un sous-bassin prend le nom du cours
    d'eau à son exutoire ; un bassin prend le nom du cours d'eau nommé de plus grande aire drainée.
Les étiquettes non accrochées sont listées dans le rapport, pas forcées.
"""
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from PIL import Image
from rasterio.transform import Affine
from scipy import ndimage as ndi
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[1]
PROC, OUT = ROOT / "data/processed", ROOT / "outputs"
D = ROOT / "data/raw/carte_cours_eau"
H = PROC / "georiskin_hydro_utm33s.gpkg"
SNAP_M, IMG_SNAP_PX = 300.0, 10

geo = json.loads((OUT / "georef_carte_rivieres.json").read_text())
s = geo["m_par_pixel"] / (geo["facteur_echelle"])  # calage initial (graticule + échelle graphique)
img_tr = Affine(*geo["transform"])
# on retient le calage initial (le recalage automatique n'améliore que de 1 m la médiane)
from pyproj import Transformer  # noqa: E402
E0, N0 = Transformer.from_crs(4326, 32733, always_xy=True).transform(15.5, -4.5)
s0 = 5000 / (174 - 47)
img_tr = Affine(s0, 0, E0 - 965.5 * s0, 0, -s0, N0 + 744.5 * s0)

a = np.asarray(Image.open(D / "carte_cours_eau_kinshasa.png").convert("RGB")).astype(int)
blue = (a[..., 2] > 150) & (a[..., 0] < 90) & (a[..., 1] < 120)
_, (iy, ix) = ndi.distance_transform_edt(~blue, return_indices=True)

with rasterio.open(PROC / "topo/direction_d8.tif") as src:
    fdir = src.read(1)
    tr = src.transform
with rasterio.open(PROC / "topo/aire_drainee_km2.tif") as src:
    area = src.read(1)
nr, nc = fdir.shape
cell_km2 = abs(tr.a * tr.e) / 1e6
stream = np.nan_to_num(area) >= 1.0
DR = {1: (0, 1), 2: (1, 1), 4: (1, 0), 8: (1, -1), 16: (0, -1), 32: (-1, -1), 64: (-1, 0), 128: (-1, 1)}


def down(r, c):
    d = DR.get(int(fdir[r, c]))
    if d is None:
        return None
    rr, cc = r + d[0], c + d[1]
    return (rr, cc) if 0 <= rr < nr and 0 <= cc < nc and fdir[rr, cc] != 255 else None


def upstream_neighbours(r, c):
    out = []
    for code, (dr, dc) in DR.items():
        rr, cc = r - dr, c - dc
        if 0 <= rr < nr and 0 <= cc < nc and fdir[rr, cc] == code:
            out.append((rr, cc))
    return out


# 1–2. accrochage
lab = pd.read_csv(D / "etiquettes.csv").fillna({"contrainte": ""})
sr, sc = np.nonzero(stream)
sx, sy = tr.c + (sc + 0.5) * tr.a, tr.f + (sr + 0.5) * tr.e
rows = []
for _, L in lab.iterrows():
    y0, x0 = int(L.y_px), int(L.x_px)
    by, bx = iy[y0, x0], ix[y0, x0]
    dpx = float(np.hypot(by - y0, bx - x0))
    X, Y = img_tr * (bx + 0.5, by + 0.5)
    dist = np.hypot(sx - X, sy - Y)
    sa = area[sr, sc]
    kind = str(L.get("contrainte", "") or "")
    if kind == "principal":    # cours d'eau principal : plus grande aire drainée à moins de SNAP_M
        cand = np.nonzero(dist <= SNAP_M)[0]
        k = int(cand[np.argmax(sa[cand])]) if cand.size else int(np.argmin(dist))
    elif kind == "affluent":   # affluent posé contre un tronc : on exclut les cellules > 100 km²
        k = int(np.argmin(np.where(sa < 100, dist, np.inf)))
    else:
        k = int(np.argmin(dist))
    dm = float(dist[k])
    rows.append(dict(nom=L.nom, x_px=x0, y_px=y0, ecart_trait_px=dpx, X=X, Y=Y, r=int(sr[k]), c=int(sc[k]),
                     ecart_reseau_m=dm, aire_km2=float(area[sr[k], sc[k]]),
                     accroche=(dpx <= IMG_SNAP_PX and dm <= SNAP_M)))
L = pd.DataFrame(rows)

# 3. propagation. Chaque cellule d'étiquette est d'abord réservée à son nom ; les
#    propagations s'arrêtent sur une cellule réservée par une autre étiquette.
name = np.full(fdir.shape, "", dtype=object)
reserved = {}
for _, p in L[L.accroche].iterrows():
    reserved.setdefault((p.r, p.c), p["nom"])
for (r, c), nm in reserved.items():
    name[r, c] = nm
for _, p in L[L.accroche].sort_values("aire_km2").iterrows():
    nm = p["nom"]
    # amont : branche principale (plus grande aire drainée)
    r, c = p.r, p.c
    while True:
        ups = [(rr, cc) for rr, cc in upstream_neighbours(r, c) if stream[rr, cc]]
        if not ups:
            break
        r, c = max(ups, key=lambda q: area[q])
        if reserved.get((r, c), nm) != nm or (name[r, c] and name[r, c] != nm):
            break
        name[r, c] = nm
    # aval : jusqu'à une cellule d'une autre étiquette ou la confluence avec plus grand
    r, c = p.r, p.c
    while True:
        nxt = down(r, c)
        if nxt is None or not stream[nxt]:
            break
        if area[nxt] - area[r, c] - cell_km2 > area[r, c]:
            break
        if reserved.get(nxt, nm) != nm or (name[nxt] and name[nxt] != nm):
            break
        r, c = nxt
        name[r, c] = nm

# 4. tronçons, sous-bassins, bassins
net = gpd.read_file(H, layer="reseau_hydrographique")
sb = gpd.read_file(H, layer="sous_bassins")
bas = gpd.read_file(H, layer="bassins_versants")


def cells_of_line(g, step=None):
    step = step or abs(tr.a) / 2
    pts = [g.interpolate(d) for d in np.arange(0, g.length + 1e-6, step)]
    out = []
    for q in pts:
        c, r = ~tr * (q.x, q.y)
        r, c = int(r), int(c)
        if 0 <= r < nr and 0 <= c < nc:
            out.append(name[r, c])
    return out


noms = []
for g in net.geometry:
    v = [n for n in cells_of_line(g) if n]
    noms.append(Counter(v).most_common(1)[0][0] if v and len(v) >= 0.5 * max(1, len(cells_of_line(g))) else None)
net["nom"] = noms


def at_xy(x, y):
    c, r = ~tr * (x, y)
    r, c = int(r), int(c)
    return name[r, c] if 0 <= r < nr and 0 <= c < nc else ""


sb["nom"] = [at_xy(x, y) or None for x, y in zip(sb.exutoire_x, sb.exutoire_y)]


def outlet_stem_name(b):
    """Nom du cours d'eau à l'exutoire du bassin (cellule de plus grande aire du bassin)."""
    x, y = b.exutoire_x, b.exutoire_y
    return at_xy(x, y)
bas_names = []
Lp = gpd.GeoDataFrame(L[L.accroche], geometry=[Point(x, y) for x, y in zip(L[L.accroche].X, L[L.accroche].Y)],
                      crs=32733)
for _, b in bas.iterrows():
    nm = outlet_stem_name(b)
    if not nm:  # exutoire non nommé : cours d'eau nommé de plus grande aire dans le bassin
        inside = Lp[Lp.within(b.geometry)]
        nm = inside.sort_values("aire_km2").iloc[-1]["nom"] if len(inside) else None
    bas_names.append(nm or None)
bas["nom"] = bas_names
bas["nom_source"] = np.where(bas.nom.notna(), "carte des cours d'eau fournie (calage graticule 15°30'E/4°30'S)", None)

for layer, g in (("reseau_hydrographique", net), ("sous_bassins", sb), ("bassins_versants", bas)):
    g.to_file(H, layer=layer, driver="GPKG")
gpd.GeoDataFrame(L.drop(columns=["r", "c"]), geometry=[Point(x, y) for x, y in zip(L.X, L.Y)], crs=32733
                 ).to_file(H, layer="etiquettes_cours_eau", driver="GPKG")

rep = {"etiquettes": int(len(L)), "accrochees": int(L.accroche.sum()),
       "non_accrochees": L[~L.accroche][["nom", "ecart_trait_px", "ecart_reseau_m"]].round(0).to_dict("records"),
       "ecart_reseau_median_m": float(L.ecart_reseau_m.median()),
       "troncons_nommes": int(net.nom.notna().sum()), "longueur_nommee_km": float(net[net.nom.notna()].length.sum() / 1000),
       "sous_bassins_nommes": int(sb.nom.notna().sum()),
       "bassins_nommes": bas[bas.nom.notna()][["code", "nom", "superficie_km2", "exutoire_type"]].round(1).to_dict("records")}
(OUT / "noms_cours_eau_rapport.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(rep, indent=1, ensure_ascii=False))
