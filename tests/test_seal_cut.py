"""Corte mínimo reduzido da selagem: tem de dar o mesmo corte do grafo inteiro."""
import numpy as np
import pytest

from hammertools import seal


def _grid(seed: int, shape=(18, 16, 14), solid=0.35):
    rng = np.random.default_rng(seed)
    blocked = rng.random(shape) < solid
    src = np.zeros(shape, bool)
    snk = np.zeros(shape, bool)
    src[:3] = True                  # fonte de um lado, sumidouro do outro, com paredes aleatórias no meio
    snk[-4:] = True
    snk[:, :2] = True               # sumidouro largo também encosta na fonte (ar que é das duas máscaras)
    return blocked, src, snk


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("conn", (6, 18))
def test_reduced_cut_is_the_full_cut(seed, conn):
    blocked, src, snk = _grid(seed)
    protect = np.zeros(blocked.shape, bool)
    protect[1, 5:9, 5:9] = True
    for p in (None, protect):
        full = seal._cut_masks_full(blocked, src, snk, protect=p, conn=conn)
        assert np.array_equal(seal.cut_masks(blocked, src, snk, protect=p, conn=conn), full)


def test_reduced_cut_without_link_is_empty():
    blocked, src, _ = _grid(0)
    snk = np.zeros(blocked.shape, bool)
    snk[-4:] = True
    blocked[8] = True               # parede inteira: fonte e sumidouro não se ligam
    assert not seal.cut_masks(blocked, src, snk, conn=18).any()
    assert not seal._cut_masks_full(blocked, src, snk, conn=18).any()
