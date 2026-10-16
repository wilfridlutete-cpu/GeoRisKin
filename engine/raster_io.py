"""Lecture, géoréférencement, mosaïque et reprojection des MNT.

Module du moteur GeoRisKin, indépendant de tout framework web.
Toutes les fonctions reçoivent des chemins ou des tableaux NumPy et des
paramètres explicites ; aucune valeur par défaut cachée sur les données.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.merge import merge
from rasterio.transform import Affine
from rasterio.warp import calculate_default_transform, reproject, Resampling

DTED_NODATA = -32767  # valeur vide normalisée DTED/SRTM
WGS84 = CRS.from_epsg(4326)
UTM33S = CRS.from_epsg(32733)  # WGS 84 / UTM zone 33S, utilisée par les shapefiles du projet

_TILE_RE = re.compile(r"DTED_([EW])(\d{3})_([NS])(\d{2})", re.IGNORECASE)


def dted_tile_origin(name: str) -> tuple[float, float]:
    """Renvoie (lon, lat) du coin sud-ouest d'une tuile DTED à partir de son nom.

    Convention DTED/SRTM : le nom désigne le coin SO. « E015_S05 » couvre
    15°E–16°E et 5°S–4°S. Vérifié avec DTED_OriginLatitude=0050000S et
    DTED_OriginLongitude=0150000E dans le fichier .aux.xml du projet.
    """
    m = _TILE_RE.search(name)
    if not m:
        raise ValueError(f"Nom de tuile DTED non reconnu : {name}")
    ew, lon, ns, lat = m.groups()
    lon = float(lon) * (1 if ew.upper() == "E" else -1)
    lat = float(lat) * (1 if ns.upper() == "N" else -1)
    return lon, lat


def dted_overview_transform(name: str, width: int, height: int) -> Affine:
    """Géotransformation d'une vue réduite (.ovr) GDAL d'une tuile DTED niveau 2.

    Une tuile DTED2 de 1°×1° contient 3601×3601 échantillons espacés de 1"
    (pixel-is-point). GDAL l'expose comme une grille de pixels de 1" dont
    l'emprise déborde d'un demi-pixel : [lon0-0.5", lon0+1°+0.5"].
    Une vue réduite de n pixels couvre exactement la même emprise ; la taille
    de pixel est donc (1° + 1") / n.
    """
    lon0, lat0 = dted_tile_origin(name)
    half = 0.5 / 3600.0
    extent = 1.0 + 2 * half
    return Affine(extent / width, 0.0, lon0 - half,
                  0.0, -extent / height, lat0 + 1.0 + half)


def georeference_dted_overview(src: Path, dst: Path) -> dict:
    """Écrit un GeoTIFF géoréférencé à partir d'un .ovr DTED non géoréférencé."""
    with rasterio.open(src) as s:
        arr = s.read(1)
        nodata = s.nodata if s.nodata is not None else DTED_NODATA
    h, w = arr.shape
    tr = dted_overview_transform(src.name, w, h)
    profile = dict(driver="GTiff", width=w, height=h, count=1, dtype=arr.dtype,
                   crs=WGS84, transform=tr, nodata=nodata, compress="deflate",
                   tiled=True, blockxsize=256, blockysize=256)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(dst, "w", **profile) as d:
        d.write(arr, 1)
        d.update_tags(SOURCE=src.name, VERTICAL_DATUM="EGM96 (geoide)",
                      UNITS="m", NOTE="Vue reduite 1/2 (≈2 secondes d'arc) d'une tuile SRTM DTED2")
    return {"file": dst.name, "shape": [h, w], "pixel_deg": tr.a,
            "nodata_count": int((arr == nodata).sum())}


def mosaic(paths: list[Path], dst: Path) -> None:
    """Mosaïque de tuiles ayant le même SCR et la même résolution."""
    srcs = [rasterio.open(p) for p in paths]
    try:
        res = {round(s.res[0], 12) for s in srcs}
        crs = {s.crs.to_string() for s in srcs}
        if len(res) != 1 or len(crs) != 1:
            raise ValueError(f"Tuiles incompatibles : résolutions {res}, SCR {crs}")
        # float32 : les tuiles peuvent mélanger entiers (DTED) et réels (Copernicus) ;
        # ordre de la liste = priorité en cas de recouvrement.
        nod = next((x.nodata for x in srcs if x.nodata is not None), -32767)
        arr, tr = merge(srcs, nodata=nod, dtype="float32")
        profile = srcs[0].profile.copy()
    finally:
        for s in srcs:
            s.close()
    # toujours un GeoTIFF, quel que soit le format des tuiles (DTED est en lecture seule ici)
    profile = {k: v for k, v in profile.items() if k in ("crs", "count")}
    profile.update(dtype="float32", nodata=nod)
    profile.update(driver="GTiff", width=arr.shape[2], height=arr.shape[1], transform=tr,
                   compress="deflate", tiled=True, blockxsize=256, blockysize=256, BIGTIFF="IF_SAFER")
    with rasterio.open(dst, "w", **profile) as d:
        d.write(arr)


def reproject_dem(src: Path, dst: Path, dst_crs: CRS, resolution: float,
                  bounds_wgs84: tuple[float, float, float, float] | None = None,
                  resampling: Resampling = Resampling.bilinear) -> dict:
    """Reprojette (et découpe optionnellement) un MNT vers un SCR métrique.

    Les pixels NoData de la source restent NoData (pas de comblement implicite).
    La grille de sortie est alignée sur des multiples entiers de `resolution`
    pour que tous les rasters futurs (facteurs RUSLE) puissent s'y caler.
    """
    with rasterio.open(src) as s:
        left, bottom, right, top = bounds_wgs84 or s.bounds
        tr, w, h = calculate_default_transform(s.crs, dst_crs, s.width, s.height,
                                               left=left, bottom=bottom, right=right, top=top,
                                               resolution=resolution)
        # alignement de la grille sur des multiples de la résolution
        x0 = np.floor(tr.c / resolution) * resolution
        y0 = np.ceil(tr.f / resolution) * resolution
        w += 1
        h += 1
        tr = Affine(resolution, 0, x0, 0, -resolution, y0)
        out = np.full((h, w), np.nan, dtype="float32")
        reproject(source=rasterio.band(s, 1), destination=out,
                  src_transform=s.transform, src_crs=s.crs, src_nodata=s.nodata,
                  dst_transform=tr, dst_crs=dst_crs, dst_nodata=np.nan,
                  resampling=resampling)
        tags = s.tags()
    profile = dict(driver="GTiff", width=w, height=h, count=1, dtype="float32",
                   crs=dst_crs, transform=tr, nodata=np.nan, compress="deflate",
                   predictor=3, tiled=True, blockxsize=256, blockysize=256)
    with rasterio.open(dst, "w", **profile) as d:
        d.write(out, 1)
        d.update_tags(**tags, RESAMPLING=resampling.name, UNITS="m",
                      HORIZONTAL_CRS=dst_crs.to_string())
    return {"shape": [h, w], "resolution_m": resolution,
            "nodata_count": int(np.isnan(out).sum())}


@dataclass
class DemReport:
    path: str
    crs: str
    resolution: list
    shape: list
    bounds: list
    nodata_pixels: int
    valid_pixels: int
    z_min: float
    z_max: float
    z_mean: float
    z_p01: float
    z_p99: float


def dem_report(path: Path) -> DemReport:
    """Contrôle qualité d'un MNT : SCR, résolution, NoData, statistiques."""
    with rasterio.open(path) as s:
        a = s.read(1, masked=True).astype("float64")
        if s.nodata is not None and np.isnan(s.nodata):
            a = np.ma.masked_invalid(a)
        v = a.compressed()
        return DemReport(str(path), s.crs.to_string(), list(s.res), [s.height, s.width],
                         list(s.bounds), int(a.mask.sum()), int(v.size),
                         float(v.min()), float(v.max()), float(v.mean()),
                         float(np.percentile(v, 1)), float(np.percentile(v, 99)))


def write_json(obj, path: Path) -> None:
    if hasattr(obj, "__dataclass_fields__"):
        obj = asdict(obj)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
