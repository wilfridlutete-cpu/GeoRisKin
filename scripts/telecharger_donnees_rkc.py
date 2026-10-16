"""Télécharge et découpe les données ouvertes nécessaires aux facteurs R, K et C.

À lancer sur un ordinateur ayant accès à Internet (l'environnement de développement de
GeoRisKin n'y a pas accès) :

    pip install requests rasterio numpy
    python scripts/telecharger_donnees_rkc.py --tout            # tout
    python scripts/telecharger_donnees_rkc.py --soilgrids        # seulement les sols
    python scripts/telecharger_donnees_rkc.py --chirps 1991 2020 # pluies journalières

Les fichiers sont écrits dans data/raw/{soilgrids,worldcover,chirps}/, découpés sur l'emprise
du domaine hydrologique (15,08–16,68°E ; 5,85–3,90°S). À joindre ensuite dans la conversation.

ATTENTION : script non testé dans l'environnement de développement (pas d'accès réseau) ;
les adresses suivent la documentation des fournisseurs (vérifiée le 16/10/2026) :
- SoilGrids 2.0 (ISRIC, CC BY 4.0) : service WCS maps.isric.org, 250 m ;
- ESA WorldCover 2021 v200 (CC BY 4.0) : tuile S06E015 (15–18°E, 6–3°S), 10 m ;
- CHIRPS 2.0 Afrique journalier, 0,05° (≈5,5 km), domaine public.
"""
from __future__ import annotations

import argparse
import gzip
import io
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw"
BBOX = (15.08, -5.85, 16.68, -3.90)  # lon_min, lat_min, lon_max, lat_max

SOIL_PROPS = ["sand", "silt", "clay", "soc"]
SOIL_DEPTHS = ["0-5cm", "5-15cm", "15-30cm"]
WC_URL = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
          "ESA_WorldCover_10m_2021_v200_S06E015_Map.tif")
CHIRPS_URL = ("https://data.chc.ucsb.edu/products/CHIRPS-2.0/africa_daily/tifs/p05/"
              "{y}/chirps-v2.0.{y}.{m:02d}.{d:02d}.tif.gz")


def get(url, **kw):
    r = requests.get(url, timeout=300, **kw)
    r.raise_for_status()
    return r.content


def soilgrids():
    out = RAW / "soilgrids"
    out.mkdir(parents=True, exist_ok=True)
    for prop in SOIL_PROPS:
        for depth in SOIL_DEPTHS:
            cov = f"{prop}_{depth}_mean"
            dst = out / f"{cov}.tif"
            if dst.exists():
                continue
            url = (f"https://maps.isric.org/mapserv?map=/map/{prop}.map&SERVICE=WCS&VERSION=2.0.1"
                   f"&REQUEST=GetCoverage&COVERAGEID={cov}&FORMAT=image/tiff"
                   f"&SUBSET=long({BBOX[0]},{BBOX[2]})&SUBSET=lat({BBOX[1]},{BBOX[3]})"
                   f"&SUBSETTINGCRS=http://www.opengis.net/def/crs/EPSG/0/4326"
                   f"&OUTPUTCRS=http://www.opengis.net/def/crs/EPSG/0/4326")
            print("SoilGrids", cov)
            dst.write_bytes(get(url))
    print("Unités SoilGrids : sand/silt/clay en g/kg (÷10 -> %), soc en dg/kg (÷100 -> %).")


def worldcover():
    import rasterio
    from rasterio.windows import from_bounds
    out = RAW / "worldcover"
    out.mkdir(parents=True, exist_ok=True)
    dst = out / "worldcover_2021_v200_domaine.tif"
    if dst.exists():
        return
    print("WorldCover : lecture partielle de la tuile S06E015 (COG)")
    with rasterio.open(WC_URL) as s:
        win = from_bounds(*BBOX, transform=s.transform)
        a = s.read(1, window=win)
        prof = s.profile.copy()
        prof.update(width=a.shape[1], height=a.shape[0], transform=s.window_transform(win),
                    compress="deflate", tiled=True)
    with rasterio.open(dst, "w", **prof) as d:
        d.write(a, 1)


def chirps(y0, y1):
    import datetime as dt
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.windows import from_bounds
    out = RAW / "chirps"
    out.mkdir(parents=True, exist_ok=True)
    for y in range(y0, y1 + 1):
        d = dt.date(y, 1, 1)
        while d.year == y:
            dst = out / f"chirps_{d:%Y%m%d}.tif"
            if not dst.exists():
                try:
                    raw = gzip.decompress(get(CHIRPS_URL.format(y=y, m=d.month, d=d.day)))
                except requests.HTTPError as e:
                    print("absent", d, e)
                    d += dt.timedelta(days=1)
                    continue
                with MemoryFile(raw) as mf, mf.open() as s:
                    win = from_bounds(*BBOX, transform=s.transform)
                    a = s.read(1, window=win)
                    prof = s.profile.copy()
                    prof.update(width=a.shape[1], height=a.shape[0], transform=s.window_transform(win),
                                compress="deflate")
                with rasterio.open(dst, "w", **prof) as o:
                    o.write(a, 1)
            d += dt.timedelta(days=1)
        print("CHIRPS", y, "terminé")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tout", action="store_true")
    ap.add_argument("--soilgrids", action="store_true")
    ap.add_argument("--worldcover", action="store_true")
    ap.add_argument("--chirps", nargs=2, type=int, metavar=("ANNEE_DEBUT", "ANNEE_FIN"))
    a = ap.parse_args()
    if not (a.tout or a.soilgrids or a.worldcover or a.chirps):
        ap.print_help()
        sys.exit(1)
    if a.tout or a.soilgrids:
        soilgrids()
    if a.tout or a.worldcover:
        worldcover()
    if a.tout or a.chirps:
        y0, y1 = a.chirps or (1991, 2020)
        chirps(y0, y1)
