import numpy as np
from engine.r_factor import r_roose, r_renard_freimund, r_lo, fournier_modifie


def test_r_formulas_hand_values():
    assert np.isclose(r_roose(1500), 0.5 * 1500 * 17.02)       # 12 765
    assert np.isclose(r_renard_freimund(1500), 587.8 - 1.219 * 1500 + 0.004105 * 1500 ** 2)
    assert np.isclose(r_lo(1500), 38.46 + 3.48 * 1500)


def test_fournier_uniform_rain():
    m = np.full((12, 1), 100.0)
    assert np.isclose(fournier_modifie(m)[0], 100.0)
