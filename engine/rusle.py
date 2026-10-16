"""RUSLE : A = R · K · LS · C · P (perte moyenne annuelle de sol, t/ha/an).

Unités attendues : R en MJ·mm/(ha·h·an), K en t·ha·h/(ha·MJ·mm), LS, C, P sans dimension.
Toute cellule où un facteur est NaN reste NaN (hors domaine ou donnée manquante, jamais 0).
RUSLE représente l'érosion en nappe et en rigoles, pas les ravines ni les glissements.
"""
from __future__ import annotations

import numpy as np


def rusle(R, K, LS, C, P=1.0):
    arrs = [np.asarray(x, dtype="float32") for x in (R, K, LS, C)]
    shape = arrs[0].shape
    if any(a.shape != shape for a in arrs):
        raise ValueError("Tous les facteurs doivent être sur la même grille.")
    P = np.broadcast_to(np.asarray(P, dtype="float32"), shape)
    for name, a in zip("R K LS C P".split(), arrs + [P]):
        if np.any(a[np.isfinite(a)] < 0):
            raise ValueError(f"Facteur {name} négatif.")
    with np.errstate(invalid="ignore"):
        return arrs[0] * arrs[1] * arrs[2] * arrs[3] * P
