import numpy as np
import pytest
from engine.rusle import rusle


def test_ones_give_one_and_zero_gives_zero():
    o = np.ones((2, 2))
    assert np.allclose(rusle(o, o, o, o), 1)
    c = o.copy(); c[0, 0] = 0
    assert rusle(o, o, o, c)[0, 0] == 0


def test_nan_propagates_never_zero():
    o = np.ones((1, 2)); k = o.copy(); k[0, 1] = np.nan
    a = rusle(o, k, o, o)
    assert a[0, 0] == 1 and np.isnan(a[0, 1])


def test_shape_and_sign_checks():
    with pytest.raises(ValueError):
        rusle(np.ones((2, 2)), np.ones((2, 3)), np.ones((2, 2)), np.ones((2, 2)))
    with pytest.raises(ValueError):
        rusle(-np.ones((1, 1)), np.ones((1, 1)), np.ones((1, 1)), np.ones((1, 1)))
