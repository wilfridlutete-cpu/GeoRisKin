"""Lecture du catalogue des couches (parametres/couches.json) et interrogation ponctuelle des rasters."""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import rasterio
from django.conf import settings
from rasterio.warp import transform as warp_transform


def catalogue_path() -> Path:
    return settings.PROJECT_ROOT / "parametres" / "couches.json"


@lru_cache(maxsize=1)
def _load(mtime: float):
    return json.loads(catalogue_path().read_text(encoding="utf-8"))["couches"]


def couches():
    return _load(catalogue_path().stat().st_mtime)


@lru_cache(maxsize=64)
def _dataset(path: str):
    return rasterio.open(path)


def valeurs_au_point(lon: float, lat: float):
    """Valeur de chaque couche interrogeable au point (lon, lat WGS84). None = hors donnée."""
    out = []
    for c in couches():
        if not c.get("requete"):
            continue
        f = Path(settings.GEORISKIN_DATA_DIR) / "processed" / c["fichier"]
        if not f.exists():
            continue
        ds = _dataset(str(f))
        xs, ys = warp_transform("EPSG:4326", ds.crs, [lon], [lat])
        row, col = ds.index(xs[0], ys[0])
        val = None
        if 0 <= row < ds.height and 0 <= col < ds.width:
            v = ds.read(1, window=((row, row + 1), (col, col + 1)))[0, 0]
            v = float(v)
            nod = ds.nodata
            if not math.isnan(v) and not (nod is not None and not math.isnan(nod) and v == nod):
                val = v
        item = {"id": c["id"], "titre": c["titre"], "unite": c.get("unite", ""), "statut": c.get("statut", "")}
        if c["type"] == "categoriel":
            lab = c["classes"].get(str(int(val))) if val is not None else None
            item["valeur"] = lab[0] if lab else None
        else:
            item["valeur"] = None if val is None else float(f"{val:.4g}")
        out.append(item)
    return out
