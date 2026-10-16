"""Facteur R (érosivité des pluies), en MJ·mm/(ha·h·an), à partir de la pluie annuelle P (mm).

Aucune donnée d'intensité (EI30) n'est disponible pour Kinshasa : R est estimé par des
relations empiriques pluie annuelle -> R, calées AILLEURS. On en calcule plusieurs pour
encadrer l'incertitude ; aucune n'est validée à Kinshasa.

- Roose (1977), Afrique de l'Ouest : R_US = a · P, a = 0,5 ± 0,05 (unités US) ; ×17,02 -> SI
  (1 unité US = 1,735 unité métrique t·m·cm/(ha·h) × 9,81 = 17,02 MJ·mm/(ha·h)).
- Renard & Freimund (1994), États-Unis, P > 850 mm : R = 587,8 − 1,219 P + 0,004105 P².
- Lo et al. (1985), Hawaï : R = 38,46 + 3,48 P.
"""
from __future__ import annotations

import numpy as np

US_TO_SI = 17.02


def r_roose(p_mm, a=0.5):
    return a * np.asarray(p_mm, dtype="float64") * US_TO_SI


def r_renard_freimund(p_mm):
    p = np.asarray(p_mm, dtype="float64")
    r = np.where(p > 850, 587.8 - 1.219 * p + 0.004105 * p ** 2, 0.0483 * p ** 1.61)
    return r


def r_lo(p_mm):
    return 38.46 + 3.48 * np.asarray(p_mm, dtype="float64")


def fournier_modifie(monthly_mm):
    """Indice de Fournier modifié (Arnoldus 1980) : somme(p_i²)/P sur 12 mois (axe 0)."""
    m = np.asarray(monthly_mm, dtype="float64")
    return (m ** 2).sum(axis=0) / m.sum(axis=0)


METHODES = {
    "roose1977_a0.45": lambda p: r_roose(p, 0.45),
    "roose1977_a0.50": lambda p: r_roose(p, 0.50),
    "roose1977_a0.55": lambda p: r_roose(p, 0.55),
    "renard_freimund1994": r_renard_freimund,
    "lo1985": r_lo,
}
