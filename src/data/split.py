"""Partições por grupos, referência de treino e janelas sem resultados de modelo."""

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold, train_test_split

from src.data.prepare import TARGET
from src.utils.config import DataConfig
from src.utils.manifest import content_hash

PARTITIONS = {"train": 0.50, "validation": 0.15, "test": 0.15, "production_pool": 0.20}


@dataclass
class Partitions:
    tables: dict[str, pd.DataFrame]
    reference: pd.DataFrame
    windows: list[pd.DataFrame]
    remainder: pd.DataFrame
    split_hash: str
    statistics: dict


def split(data: pd.DataFrame, config: DataConfig) -> Partitions:
    """SGKF de 20 folds: 0..9 treino, 10..12 validação, 13..15 teste, 16..19 produção.

    A referência é estratificada por linha, somente dentro do treino. Janelas são
    permutadas a partir de produção ordenada por ID, usando RNG exclusivo de seed 42.
    """
    data = data.sort_values("record_id").reset_index(drop=True)
    if len(data) < config.minimum_rows:
        raise ValueError("Menos de 5.000 registros utilizáveis")
    if data.group_id.nunique() < config.n_splits:
        raise ValueError("Grupos insuficientes para os folds")
    splitter = StratifiedGroupKFold(
        n_splits=config.n_splits, shuffle=True, random_state=config.split_seed
    )
    folds = np.full(len(data), -1, dtype=int)
    for fold, (_, indices) in enumerate(splitter.split(data, data[TARGET], data.group_id)):
        folds[indices] = fold
    names = np.select(
        [folds < 10, folds < 13, folds < 16],
        ["train", "validation", "test"],
        default="production_pool",
    )
    tables = {name: data.loc[names == name].copy() for name in PARTITIONS}
    for table in tables.values():
        if set(table[TARGET].unique()) != {0, 1}:
            raise ValueError("Partição sem duas classes")
    for left, right in combinations(tables.values(), 2):
        if set(left.group_id) & set(right.group_id) or set(left.record_id) & set(right.record_id):
            raise ValueError("Interseção indevida entre partições")
    train = tables["train"]
    if len(train) <= config.reference_size:
        reference = train.copy()
    else:
        selected, _ = train_test_split(
            np.arange(len(train)),
            train_size=config.reference_size,
            stratify=train[TARGET],
            random_state=config.split_seed,
        )
        reference = train.iloc[selected].sort_values("record_id").copy()
    production = tables["production_pool"]
    order = np.random.default_rng(config.split_seed).permutation(len(production))
    production = production.iloc[order]
    complete = len(production) // config.window_size
    if complete < config.minimum_windows:
        raise ValueError("Produção insuficiente para quatro janelas completas")
    windows = [
        production.iloc[i * config.window_size : (i + 1) * config.window_size].copy()
        for i in range(complete)
    ]
    remainder = production.iloc[complete * config.window_size :].copy()
    # O hash inclui associação inteira de partições, referência e ordem das janelas.
    allocation = {
        "partitions": {
            name: table[["record_id", "group_id"]].values.tolist() for name, table in tables.items()
        },
        "reference": reference.record_id.tolist(),
        "windows": [window.record_id.tolist() for window in windows],
        "remainder": remainder.record_id.tolist(),
    }
    statistics = {
        name: {
            "row_count": len(table),
            "class_counts": {
                str(key): int(value)
                for key, value in table[TARGET].value_counts().sort_index().items()
            },
            "prevalence": float(table[TARGET].mean()),
            "fraction": len(table) / len(data),
            "deviation_percentage_points": 100 * (len(table) / len(data) - PARTITIONS[name]),
            "group_count": int(table.group_id.nunique()),
        }
        for name, table in tables.items()
    }
    return Partitions(tables, reference, windows, remainder, content_hash(allocation), statistics)
