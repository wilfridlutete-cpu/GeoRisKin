"""Chargement des facteurs RUSLE sur la fenêtre d'une zone (géométrie WGS84) et propagation
vers l'aval de la surface imperméable ajoutée. Utilisé par le CLI et par Django."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.warp import transform_geom
from rasterio.windows import Window, from_bounds
from shapely.geometry import shape

from .flow_analysis import flow_accumulation
from .scenarios import CODES, Entrees

R_METHODES = {"lo1985": "lo1985", "renard_freimund1994": "renard_freimund1994", "roose1977": "roose1977_a0.50"}
PERIODES = ("1991-2020", "1991-2025", "2011-2025")


def charger(data_dir: Path, params_dir: Path, zone_wgs84: dict, periode: str = "1991-2020", marge_m: float = 0.0):
    if periode not in PERIODES:
        raise ValueError(f"période inconnue : {periode}")
    P = Path(data_dir) / "processed"
    ref = P / "topo/pente_deg.tif"
    with rasterio.open(ref) as s:
        crs, full_tr, H, W = s.crs, s.transform, s.height, s.width
        geom = transform_geom("EPSG:4326", crs, zone_wgs84)
        b = shape(geom).bounds
        win = from_bounds(b[0] - marge_m, b[1] - marge_m, b[2] + marge_m, b[3] + marge_m, full_tr)
        win = win.round_offsets().round_lengths()
        win = Window(max(0, win.col_off), max(0, win.row_off),
                     min(win.width, W - max(0, win.col_off)), min(win.height, H - max(0, win.row_off)))
        tr = s.window_transform(win)
        pente = s.read(1, window=win)
    shp = (int(win.height), int(win.width))
    zone = rasterize([(geom, 1)], out_shape=shp, transform=tr, fill=0, dtype="uint8") > 0

    def rd(rel):
        with rasterio.open(P / rel) as s:
            return s.read(1, window=win).astype("float32")

    conc = rd("topo/ecoulement_concentre.tif") > 0
    LS = {"desmet_govers": np.where(conc, np.nan, rd("topo/ls_rusle.tif")),
          "moore_burch": np.where(conc, np.nan, rd("topo/ls_variante_moore_burch.tif"))}
    R_ref = {k: rd(f"pluie/facteur_r_{v}_1991-2020_30m.tif") for k, v in R_METHODES.items()}
    R_scen = {k: rd(f"pluie/facteur_r_{v}_{periode}_30m.tif") for k, v in R_METHODES.items()}
    fracs = {c: rd(f"occupation/worldcover_frac_{n}.tif") for c, n in CODES.items()}
    table_c = json.loads((Path(params_dir) / "table_c_worldcover.json").read_text(encoding="utf-8"))
    e = Entrees(K=rd("sols/facteur_k_williams_30m.tif"), LS=LS, R_ref=R_ref, R_scen=R_scen, fracs=fracs,
                pente_deg=pente, zone=zone, cell_ha=abs(tr.a * tr.e) / 1e4, table_c=table_c,
                meta={"window": win, "transform": tr, "crs": crs, "full_shape": (H, W)})
    return e


def propagation_impermeable(data_dir: Path, e: Entrees, bati_ajoute: np.ndarray, seuil_ha: float = 1.0):
    """Surface imperméable ajoutée, cumulée vers l'aval (D8) sur toute la grille."""
    if bati_ajoute.sum() <= 0:
        return {"lineaire_aval_km_recevant_plus_de_1ha": 0.0, "surface_impermeable_ajoutee_ha": 0.0}
    P = Path(data_dir) / "processed"
    with rasterio.open(P / "topo/direction_d8.tif") as s:
        fdir = s.read(1)
    win = e.meta["window"]
    w = np.zeros(fdir.shape, "float64")
    r0, c0 = int(win.row_off), int(win.col_off)
    w[r0:r0 + bati_ajoute.shape[0], c0:c0 + bati_ajoute.shape[1]] = bati_ajoute * e.cell_ha
    acc = flow_accumulation(fdir, fdir != 255, w)
    hors_zone = np.ones(fdir.shape, bool)
    hors_zone[r0:r0 + e.zone.shape[0], c0:c0 + e.zone.shape[1]] &= ~e.zone
    n = int(((acc >= seuil_ha) & hors_zone).sum())
    return {"surface_impermeable_ajoutee_ha": round(float(bati_ajoute.sum() * e.cell_ha), 1),
            "lineaire_aval_km_recevant_plus_de_1ha": round(n * abs(e.meta["transform"].a) / 1000, 1),
            "note": "cellules hors zone dont la surface bâtie amont augmente d'au moins 1 ha (chemin D8) ; "
                    "indicateur de report du ruissellement vers l'aval, pas un débit"}
