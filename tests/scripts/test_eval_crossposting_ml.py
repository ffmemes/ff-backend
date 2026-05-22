import pytest
from scripts.eval_crossposting_ml import top_quintile_lift


def test_top_quintile_lift_is_neutral_when_scores_are_tied():
    labels = [1, 0, 1, 0, 0]

    assert top_quintile_lift([0, 0, 0, 0, 0], labels) == 1.0


def test_top_quintile_lift_handles_boundary_ties_without_label_leakage():
    labels = [1, 0, 0, 1, 0, 0, 0, 0, 0, 0]

    assert top_quintile_lift([10, 9, 9, 9, 1, 0, 0, 0, 0, 0], labels) == pytest.approx(10 / 3)
