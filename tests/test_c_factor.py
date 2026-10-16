import numpy as np
from engine.c_factor import c_from_fractions, class_values

TABLE = {"classes": {"10": {"bas": 0.001, "haut": 0.001}, "60": {"bas": 1.0, "haut": 1.0},
                     "50": {"bas": None, "haut": None, "regle": "hors_domaine"}}}


def test_weighted_mean_and_out_of_domain():
    v = class_values(TABLE, "central")
    fr = {10: np.array([[0.5, 0.2, np.nan]]), 60: np.array([[0.5, 0.0, np.nan]]),
          50: np.array([[0.0, 0.8, np.nan]])}
    c = c_from_fractions(fr, v, 0.5)
    assert np.isclose(c[0, 0], 0.5005)
    assert np.isnan(c[0, 1])  # 80 % bâti -> hors domaine, jamais 0
    assert np.isnan(c[0, 2])  # sans donnée


def test_central_is_geometric_mean():
    t = {"classes": {"30": {"bas": 0.01, "haut": 0.1}}}
    assert np.isclose(class_values(t, "central")[30], np.sqrt(0.001))


def test_weighted_accumulation_impervious():
    from engine.flow_analysis import flow_accumulation
    # 1 ligne de 3 cellules s'écoulant vers l'est (code ESRI 1), la dernière est un exutoire (0)
    fdir = np.array([[1, 1, 0]], dtype="uint8")
    w = np.array([[0.5, 0.0, 1.0]])
    acc = flow_accumulation(fdir, np.ones_like(fdir, bool), w)
    assert np.allclose(acc, [[0.5, 0.5, 1.5]])
