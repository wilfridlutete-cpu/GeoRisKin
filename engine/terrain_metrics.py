"""Indicateurs topographiques dérivés d'un MNT en coordonnées projetées (m).

Méthodes documentées :
- pente et exposition : différences finies de Horn (1981), fenêtre 3×3 ;
- courbures de profil et en plan : coefficients de Zevenbergen & Thorne (1987),
  signes fixés par les tests de référence (dôme, gouttière) ;
- ombrage : modèle de Lambert, soleil à l'azimut/hauteur donnés ;
- courbes de niveau : interpolation linéaire (marching squares, scikit-image).

Conventions :
- entrée : tableau 2D float, NaN = NoData, cellule carrée de taille `res` (m) ;
- une cellule dont un voisin est NoData reçoit NaN (pas d'extrapolation) ;
- exposition en degrés depuis le nord, dans le sens horaire ; NaN si pente nulle ;
- courbures en 1/m ; profil > 0 = convexe (le ruissellement accélère),
  profil < 0 = concave ; plan > 0 = divergent, plan < 0 = convergent.
"""
from __future__ import annotations

import numpy as np


def _neighbours(z: np.ndarray):
    """Renvoie les 9 vues décalées (a..i) d'une fenêtre 3×3, bords en NaN.

        a b c
        d e f
        g h i
    """
    p = np.pad(z.astype("float64"), 1, constant_values=np.nan)
    a, b, c = p[:-2, :-2], p[:-2, 1:-1], p[:-2, 2:]
    d, e, f = p[1:-1, :-2], p[1:-1, 1:-1], p[1:-1, 2:]
    g, h, i = p[2:, :-2], p[2:, 1:-1], p[2:, 2:]
    return a, b, c, d, e, f, g, h, i


def horn_gradients(z: np.ndarray, res: float):
    """Gradients dz/dx (vers l'est) et dz/dy (vers le nord) selon Horn (1981)."""
    a, b, c, d, e, f, g, h, i = _neighbours(z)
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * res)
    dzdy = ((a + 2 * b + c) - (g + 2 * h + i)) / (8 * res)  # ligne 0 = nord
    return dzdx, dzdy


def slope(z: np.ndarray, res: float, units: str = "degrees") -> np.ndarray:
    """Pente : 'degrees', 'percent' ou 'radians'."""
    dzdx, dzdy = horn_gradients(z, res)
    tan = np.hypot(dzdx, dzdy)
    if units == "percent":
        return (100 * tan).astype("float32")
    rad = np.arctan(tan)
    return (np.degrees(rad) if units == "degrees" else rad).astype("float32")


def aspect(z: np.ndarray, res: float) -> np.ndarray:
    """Exposition (direction de la plus grande pente descendante), 0–360° depuis le nord."""
    dzdx, dzdy = horn_gradients(z, res)
    asp = np.degrees(np.arctan2(-dzdx, -dzdy)) % 360.0
    asp[(dzdx == 0) & (dzdy == 0)] = np.nan
    return asp.astype("float32")


def hillshade(z: np.ndarray, res: float, azimuth: float = 315.0, altitude: float = 45.0,
              z_factor: float = 1.0) -> np.ndarray:
    """Ombrage 0–255 (uint8 ; 0 aussi pour NoData, voir le masque)."""
    dzdx, dzdy = horn_gradients(z * z_factor, res)
    slp = np.arctan(np.hypot(dzdx, dzdy))
    asp = np.arctan2(-dzdx, -dzdy)
    az, alt = np.radians(azimuth), np.radians(altitude)
    hs = np.sin(alt) * np.cos(slp) + np.cos(alt) * np.sin(slp) * np.cos(az - asp)
    out = np.clip(hs, 0, 1) * 255
    return np.where(np.isnan(out), 0, out).astype("uint8")


def curvatures(z: np.ndarray, res: float):
    """Courbures de profil et en plan (1/m), Zevenbergen & Thorne (1987)."""
    a, b, c, d, e, f, g, h, i = _neighbours(z)
    L = res
    D = ((d + f) / 2 - e) / L**2
    E = ((b + h) / 2 - e) / L**2
    F = (-a + c + g - i) / (4 * L**2)
    G = (-d + f) / (2 * L)
    H = (b - h) / (2 * L)
    p = G**2 + H**2
    with np.errstate(invalid="ignore", divide="ignore"):
        prof = -2 * (D * G**2 + E * H**2 + F * G * H) / p
        plan = -2 * (D * H**2 + E * G**2 - F * G * H) / p  # signe : > 0 = divergent
    flat = p == 0
    prof[flat] = 0.0
    plan[flat] = 0.0
    return prof.astype("float32"), plan.astype("float32")


def contours(z: np.ndarray, transform, interval: float, base: float = 0.0):
    """Courbes de niveau en coordonnées du raster ; renvoie [(altitude, LineString)]."""
    from skimage import measure
    from shapely.geometry import LineString

    zmin, zmax = np.nanmin(z), np.nanmax(z)
    start = base + np.ceil((zmin - base) / interval) * interval
    levels = np.arange(start, zmax + 1e-9, interval)
    out = []
    for lev in levels:
        for path in measure.find_contours(z, lev):  # NaN = trou, les lignes s'y coupent
            if len(path) < 2:
                continue
            rows, cols = path[:, 0], path[:, 1]
            xs = transform.c + (cols + 0.5) * transform.a
            ys = transform.f + (rows + 0.5) * transform.e
            out.append((float(lev), LineString(np.column_stack([xs, ys]))))
    return out
