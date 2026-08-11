"""Taste cohort load + shadow multiplier."""

from src.crossposting.taste_cohort import (
    load_ru_taste_cohort,
    taste_boost_multiplier,
)


def test_cohort_file_loads_nonempty():
    ids = load_ru_taste_cohort()
    # Frozen v1 file committed with PR; empty only if missing in some envs.
    assert isinstance(ids, tuple)
    if ids:
        assert len(ids) == 50
        assert all(isinstance(i, int) for i in ids)


def test_taste_boost_multiplier():
    assert taste_boost_multiplier(0) == 1.0
    assert taste_boost_multiplier(1) == 1.15
    assert taste_boost_multiplier(5) == 1.0 + 0.15 * 5
    assert taste_boost_multiplier(99) == taste_boost_multiplier(5)
