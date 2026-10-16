"""Tests de référence du moteur topographique et hydrologique (rasters synthétiques)."""
import numpy as np
import pytest
from rasterio.crs import CRS
from rasterio.transform import Affine

from engine import terrain_metrics as tm
from engine import flow_analysis as fa

RES = 10.0


def plane(nr=20, nc=20, sx=0.1, sy=0.0):
    """Plan incliné : z = 100 + sx*x + sy*y (x vers l'est, y vers le nord), en m."""
    rows, cols = np.mgrid[0:nr, 0:nc]
    x = cols * RES
    y = (nr - 1 - rows) * RES
    return (100 + sx * x + sy * y).astype("float64")


def test_slope_plane_exact():
    z = plane(sx=0.1)  # 10 % vers l'est
    s = tm.slope(z, RES, "percent")
    assert np.nanmax(np.abs(s[1:-1, 1:-1] - 10.0)) < 1e-4
    d = tm.slope(z, RES, "degrees")
    assert np.allclose(d[1:-1, 1:-1], np.degrees(np.arctan(0.1)), atol=1e-4)
    assert np.isnan(s[0]).all()  # bord : voisin manquant -> NaN, pas d'extrapolation


def test_aspect_directions():
    # le terrain monte vers l'est -> la pente descend vers l'ouest (270°)
    assert np.allclose(tm.aspect(plane(sx=0.1), RES)[5:-5, 5:-5], 270, atol=1e-6)
    # monte vers le nord -> descend vers le sud (180°)
    assert np.allclose(tm.aspect(plane(sx=0, sy=0.1), RES)[5:-5, 5:-5], 180, atol=1e-6)
    assert np.isnan(tm.aspect(np.full((5, 5), 3.0), RES)[2, 2])


def test_curvature_plane_zero_and_hill_convex():
    prof, plan = tm.curvatures(plane(sx=0.1, sy=0.05), RES)
    assert np.allclose(prof[1:-1, 1:-1], 0, atol=1e-9) and np.allclose(plan[1:-1, 1:-1], 0, atol=1e-9)
    r, c = np.mgrid[0:41, 0:41]
    dome = 100 - 0.01 * ((r - 20) ** 2 + (c - 20) ** 2) * RES  # colline
    prof, plan = tm.curvatures(dome, RES)
    assert prof[20, 30] > 0  # versant convexe en profil
    assert plan[20, 30] > 0  # divergent en plan
    rr, cc = np.mgrid[0:41, 0:41]
    trough = 100 + 0.02 * ((cc - 20) * RES) ** 2 / RES - 0.5 * rr * RES * -1  # gouttière descendant vers le nord
    prof2, plan2 = tm.curvatures(trough.astype(float), RES)
    assert plan2[20, 25] < 0  # convergent


def test_contours_levels():
    z = plane(sx=0.1)
    lines = tm.contours(z, Affine(RES, 0, 0, 0, -RES, 200), interval=5)
    levels = sorted({l for l, _ in lines})
    assert levels[0] >= z.min() and levels[-1] <= z.max()
    assert all(abs(lv % 5) < 1e-9 for lv in levels)


def v_valley(n=31):
    """Vallée en V qui descend vers le sud : talweg au centre (colonne 15)."""
    r, c = np.mgrid[0:n, 0:n]
    return (200 - 2.0 * r + 3.0 * np.abs(c - n // 2)).astype("float64")


def test_d8_valley_flows_to_thalweg_and_south():
    z = v_valley()
    fd = fa.flow_direction(z, RES)
    assert fd[10, 5] in (1, 2)          # rive gauche -> E ou SE
    assert fd[10, 25] in (16, 8)        # rive droite -> O ou SO
    assert fd[10, 15] == 4              # talweg -> S


def test_accumulation_mass_balance_and_outlet():
    z = v_valley()
    valid = np.ones(z.shape, bool)
    fd = fa.flow_direction(z, RES)
    acc = fa.flow_accumulation(fd, valid)
    lab = fa.basins(fd, valid)
    # somme des accumulations aux exutoires = nombre total de cellules
    outlets = np.unique(lab)
    total = sum(acc.ravel()[o] for o in outlets)
    assert total == z.size
    assert np.nanmax(acc) == acc[-1, 15]  # le maximum est à la sortie du talweg


def test_conditioning_fills_pit_and_records_it():
    z = v_valley()
    z[15, 15] -= 20  # cuvette artificielle dans le talweg
    cond = fa.condition_dem(z, Affine(RES, 0, 0, 0, -RES, 310), CRS.from_epsg(32733))
    # comblée jusqu'au seuil de débordement aval (168 m) : 168 - 150 = 18 m
    assert cond.fill_depth[15, 15] == pytest.approx(18, abs=0.01)
    assert cond.stats["cellules_modifiees_plus_1mm"] >= 1
    fd = fa.flow_direction(cond.dem, RES)
    acc = fa.flow_accumulation(fd, np.ones(z.shape, bool))
    assert acc[-1, 15] > z.shape[0] * 10  # l'écoulement franchit la cuvette


def test_nodata_not_routed():
    z = v_valley()
    z[0:5, 0:5] = np.nan
    valid = ~np.isnan(z)
    fd = fa.flow_direction(z, RES)
    acc = fa.flow_accumulation(fd, valid)
    assert np.isnan(acc[0:5, 0:5]).all()
    assert np.nansum(fa.flow_accumulation(fd, valid)[fa.basins(fd, valid) == fa.basins(fd, valid)[-1, 15]]) > 0


def test_subbasins_and_catchment():
    z = v_valley()
    valid = np.ones(z.shape, bool)
    fd = fa.flow_direction(z, RES)
    acc = fa.flow_accumulation(fd, valid)
    streams = fa.stream_mask(acc, RES * RES, threshold_km2=20 * RES * RES / 1e6)
    lab, nodes = fa.subbasins(fd, valid, streams)
    assert nodes.sum() >= 1 and (lab >= 0).all()
    r, c = fa.snap_to_stream(acc, 30, 13, 3)
    assert (r, c) == (30, 15)
    m = fa.catchment(fd, valid, r, c)
    assert m.sum() == acc[r, c]


def test_interior_nodata_is_outlet():
    """Une cuvette dont le fond est un lac (NoData) ne doit pas être comblée."""
    r, c = np.mgrid[0:41, 0:41]
    z = 100 + 0.5 * np.hypot(r - 20, c - 20)
    z[19:22, 19:22] = np.nan
    cond = fa.condition_dem(z)
    assert cond.stats["cellules_modifiees_plus_1mm"] == 0
    fd = fa.flow_direction(cond.dem, RES)
    lab = fa.basins(fd, ~np.isnan(z))
    outl = np.unique(lab[~np.isnan(z)])
    rr, cc = np.divmod(outl, z.shape[1])
    assert np.all((np.abs(rr - 20) <= 2) & (np.abs(cc - 20) <= 2))  # tout s'écoule vers le lac
