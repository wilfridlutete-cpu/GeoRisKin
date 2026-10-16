"""Tests de référence du facteur LS."""
import numpy as np
import pytest

from engine import ls_factor as ls


def test_mccool_s_reference_values():
    # 9 % (tan) : bascule entre les deux branches ; 5 % et 20 % calculés à la main
    for tan, expected in [(0.05, 10.8 * np.sin(np.arctan(0.05)) + 0.03),
                          (0.20, 16.8 * np.sin(np.arctan(0.20)) - 0.50)]:
        assert ls.s_mccool(np.array([np.arctan(tan)]))[0] == pytest.approx(expected)
    # unité USLE : pente de 9 % -> S ≈ 1
    assert ls.s_mccool(np.array([np.arctan(0.09)]))[0] == pytest.approx(1.0, abs=0.02)


def test_desmet_govers_reproduces_uniform_slope_usle_L():
    """Sur un versant plan de longueur λ, la moyenne des L de cellule = (λ/22,13)^m."""
    D, n = 10.0, 30                 # 30 cellules de 10 m -> λ = 300 m
    theta = np.full(n, np.arctan(0.12))
    a_in = np.arange(n) * D * D      # écoulement unidirectionnel, largeur D
    L = ls.l_desmet_govers(a_in, D, theta, np.zeros(n))  # exposition nord : x = 1
    m = ls.slope_exponent_m(np.sin(theta[0]))
    assert L.mean() == pytest.approx((n * D / 22.13) ** m, rel=1e-9)


def test_unit_plot_gives_ls_close_to_one():
    """Parcelle unitaire USLE (22,13 m, 9 %) : LS ≈ 1."""
    D = 22.13
    L = ls.l_desmet_govers(np.array([0.0]), D, np.array([np.arctan(0.09)]), np.array([0.0]))
    S = ls.s_mccool(np.array([np.arctan(0.09)]))
    assert (L * S)[0] == pytest.approx(1.0, abs=0.03)


def test_channel_cells_excluded_not_zeroed():
    area = np.array([[900.0, 2e5]])
    LS, L, S, out = ls.ls_factor(area, 30.0, np.array([[5.0, 5.0]]), np.array([[0.0, 0.0]]),
                                 channel_area_m2=1e5)
    assert np.isfinite(LS[0, 0]) and LS[0, 0] > 0
    assert np.isnan(LS[0, 1]) and out[0, 1]


def test_flat_cell_has_small_ls_and_nodata_propagates():
    LS, *_ = ls.ls_factor(np.array([[900.0, np.nan]]), 30.0, np.array([[0.0, 3.0]]),
                          np.array([[np.nan, 0.0]]), channel_area_m2=None)
    assert LS[0, 0] == pytest.approx(0.03, abs=1e-6)  # S(0) = 0,03, L(0 aire amont) = 1
    assert np.isnan(LS[0, 1])
