"""Facteur C provisoire (3 variantes : bas, central, haut) à partir de WorldCover à 30 m.
Table : parametres/table_c_worldcover.json (PROPOSITION à valider). Sorties data/processed/occupation/."""
import json
import sys
from pathlib import Path

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.features import rasterize

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.c_factor import c_from_fractions, class_values  # noqa: E402

table = json.loads((ROOT / "parametres/table_c_worldcover.json").read_text(encoding="utf-8"))
OCC = ROOT / "data/processed/occupation"
fr = {}
for code, c in table["classes"].items():
    with rasterio.open(OCC / f"worldcover_frac_{c['nom']}.tif") as s:
        fr[int(code)] = s.read(1)
        prof, tr, shp = s.profile.copy(), s.transform, (s.height, s.width)
B = ROOT / "data/processed/georiskin_vecteurs_utm33s.gpkg"
prov = gpd.read_file(B, layer="province")
pm = rasterize(((g, 1) for g in prov.geometry), out_shape=shp, transform=tr, fill=0, dtype="uint8") > 0
com = gpd.read_file(B, layer="communes")
lab = rasterize(((g, i + 1) for i, g in enumerate(com.geometry)), out_shape=shp, transform=tr, fill=0, dtype="int32")
rav = gpd.read_file(B, layer="ravines_observees")
rm = rasterize(((g, 1) for g in rav.geometry), out_shape=shp, transform=tr, fill=0, dtype="uint8") > 0

rep = {"statut": "PROVISOIRE - table non validée", "table": "parametres/table_c_worldcover.json", "variantes": {}}
for var in ("bas", "central", "haut"):
    vals = class_values(table, var)
    c = c_from_fractions(fr, vals, table["seuil_hors_domaine"]).astype("float32")
    with rasterio.open(OCC / f"facteur_c_{var}_30m.tif", "w", **prof) as o:
        o.write(c, 1)
        o.update_tags(STATUT="PROVISOIRE, table non validee", VARIANTE=var,
                      VALEURS=json.dumps({k: v for k, v in vals.items()}))
    v = c[pm & np.isfinite(c)]
    n = len(com) + 1
    ok = (lab > 0) & np.isfinite(c)
    s = np.bincount(lab[ok], weights=c[ok], minlength=n); k = np.bincount(lab[ok], minlength=n)
    tot = np.bincount(lab[lab > 0], minlength=n)
    rep["variantes"][var] = {
        "valeurs_classes": {table["classes"][str(k_)]["nom"]: (round(x, 5) if x is not None else None) for k_, x in vals.items()},
        "province_mediane": round(float(np.median(v)), 4), "province_moyenne": round(float(v.mean()), 4),
        "province_p95": round(float(np.percentile(v, 95)), 4),
        "part_province_hors_domaine_pct": round(float(100 * np.mean(~np.isfinite(c[pm]))), 1),
        "c_median_ravines_indicatives": round(float(np.nanmedian(c[rm])), 4) if np.isfinite(c[rm]).any() else None,
        "part_ravines_hors_domaine_pct": round(float(100 * np.mean(~np.isfinite(c[rm]))), 1),
        "communes": {r.nom: {"c_moyen": round(float(s[i + 1] / k[i + 1]), 4) if k[i + 1] else None,
                             "hors_domaine_pct": round(float(100 * (1 - k[i + 1] / tot[i + 1])), 1)}
                     for i, r in enumerate(com.itertuples())},
    }
(ROOT / "outputs/facteur_c_rapport.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
for var, d in rep["variantes"].items():
    print(var, {k: d[k] for k in d if k not in ("communes",)})
for nom in ("Kisenso", "Lemba", "Ngaba", "Mont-Ngafula", "Selembao", "Ngaliema", "Maluku", "N'sele", "Makala", "Kimbanseke"):
    print(nom, rep["variantes"]["central"]["communes"][nom])
