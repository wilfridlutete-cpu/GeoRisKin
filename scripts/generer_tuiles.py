"""Génère les tuiles PNG (XYZ, Web Mercator) des couches raster de parametres/couches.json.

Sans gdal2tiles : chaque zoom est obtenu en reprojetant directement les VALEURS sur la grille
de tuiles (bilinéaire pour le continu au zoom max, moyenne aux zooms inférieurs, plus proche
voisin pour le catégoriel), puis en appliquant la palette. NaN / sans donnée = transparent.

Usage : python scripts/generer_tuiles.py [id_couche ...] [--zmin 8] [--zmax 13]
Sortie : data/tuiles/<id>/<z>/<x>/<y>.png  (servies par Django sous /tuiles/ en développement)
"""
import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import rasterio
from matplotlib import colormaps
from PIL import Image
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.warp import reproject, transform_bounds

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data/processed"
OUT = ROOT / "data/tuiles"
R_EARTH = 6378137.0
ORIGIN = math.pi * R_EARTH
TILE = 256


def tile_range(bounds_3857, z):
    res = 2 * ORIGIN / (TILE * 2 ** z)
    x0 = int((bounds_3857[0] + ORIGIN) // (res * TILE))
    x1 = int((bounds_3857[2] + ORIGIN) // (res * TILE))
    y0 = int((ORIGIN - bounds_3857[3]) // (res * TILE))
    y1 = int((ORIGIN - bounds_3857[1]) // (res * TILE))
    return x0, x1, y0, y1, res


def lut_continu(c):
    cmap = colormaps[c["palette"]]
    return (cmap(np.linspace(0, 1, 256)) * 255).astype("uint8")


def colorize(v, c):
    h, w = v.shape
    rgba = np.zeros((h, w, 4), "uint8")
    if c["type"] == "categoriel":
        for code, (_, col) in c["classes"].items():
            m = v == int(code)
            rgba[m] = [int(col[i:i + 2], 16) for i in (1, 3, 5)] + [255]
        return rgba
    ok = np.isfinite(v)
    if c["echelle"] == "log":
        lo, hi = math.log10(c["min"]), math.log10(c["max"])
        t = (np.log10(np.clip(np.where(ok, v, c["min"]), c["min"], c["max"])) - lo) / (hi - lo)
    else:
        t = (np.clip(np.where(ok, v, c["min"]), c["min"], c["max"]) - c["min"]) / (c["max"] - c["min"])
    idx = np.round(t * 255).astype("uint8")
    rgba[:] = lut_continu(c)[idx]
    rgba[~ok, 3] = 0
    return rgba


def ensure_derived():
    f = PROC / "erosion/incertitude_p90_sur_p10.tif"
    if f.exists():
        return
    with rasterio.open(PROC / "erosion/perte_sol_p10_t_ha_an_30m.tif") as a, \
            rasterio.open(PROC / "erosion/perte_sol_p90_t_ha_an_30m.tif") as b:
        p10, p90, prof = a.read(1), b.read(1), a.profile
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(p10 > 0, p90 / p10, np.nan).astype("float32")
    with rasterio.open(f, "w", **prof) as o:
        o.write(r, 1)
        o.update_tags(UNITE="facteur", DESCRIPTION="P90/P10 de l'ensemble RUSLE")


def write_legend(c):
    d = OUT / c["id"]
    d.mkdir(parents=True, exist_ok=True)
    if c["type"] == "categoriel":
        leg = [{"valeur": v[0], "couleur": v[1]} for v in c["classes"].values()]
    else:
        lut = lut_continu(c)
        leg = []
        for t in np.linspace(0, 1, 7):
            if c["echelle"] == "log":
                v = 10 ** (math.log10(c["min"]) + t * (math.log10(c["max"]) - math.log10(c["min"])))
            else:
                v = c["min"] + t * (c["max"] - c["min"])
            r, g, b, _ = lut[int(round(t * 255))]
            leg.append({"valeur": float(f"{v:.3g}"), "couleur": f"#{r:02x}{g:02x}{b:02x}"})
    (d / "legende.json").write_text(json.dumps(leg, ensure_ascii=False), encoding="utf-8")


def tile_terrarium(zmin=8, zmax=12):
    """Tuiles d'élévation codées « terrarium » pour le relief 3D de MapLibre (raster-dem)."""
    with rasterio.open(PROC / "topo/altitude_m.tif") as s:
        data = s.read(1).astype("float32")
        if s.nodata is not None and not math.isnan(s.nodata):
            data[data == s.nodata] = np.nan
        src_tr, src_crs = s.transform, s.crs
        b3857 = transform_bounds(s.crs, "EPSG:3857", *s.bounds)
    fill = float(np.nanpercentile(data, 1))
    n = 0
    for z in range(zmin, zmax + 1):
        x0, x1, y0, y1, res = tile_range(b3857, z)
        W, H = (x1 - x0 + 1) * TILE, (y1 - y0 + 1) * TILE
        tr = Affine(res, 0, -ORIGIN + x0 * TILE * res, 0, -res, ORIGIN - y0 * TILE * res)
        dst = np.full((H, W), np.nan, "float32")
        reproject(data, dst, src_transform=src_tr, src_crs=src_crs, dst_transform=tr, dst_crs="EPSG:3857",
                  src_nodata=np.nan, dst_nodata=np.nan,
                  resampling=Resampling.bilinear if z == zmax else Resampling.average)
        v = np.where(np.isfinite(dst), dst, fill).astype("float64") + 32768.0
        rgb = np.stack([np.floor(v / 256), np.floor(v) % 256, np.floor((v - np.floor(v)) * 256)], -1).astype("uint8")
        for ty in range(y1 - y0 + 1):
            for tx in range(x1 - x0 + 1):
                d = OUT / "mnt_terrarium" / str(z) / str(x0 + tx)
                d.mkdir(parents=True, exist_ok=True)
                Image.fromarray(rgb[ty * TILE:(ty + 1) * TILE, tx * TILE:(tx + 1) * TILE], "RGB").save(d / f"{y0 + ty}.png")
                n += 1
    return n


def tile_layer(c, zmin, zmax):
    src_path = PROC / c["fichier"]
    with rasterio.open(src_path) as s:
        data = s.read(1)
        nod = s.nodata
        if c["type"] == "categoriel":
            data = data.astype("float32")
            data[data == (nod if nod is not None else 0)] = np.nan
        else:
            data = data.astype("float32")
            if nod is not None and not (isinstance(nod, float) and math.isnan(nod)):
                data[data == nod] = np.nan
        src_tr, src_crs = s.transform, s.crs
        b3857 = transform_bounds(s.crs, "EPSG:3857", *s.bounds)
    n = 0
    for z in range(zmin, zmax + 1):
        x0, x1, y0, y1, res = tile_range(b3857, z)
        W, H = (x1 - x0 + 1) * TILE, (y1 - y0 + 1) * TILE
        tr = Affine(res, 0, -ORIGIN + x0 * TILE * res, 0, -res, ORIGIN - y0 * TILE * res)
        dst = np.full((H, W), np.nan, "float32")
        if c["type"] == "categoriel":
            rs = Resampling.nearest if z == zmax else Resampling.mode
        else:
            rs = Resampling.bilinear if z == zmax else Resampling.average
        reproject(data, dst, src_transform=src_tr, src_crs=src_crs, dst_transform=tr, dst_crs="EPSG:3857",
                  src_nodata=np.nan, dst_nodata=np.nan, resampling=rs)
        rgba = colorize(dst, c)
        for ty in range(y1 - y0 + 1):
            for tx in range(x1 - x0 + 1):
                t = rgba[ty * TILE:(ty + 1) * TILE, tx * TILE:(tx + 1) * TILE]
                if not t[..., 3].any():
                    continue
                d = OUT / c["id"] / str(z) / str(x0 + tx)
                d.mkdir(parents=True, exist_ok=True)
                Image.fromarray(t, "RGBA").save(d / f"{y0 + ty}.png", optimize=True)
                n += 1
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--zmin", type=int, default=8)
    ap.add_argument("--zmax", type=int, default=13)
    ap.add_argument("--legendes", action="store_true", help="ne régénère que les légendes")
    ap.add_argument("--relief3d", action="store_true", help="génère seulement les tuiles d'élévation 3D")
    a = ap.parse_args()
    ensure_derived()
    if a.relief3d:
        print("mnt_terrarium:", tile_terrarium(), "tuiles")
        raise SystemExit

    cat = json.loads((ROOT / "parametres/couches.json").read_text(encoding="utf-8"))["couches"]
    for c in cat:
        if a.ids and c["id"] not in a.ids:
            continue
        write_legend(c)
        if a.legendes:
            continue
        t0 = time.time()
        n = tile_layer(c, a.zmin, a.zmax)
        print(f"{c['id']}: {n} tuiles en {time.time() - t0:.0f} s")
