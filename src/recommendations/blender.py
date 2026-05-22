import random
from collections import deque
from typing import Any

EPS = 1e-6


def _validate_blend_inputs(
    candidates_dict: dict[str, list[dict[str, Any]]],
    weights_dict: dict[str, float],
    fixed_pos: dict[int, str],
) -> None:
    if set(candidates_dict.keys()) != set(weights_dict.keys()):
        raise ValueError("Keys in candidates_dict and weights_dict do not match")

    for engine in fixed_pos.values():
        if engine not in candidates_dict:
            raise ValueError(f"Engine {engine} does not present in candidates_dict")


def _active_engines(
    candidate_queues: dict[str, deque[dict[str, Any]]],
    seen_candidate_ids: set[Any],
) -> list[str]:
    active_engines = []
    for engine, candidates in candidate_queues.items():
        while candidates and candidates[0]["id"] in seen_candidate_ids:
            candidates.popleft()
        if candidates:
            active_engines.append(engine)
    return active_engines


def _engine_weights(engines: list[str], weights_dict: dict[str, float]) -> list[float]:
    return [weights_dict[engine] + EPS for engine in engines]


def blend(
    candidates_dict: dict[str, list[dict[str, Any]]],
    weights_dict: dict[str, float],
    fixed_pos: dict[int, str] | None = None,
    limit: int = 0,
    random_seed: int | None = None,
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

    rng = random.Random(random_seed)
    fixed_pos = fixed_pos or {}
    _validate_blend_inputs(candidates_dict, weights_dict, fixed_pos)

    if limit == 0:
        limit = sum(len(candidates) for candidates in candidates_dict.values())

    candidate_queues = {
        engine: deque(candidates)
        for engine, candidates in candidates_dict.items()
        if len(candidates) > 0
    }
    seen_candidate_ids: set[Any] = set()
    result = []

    for result_idx in range(limit):
        engines = _active_engines(candidate_queues, seen_candidate_ids)
        if not engines:
            break

        engine = fixed_pos.get(result_idx)
        if engine not in engines:
            engine = rng.choices(
                population=engines,
                weights=_engine_weights(engines, weights_dict),
            )[0]

        next_item = candidate_queues[engine].popleft().copy()
        result.append(next_item)
        seen_candidate_ids.add(next_item["id"])

    return result
