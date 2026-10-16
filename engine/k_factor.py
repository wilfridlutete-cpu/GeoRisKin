"""Facteur K (érodibilité du sol) à partir de la texture et du carbone organique.

Méthode : équation EPIC de Williams (1995), utilisable avec SoilGrids (sable, limon,
argile, carbone organique) :
    K = fcsand · fcl-si · forgc · fhisand · 0,1317
    fcsand = 0,2 + 0,3 · exp[−0,0256 · SAN · (1 − SIL/100)]
    fcl-si = [SIL / (CLA + SIL)]^0,3
    forgc  = 1 − 0,25 · C / (C + exp(3,72 − 2,95 · C))
    fhisand = 1 − 0,7 · SN1 / (SN1 + exp(−5,51 + 22,9 · SN1)),  SN1 = 1 − SAN/100
SAN, SIL, CLA en %, C = carbone organique en %. Le facteur 0,1317 convertit des unités US
(t·acre·h / (100·acre·ft·tonf·in)) en t·ha·h / (ha·MJ·mm).

Limites : formule empirique, non calibrée à Kinshasa ; SoilGrids (250 m) représente mal les
sols urbains remaniés et les remblais. Les cellules sans donnée restent NaN (jamais 0).
"""
from __future__ import annotations

import numpy as np

US_TO_SI = 0.1317


def k_williams(sand_pct, silt_pct, clay_pct, oc_pct):
    san, sil, cla, c = (np.asarray(v, dtype="float64") for v in (sand_pct, silt_pct, clay_pct, oc_pct))
    fcsand = 0.2 + 0.3 * np.exp(-0.0256 * san * (1 - sil / 100.0))
    with np.errstate(invalid="ignore", divide="ignore"):
        fclsi = np.power(sil / (cla + sil), 0.3)
    forgc = 1 - 0.25 * c / (c + np.exp(3.72 - 2.95 * c))
    sn1 = 1 - san / 100.0
    fhisand = 1 - 0.7 * sn1 / (sn1 + np.exp(-5.51 + 22.9 * sn1))
    k = fcsand * fclsi * forgc * fhisand * US_TO_SI
    bad = ~np.isfinite(k) | np.isnan(san) | np.isnan(sil) | np.isnan(cla) | np.isnan(c)
    return np.where(bad, np.nan, k)
