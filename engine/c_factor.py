"""Facteur C (couverture et gestion) à partir des fractions d'occupation du sol.

C de cellule = moyenne des C de classe pondérée par la fraction de chaque classe dans la cellule,
calculée sur les seules classes du domaine RUSLE. Les classes « hors domaine » (bâti, eau) ne
reçoivent jamais C = 0 : si elles dépassent `seuil_hors_domaine` de la cellule, la cellule est NaN.
"""
from __future__ import annotations

import math

import numpy as np


def class_values(table: dict, variante: str) -> dict[int, float | None]:
    """Valeur de C par code de classe pour la variante 'bas', 'central' ou 'haut'."""
    out = {}
    for code, c in table["classes"].items():
        if c.get("regle") == "hors_domaine" or c["bas"] is None:
            out[int(code)] = None
        elif variante == "central":
            out[int(code)] = math.sqrt(c["bas"] * c["haut"])
        else:
            out[int(code)] = float(c[variante])
    return out


def c_from_fractions(fractions: dict[int, np.ndarray], values: dict[int, float | None],
                     seuil_hors_domaine: float = 0.5) -> np.ndarray:
    shape = next(iter(fractions.values())).shape
    num = np.zeros(shape)
    den = np.zeros(shape)
    hors = np.zeros(shape)
    known = np.zeros(shape, bool)
    for code, f in fractions.items():
        f = np.asarray(f, dtype="float64")
        ok = np.isfinite(f)
        known |= ok
        f0 = np.where(ok, f, 0.0)
        v = values.get(code)
        if v is None:
            hors += f0
        else:
            num += f0 * v
            den += f0
    with np.errstate(invalid="ignore", divide="ignore"):
        c = num / den
    c[~known | (den <= 0) | (hors > seuil_hors_domaine)] = np.nan
    return c
