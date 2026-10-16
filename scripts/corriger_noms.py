"""Applique parametres/corrections_noms.json : nomme un bassin et son tronc principal
(remontée depuis l'exutoire en suivant, à chaque confluence, le tronçon d'aire drainée maximale)."""
import json
from collections import defaultdict
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parents[1]
H = ROOT / "data/processed/georiskin_hydro_utm33s.gpkg"
corr = json.loads((ROOT / "parametres/corrections_noms.json").read_text(encoding="utf-8"))["corrections"]
r = gpd.read_file(H, layer="reseau_hydrographique")
b = gpd.read_file(H, layer="bassins_versants")


def ends(g):
    g = g.geoms[0] if g.geom_type == "MultiLineString" else g
    c = list(g.coords)
    return (round(c[0][0]), round(c[0][1])), (round(c[-1][0]), round(c[-1][1]))


ab = list(r.geometry.map(ends))
idx = defaultdict(list)
for i, (a, z) in zip(r.index, ab):
    idx[a].append(i)
    idx[z].append(i)
rapport = []
for c in corr:
    bi = b.index[b.code == c["bassin"]]
    b.loc[bi, "nom"] = c["nom"]
    b.loc[bi, "nom_source"] = c["source"]
    n = 0
    if c.get("tronc_depuis_exutoire"):
        seg = r[r.code_bassin == c["bassin"]]
        cur = seg.aire_drainee_km2.idxmax()
        seen = {cur}
        while True:
            r.loc[cur, "nom"] = c["nom"]
            n += 1
            a, z = ab[r.index.get_loc(cur)]
            cand = [j for p in (a, z) for j in idx[p] if j not in seen
                    and r.aire_drainee_km2[j] < r.aire_drainee_km2[cur]]
            if not cand:
                break
            cur = max(cand, key=lambda j: r.aire_drainee_km2[j])
            seen.add(cur)
    rapport.append({"nom": c["nom"], "bassin": c["bassin"], "troncons_nommes": n})
r.to_file(H, layer="reseau_hydrographique", driver="GPKG")
b.to_file(H, layer="bassins_versants", driver="GPKG")
print(rapport)
