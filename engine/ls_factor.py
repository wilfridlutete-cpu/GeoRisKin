"""Facteur topographique LS de RUSLE, calculé cellule par cellule sur MNT.

Méthode par défaut (documentée, couramment utilisée sur MNT) :
- L : Desmet & Govers (1996), extension à la surface de la formule de segment de
  Foster & Wischmeier (1974) :
      L_ij = [(A_in + D²)^(m+1) − A_in^(m+1)] / [D^(m+2) · x^m · 22,13^m]
  A_in : aire contributive à l'entrée de la cellule (m²), D : taille de cellule (m),
  x = |sin α| + |cos α| (α : exposition), 22,13 m : longueur de la parcelle unitaire USLE ;
- exposant m = β / (1 + β), β = (sin θ / 0,0896) / (3 · sin θ^0,8 + 0,56)
  (McCool et al. 1989, rapport rigole/interrigole « modéré ») ;
- S : McCool et al. (1987) : 10,8 sin θ + 0,03 si tan θ < 0,09, sinon 16,8 sin θ − 0,50.

Variantes (pour l'analyse de sensibilité, phase 4) :
- S de Nearing (1997) pour les fortes pentes : −1,5 + 17 / (1 + exp(2,3 − 6,1 sin θ)) ;
- LS de Moore & Burch (1986) : (A_s / 22,13)^0,4 · (sin θ / 0,0896)^1,3, A_s = A / (D·x).

Domaine de validité : RUSLE représente l'érosion en nappe et en rigoles. Les cellules où
l'écoulement est concentré (talwegs, ravines, rivières) sortent de ce domaine : elles sont
repérées par un seuil d'aire drainée explicite et exclues (NaN), pas mises à zéro.
L'aire contributive vient d'un routage D8 (une seule direction) : sur les versants
divergents, D8 concentre l'écoulement et peut surestimer L par endroits.
"""
from __future__ import annotations

import numpy as np

UNIT_PLOT_M = 22.13


def slope_exponent_m(sin_t: np.ndarray) -> np.ndarray:
    beta = (sin_t / 0.0896) / (3.0 * np.power(sin_t, 0.8) + 0.56)
    return beta / (1.0 + beta)


def s_mccool(slope_rad: np.ndarray) -> np.ndarray:
    s, t = np.sin(slope_rad), np.tan(slope_rad)
    return np.where(t < 0.09, 10.8 * s + 0.03, 16.8 * s - 0.50)


def s_nearing(slope_rad: np.ndarray) -> np.ndarray:
    return -1.5 + 17.0 / (1.0 + np.exp(2.3 - 6.1 * np.sin(slope_rad)))


def l_desmet_govers(a_in_m2: np.ndarray, cell_m: float, slope_rad: np.ndarray,
                    aspect_deg: np.ndarray) -> np.ndarray:
    """Facteur L ; `a_in_m2` = aire amont hors cellule. Exposition NaN (plat) -> x = 1."""
    m = slope_exponent_m(np.sin(slope_rad))
    a = np.deg2rad(np.nan_to_num(aspect_deg, nan=0.0))
    x = np.abs(np.sin(a)) + np.abs(np.cos(a))
    D = float(cell_m)
    num = np.power(a_in_m2 + D * D, m + 1.0) - np.power(a_in_m2, m + 1.0)
    den = np.power(D, m + 2.0) * np.power(x, m) * np.power(UNIT_PLOT_M, m)
    return num / den


def ls_moore_burch(area_m2: np.ndarray, cell_m: float, slope_rad: np.ndarray,
                   aspect_deg: np.ndarray) -> np.ndarray:
    a = np.deg2rad(np.nan_to_num(aspect_deg, nan=0.0))
    x = np.abs(np.sin(a)) + np.abs(np.cos(a))
    As = area_m2 / (cell_m * x)
    return np.power(As / UNIT_PLOT_M, 0.4) * np.power(np.sin(slope_rad) / 0.0896, 1.3)


def ls_factor(area_m2: np.ndarray, cell_m: float, slope_deg: np.ndarray, aspect_deg: np.ndarray,
              channel_area_m2: float | None, s_method: str = "mccool"):
    """Renvoie (LS, L, S, masque_hors_domaine).

    area_m2 : aire drainée de la cellule, cellule comprise (accumulation D8 × D²).
    channel_area_m2 : au-delà, la cellule est un écoulement concentré -> NaN (hors RUSLE).
    """
    t = np.deg2rad(slope_deg.astype("float64"))
    a_in = np.maximum(area_m2.astype("float64") - cell_m * cell_m, 0.0)
    L = l_desmet_govers(a_in, cell_m, t, aspect_deg)
    S = s_mccool(t) if s_method == "mccool" else s_nearing(t)
    LS = L * S
    out = np.zeros(LS.shape, bool) if channel_area_m2 is None else (area_m2 >= channel_area_m2)
    invalid = ~np.isfinite(LS) | np.isnan(area_m2) | np.isnan(slope_deg)
    LS = np.where(out | invalid, np.nan, LS)
    return LS.astype("float32"), L.astype("float32"), S.astype("float32"), out
