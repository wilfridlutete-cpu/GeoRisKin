"""Exécution d'un scénario : chargement des facteurs sur la zone, calcul, images de résultat."""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import rasterio
from django.conf import settings
from PIL import Image
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject

sys.path.insert(0, str(settings.PROJECT_ROOT))
from engine.scenario_donnees import PERIODES, charger, propagation_impermeable  # noqa: E402
from engine.scenarios import executer  # noqa: E402

VERSION = "scenarios-1.0"
ZONE_MAX_KM2 = float(getattr(settings, "GEORISKIN_SCENARIO_MAX_KM2", 1000))
CLASSES_VALIDES = {10, 20, 30, 40, 60, 90}


def table_pratiques():
    return json.loads((settings.PROJECT_ROOT / "parametres/table_p_pratiques.json").read_text(encoding="utf-8"))["pratiques"]


def valider(p: dict) -> dict:
    """Contrôle et normalise les paramètres reçus de l'interface."""
    out = {"periode_pluie": p.get("periode_pluie", "1991-2020")}
    if out["periode_pluie"] not in PERIODES:
        raise ValueError(f"période de pluie inconnue (choix : {', '.join(PERIODES)})")
    for k, vers in (("reboisement", 10), ("urbanisation", 50)):
        v = p.get(k)
        if v:
            part = float(v.get("part", 0))
            classes = [int(c) for c in v.get("classes", [])]
            if not 0 <= part <= 1:
                raise ValueError(f"{k} : part entre 0 et 1")
            if not set(classes) <= CLASSES_VALIDES:
                raise ValueError(f"{k} : classes autorisées {sorted(CLASSES_VALIDES)}")
            if part > 0 and classes:
                out[k] = {"part": part, "classes": classes}
    pr = p.get("pratique")
    if pr and pr.get("id"):
        tab = table_pratiques()
        if pr["id"] not in tab:
            raise ValueError(f"pratique inconnue (choix : {', '.join(tab)})")
        cible = pr.get("cible", "cultures")
        if cible not in ("cultures", "tout"):
            raise ValueError("cible : 'cultures' ou 'tout'")
        out["pratique"] = {"id": pr["id"], "cible": cible, "pente_min_deg": float(pr.get("pente_min_deg", 0))}
    if not any(k in out for k in ("reboisement", "urbanisation", "pratique")) and out["periode_pluie"] == "1991-2020":
        raise ValueError("aucune modification : choisissez au moins une intervention ou une autre période de pluie")
    return out


def _png_wgs84(arr, tr, crs, path: Path, coloriser):
    """Reprojette un tableau en WGS84, le colore et l'écrit en PNG ; renvoie les 4 coins pour MapLibre."""
    h, w = arr.shape
    left, top = tr.c, tr.f
    right, bottom = left + w * tr.a, top + h * tr.e
    dtr, dw, dh = calculate_default_transform(crs, "EPSG:4326", w, h, left, bottom, right, top)
    dst = np.full((dh, dw), np.nan, "float32")
    reproject(arr.astype("float32"), dst, src_transform=tr, src_crs=crs, dst_transform=dtr, dst_crs="EPSG:4326",
              src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.nearest)
    Image.fromarray(coloriser(dst), "RGBA").save(path, optimize=True)
    l, t = dtr.c, dtr.f
    r, b = l + dw * dtr.a, t + dh * dtr.e
    return [[l, t], [r, t], [r, b], [l, b]]


def _lut(stops):
    xs = np.linspace(0, 1, len(stops))
    cols = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in stops], float)
    t = np.linspace(0, 1, 256)
    return np.stack([np.interp(t, xs, cols[:, k]) for k in range(3)], -1).astype("uint8")


DIV = _lut(["#1a9850", "#91cf60", "#d9ef8b", "#f7f7f7", "#fee08b", "#fc8d59", "#d73027"])
SEQ = _lut(["#fcfea4", "#fbb51a", "#ed6825", "#ba3655", "#781c6d", "#34095f", "#000003"])
DIFF_MAX = 50.0


def col_diff(a):
    rgba = np.zeros((*a.shape, 4), "uint8")
    ok = np.isfinite(a)
    a0 = np.nan_to_num(a)
    t = np.clip(np.sign(a0) * np.log10(1 + np.abs(a0)) / math.log10(1 + DIFF_MAX), -1, 1)
    idx = np.clip(np.round((t + 1) / 2 * 255), 0, 255).astype(int)
    rgba[..., :3] = DIV[idx]
    rgba[..., 3] = np.where(ok, 220, 0)
    return rgba


def col_sorti(a):
    rgba = np.zeros((*a.shape, 4), "uint8")
    m = np.nan_to_num(a) > 0
    rgba[m] = [90, 90, 90, 200]
    return rgba


def col_perte(a):
    rgba = np.zeros((*a.shape, 4), "uint8")
    ok = np.isfinite(a)
    t = (np.log10(np.clip(np.nan_to_num(a, nan=0.1), 0.1, 200)) + 1) / (math.log10(200) + 1)
    rgba[..., :3] = SEQ[np.round(t * 255).astype(int)]
    rgba[..., 3] = np.where(ok, 220, 0)
    return rgba


def executer_scenario(sc) -> None:
    t0 = time.time()
    p = sc.parametres
    zone = sc.zone.transform(4326, clone=True)
    zone_geojson = json.loads(zone.geojson)
    data, params = settings.GEORISKIN_DATA_DIR, settings.PROJECT_ROOT / "parametres"
    e = charger(data, params, zone_geojson, p["periode_pluie"])
    pratique = None
    if "pratique" in p:
        pratique = table_pratiques()[p["pratique"]["id"]]
    res, cartes = executer(e, reboisement=p.get("reboisement"), urbanisation=p.get("urbanisation"),
                           pratique=pratique, cible=p.get("pratique", {}).get("cible", "cultures"),
                           pente_min_deg=p.get("pratique", {}).get("pente_min_deg", 0.0))
    res["impermeable"] = propagation_impermeable(data, e, cartes["bati_ajoute"])
    if pratique:
        res["pratique"] = {"nom": pratique["nom"], "statut": pratique["statut"], "sources": pratique["sources"]}
    out = Path(settings.GEORISKIN_SCENARIOS_DIR) / str(sc.pk)
    out.mkdir(parents=True, exist_ok=True)
    tr, crs = e.meta["transform"], e.meta["crs"]
    images = {}
    for nom, arr, col in (("difference", cartes["difference"], col_diff),
                          ("perte_scenario", cartes["perte_scenario"], col_perte),
                          ("sorti_du_domaine", cartes["sorti_du_domaine"].astype("float32"), col_sorti)):
        coins = _png_wgs84(arr, tr, crs, out / f"{nom}.png", col)
        images[nom] = {"url": f"{settings.GEORISKIN_SCENARIOS_URL}{sc.pk}/{nom}.png", "coordonnees": coins}
    prof = {"driver": "GTiff", "dtype": "float32", "count": 1, "width": arr.shape[1], "height": arr.shape[0],
            "crs": crs, "transform": tr, "nodata": np.nan, "compress": "deflate"}
    with rasterio.open(out / "difference_t_ha_an.tif", "w", **prof) as o:
        o.write(cartes["difference"].astype("float32"), 1)
        o.update_tags(UNITE="t/ha/an", DESCRIPTION="mediane des differences scenario - reference (membre a membre)")
    res["images"] = images
    res["telechargement_geotiff"] = f"{settings.GEORISKIN_SCENARIOS_URL}{sc.pk}/difference_t_ha_an.tif"
    res["legende_difference"] = {"min": -DIFF_MAX, "max": DIFF_MAX, "unite": "t/ha/an", "echelle": "log symétrique",
                                 "couleurs": ["#1a9850", "#91cf60", "#d9ef8b", "#f7f7f7", "#fee08b", "#fc8d59", "#d73027"]}
    res["rappel"] = ("Comparaison RUSLE (érosion en nappe et rigoles) membre à membre sur l'ensemble d'hypothèses ; "
                     "estimation non validée. Les ravines ne sont pas simulées.")
    sc.resultats = res
    sc.statut = "termine"
    sc.version_moteur = VERSION
    sc.duree_s = round(time.time() - t0, 2)
    sc.save()
