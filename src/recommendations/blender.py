import random
from typing import Any

EPS = 1e-6


def blend(
    candidates_dict: dict[str, list[dict[str, Any]]],
    weights_dict: dict[str, float],
    fixed_pos: dict[int, str] = None,
    limit: int = 0,
    random_seed: int = 42,
) -> list[dict[str, Any]]:
    """
    Blends candidates from multiple recommendation engines. Blending is implemented
    as sampling with weights. Besides of that, it is possible to set fixed engines
    to some positions.


    Args:
    - candidates_dict: Contains recommendation engine names with their outputs
        Items in candidate lists must have "id" field
    - weights_dict: Contains weights for each engine. Should have the same keys
        as candidates_dict. Weights may not sum to 1
    - fixed_pos: Allows to set fixed engines to provided positions. Starts from 0
    - limit
    - random_seed
    """

    random.seed(random_seed)

    # input validation and processing
    if set(candidates_dict.keys()) != set(weights_dict.keys()):
        raise ValueError("Keys in candidates_dict and weights_dict do not match")

    if fixed_pos:
        for engine in fixed_pos.values():
            if engine not in candidates_dict:
                raise ValueError(f"Engine {engine} does not present in candidates_dict")

    if limit == 0:
        for candidates in candidates_dict.values():
            limit += len(candidates)

    # candidates_dict will be changed inplace further
    candidates_dict = candidates_dict.copy()
    for engine in candidates_dict.keys():
        candidates_dict[engine] = candidates_dict[engine].copy()

    # engines list is ensured to have non-empty engines
    engines = [
        engine for engine in candidates_dict.keys() if len(candidates_dict[engine]) > 0
    ]

    weights = [(weights_dict[engine] + EPS) for engine in engines]
    if len(engines) == 0:
        return []

    res = []

    for res_idx in range(limit):
        engine = None

        # process fixed positions
        if fixed_pos and res_idx in fixed_pos:
            engine = fixed_pos[res_idx] if fixed_pos[res_idx] in engines else None

        # sample engine
        if engine is None:
            engine = random.choices(population=engines, weights=weights)[0]

        next_item = candidates_dict[engine][0].copy()
        res.append(next_item)

        # process candidates intersection
        for engine in engines:
            # remove all matches with next_item
            stop = False
            while not stop:
                stop = True
                for idx in range(len(candidates_dict[engine])):
                    if next_item["id"] == candidates_dict[engine][idx]["id"]:
                        candidates_dict[engine].pop(idx)
                        stop = False
                        break

        # maintain non-empty engines
        engines = [engine for engine in engines if len(candidates_dict[engine]) > 0]
        weights = [(weights_dict[engine] + EPS) for engine in engines]

        if len(engines) == 0:
            break

    return res
