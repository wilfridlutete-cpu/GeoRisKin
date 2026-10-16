import numpy as np
import pytest

from engine.k_factor import k_williams


def test_k_hand_computed_reference():
    # sable 80 %, limon 10 %, argile 10 %, C 1 % (calcul manuel de chaque terme)
    san, sil, cla, c = 80.0, 10.0, 10.0, 1.0
    fcsand = 0.2 + 0.3 * np.exp(-0.0256 * san * (1 - sil / 100))
    fclsi = (sil / (cla + sil)) ** 0.3
    forgc = 1 - 0.25 * c / (c + np.exp(3.72 - 2.95 * c))
    sn1 = 1 - san / 100
    fhis = 1 - 0.7 * sn1 / (sn1 + np.exp(-5.51 + 22.9 * sn1))
    assert k_williams(san, sil, cla, c) == pytest.approx(fcsand * fclsi * forgc * fhis * 0.1317)


def test_k_ordering_sand_vs_silt():
    """Un sol limoneux est plus érodable qu'un sable grossier (ordre de grandeur USLE)."""
    k_sand = k_williams(90, 5, 5, 0.5)
    k_silt = k_williams(20, 65, 15, 0.5)
    assert k_silt > k_sand
    assert 0.0 < k_sand < 0.08 and 0.02 < k_silt < 0.08


def test_k_missing_is_nan_not_zero():
    k = k_williams(np.array([np.nan, 50]), np.array([10, np.nan]), np.array([10, 10]), np.array([1, 1]))
    assert np.isnan(k).all()
