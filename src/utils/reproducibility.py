"""Seeds explícitas antes de gerar dados ou treinar modelos."""

import random

import numpy as np


def set_seed(seed: int = 42) -> np.random.Generator:
    """Inicializa RNGs legados e devolve um gerador isolado para o chamador.

    PYTHONHASHSEED e limites de threads devem ser definidos antes do processo.
    A função não promete determinismo de hash() nem de algoritmos externos.
    """
    if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed < 2**32:
        raise ValueError("seed deve ser inteiro entre 0 e 2**32-1")
    random.seed(seed)
    np.random.seed(seed)
    return np.random.default_rng(seed)
