"""Télécharge les pluies MENSUELLES CHIRPS 2.0 (0,05° ≈ 5,5 km, domaine public, UCSB-CHC)
sur Kinshasa (15,08–16,68°E ; 5,85–3,90°S) et les regroupe en UN seul petit fichier :
    chirps_mensuel_kinshasa_<debut>-<fin>.tif   (1 bande par mois, pluie en mm)

Utilisation (Windows, PowerShell) :
    pip install requests rasterio numpy
    python chirps_kinshasa.py                  # 1991-2020 (normale climatique, 360 mois)
    python chirps_kinshasa.py 2001 2020        # autre période

Chaque fichier mensuel d'Afrique (~3 Mo compressé) est téléchargé, découpé en mémoire puis
oublié : seul le découpage est conservé (dossier chirps_mois/). Le script peut être relancé
après une coupure : les mois déjà obtenus ne sont pas retéléchargés.
"""
import gzip
import sys
import time
from pathlib import Path

import numpy as np
import rasterio
import requests
from rasterio.io import MemoryFile
from rasterio.windows import from_bounds

BBOX = (15.08, -5.85, 16.68, -3.90)
URLS = [
    "https://data.chc.ucsb.edu/products/CHIRPS-2.0/africa_monthly/tifs/chirps-v2.0.{y}.{m:02d}.tif.gz",
    "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_monthly/tifs/chirps-v2.0.{y}.{m:02d}.tif.gz",
]
OUT = Path("chirps_mois")
OUT.mkdir(exist_ok=True)


def fetch(y, m):
    last = None
    for tpl in URLS:
        url = tpl.format(y=y, m=m)
        for essai in range(3):
            try:
                r = requests.get(url, timeout=180)
                if r.status_code == 404:
                    break
                r.raise_for_status()
                return gzip.decompress(r.content), url
            except Exception as e:  # réseau instable : on réessaie
                last = e
                time.sleep(5 * (essai + 1))
    raise RuntimeError(f"{y}-{m:02d} introuvable ({last})")


def main(y0=1991, y1=2020):
    for y in range(y0, y1 + 1):
        for m in range(1, 13):
            dst = OUT / f"chirps_{y}_{m:02d}.tif"
            if dst.exists():
                continue
            raw, url = fetch(y, m)
            with MemoryFile(raw) as mf, mf.open() as s:
                win = from_bounds(*BBOX, transform=s.transform).round_offsets().round_lengths()
                a = s.read(1, window=win)
                prof = s.profile.copy()
                prof.update(driver="GTiff", width=a.shape[1], height=a.shape[0],
                            transform=s.window_transform(win), compress="deflate")
            with rasterio.open(dst, "w", **prof) as o:
                o.write(a, 1)
            print(f"{y}-{m:02d} ok  ({url.split('/')[-3]})")
    files = sorted(OUT.glob("chirps_*.tif"))
    files = [f for f in files if y0 <= int(f.stem.split("_")[1]) <= y1]
    with rasterio.open(files[0]) as s:
        prof = s.profile.copy()
    prof.update(count=len(files), dtype="float32", nodata=-9999.0)
    out = Path(f"chirps_mensuel_kinshasa_{y0}-{y1}.tif")
    with rasterio.open(out, "w", **prof) as o:
        for i, f in enumerate(files, 1):
            with rasterio.open(f) as s:
                a = s.read(1).astype("float32")
                if s.nodata is not None:
                    a[a == s.nodata] = -9999.0
            o.write(a, i)
            o.set_band_description(i, f.stem.replace("chirps_", ""))
        o.update_tags(SOURCE="CHIRPS 2.0 mensuel, UCSB Climate Hazards Center, domaine public", UNITE="mm/mois")
    print(f"\nTERMINÉ : {out.resolve()}  ({len(files)} mois) -> à joindre dans la conversation")


if __name__ == "__main__":
    args = [int(a) for a in sys.argv[1:3]]
    main(*args) if len(args) == 2 else main()
