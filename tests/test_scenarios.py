import numpy as np

from engine.scenarios import Entrees, changer_occupation, executer, facteur_p

TABLE_C = {"seuil_hors_domaine": 0.5, "classes": {
    "10": {"bas": 0.001, "haut": 0.001}, "30": {"bas": 0.1, "haut": 0.1}, "40": {"bas": 0.4, "haut": 0.4},
    "50": {"bas": None, "haut": None, "regle": "hors_domaine"}}}


def entrees(fr):
    one = np.ones((1, 2), "float32")
    return Entrees(K=one, LS={"a": one}, R_ref={"r": one}, R_scen={"r": one}, fracs=fr,
                   pente_deg=np.full((1, 2), 10.0, "float32"), zone=np.array([[True, False]]), cell_ha=1.0,
                   table_c=TABLE_C)


def test_changer_occupation_conserve_les_fractions():
    fr = {30: np.array([[0.8, 0.8]]), 10: np.array([[0.2, 0.2]])}
    out, moved = changer_occupation(fr, np.array([[True, False]]), [30], 10, 0.5)
    assert np.allclose(out[30], [[0.4, 0.8]]) and np.allclose(out[10], [[0.6, 0.2]])
    assert np.allclose(moved, [[0.4, 0]])
    assert np.allclose(out[30] + out[10], 1)


def test_reboisement_reduit_la_perte_dans_la_zone_seulement():
    fr = {30: np.array([[1.0, 1.0]], "float32"), 10: np.zeros((1, 2), "float32"),
          40: np.zeros((1, 2), "float32"), 50: np.zeros((1, 2), "float32")}
    res, cartes = executer(entrees(fr), reboisement={"part": 1.0, "classes": [30]})
    assert np.isclose(res["perte_reference_t_an"]["mediane"], 0.1)
    assert np.isclose(res["perte_scenario_t_an"]["mediane"], 0.001)
    assert np.isclose(res["variation_pct"]["mediane"], -99.0)
    assert np.isnan(cartes["difference"][0, 1])  # hors zone


def test_urbanisation_sort_du_domaine_et_avertit():
    fr = {30: np.array([[1.0, 1.0]], "float32"), 10: np.zeros((1, 2), "float32"),
          40: np.zeros((1, 2), "float32"), 50: np.zeros((1, 2), "float32")}
    res, cartes = executer(entrees(fr), urbanisation={"part": 0.8, "classes": [30]})
    assert res["sorti_du_domaine_ha"] == 1.0 and res["bati_ajoute_ha"] == 0.8
    assert "avertissement" in res


def test_facteur_p_sur_part_cultivee():
    P = facteur_p({"central": 0.5}, "central", np.full((1, 2), 10.0), np.array([[True, True]]),
                  np.array([[0.4, 0.0]]), "cultures")
    assert np.allclose(P, [[0.8, 1.0]])
    Pt = facteur_p({"par_pente": [[5, 0.1], [100, 0.33]]}, "central", np.array([[1.0, 20.0]]),
                   np.array([[True, True]]), None, "tout")
    assert np.allclose(Pt, [[0.1, 0.33]])
