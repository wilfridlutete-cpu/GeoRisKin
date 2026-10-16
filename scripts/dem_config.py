"""Paramètres communs aux scripts : source et résolution du MNT.

Résolution de travail retenue : 30 m (décision du 16/10/2026).
- Source principale : tuiles SRTM DTED2 complètes (1", ≈30 m) dans data/raw/srtm_dted2/.
- Repli (en attendant ces tuiles) : vues réduites .ovr (≈2") dans data/raw/srtm_dted2_ovr/,
  utilisées à 60 m ; jamais sur-échantillonnées à 30 m (ce serait une précision fictive).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw"
DT2_DIR = RAW / "srtm_dted2"
OVR_DIR = RAW / "srtm_dted2_ovr"

# Domaine hydrologique : tous les bassins qui traversent la province (calcul à 60 m du
# 16/10 : 15,13–16,62°E ; 5,78–4,00°S) + marge. Réduit la mémoire par rapport aux 4 tuiles.
DOMAIN_WGS84 = (15.08, -5.85, 16.68, -3.90)  # nord : jusqu'à 3,90°S pour Maluku (tuile S04)


def dem_source():
    # .DT2 (OSFAC/NGA) et, pour compléter, GeoTIFF/HGT SRTM 1" (EarthExplorer) ou Copernicus GLO-30
    pats = ("*.DT2", "*.dt2", "*.tif", "*.hgt")
    dt2 = sorted({f for p in pats for f in DT2_DIR.glob(p)}, key=lambda f: (not f.name.startswith("DTED"), f.name)) \
        if DT2_DIR.exists() else []  # SRTM d'abord : prioritaire en cas de recouvrement
    if dt2:
        return {"kind": "dt2", "files": dt2, "res": 30.0, "label": "srtm1s"}
    return {"kind": "ovr", "files": sorted(OVR_DIR.glob("DTED_*.DT2.ovr")), "res": 60.0, "label": "srtm2s"}


def dem_paths(src=None):
    src = src or dem_source()
    r = int(src["res"])
    proc = ROOT / "data/processed"
    return {"domaine": proc / f"mnt_{src['label']}_domaine_utm33s_{r}m.tif",
            "kinshasa": proc / f"mnt_{src['label']}_kinshasa_utm33s_{r}m.tif",
            "mosaique": ROOT / "data/interim" / f"{src['label']}_mosaique_wgs84.tif"}
