"""RU taste cohort for crosspost shadow scoring (H7).

Cohort = users whose pre-channel-post likes historically co-occur with high
24h channel fwd/1k (train time-split). Used only for **shadow logging** until
an online gate passes — does not change ranking by default.

Refresh: `python scripts/crosspost_taste_cohort.py` (analyst DB) → rewrites
`src/crossposting/data/ru_taste_cohort_v1.json`.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_COHORT_PATH = Path(__file__).resolve().parent / "data" / "ru_taste_cohort_v1.json"

# Soft boost only if CROSSPOST_RU_TASTE_BOOST_ENABLED (default off).
TASTE_BOOST_WEIGHT = 0.15
TASTE_BOOST_CAP = 5


@lru_cache(maxsize=1)
def load_ru_taste_cohort() -> tuple[int, ...]:
    """Return frozen user_ids for RU taste shadow (empty if file missing)."""
    if not _COHORT_PATH.is_file():
        logger.warning("Taste cohort file missing: %s", _COHORT_PATH)
        return ()
    try:
        data = json.loads(_COHORT_PATH.read_text())
        ids = tuple(int(x) for x in data.get("user_ids") or [])
        return ids
    except Exception:
        logger.exception("Failed to load taste cohort from %s", _COHORT_PATH)
        return ()


def taste_boost_multiplier(n_taste_likes: int) -> float:
    """Shadow / optional online: 1 + w * min(n, cap)."""
    n = max(0, int(n_taste_likes))
    return 1.0 + TASTE_BOOST_WEIGHT * min(n, TASTE_BOOST_CAP)


def cohort_meta() -> dict:
    if not _COHORT_PATH.is_file():
        return {"version": None, "n_users": 0}
    try:
        data = json.loads(_COHORT_PATH.read_text())
        return {
            "version": data.get("version"),
            "n_users": len(data.get("user_ids") or []),
            "created_at_utc": data.get("created_at_utc"),
            "train_cut": data.get("train_cut"),
        }
    except Exception:
        return {"version": None, "n_users": 0}
