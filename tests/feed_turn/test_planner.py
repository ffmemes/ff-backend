import pytest

from src.feed_turn.planner import (
    COLD_START_1,
    COLD_START_2,
    COLD_START_3,
    GROWING,
    MATURE,
    low_sent_quota,
    plan_candidate_selection,
)


def _fallbacks(nmemes_sent: int) -> tuple[tuple[str, dict], ...]:
    plan = plan_candidate_selection(nmemes_sent)
    return tuple((fallback.engine, dict(fallback.kwargs)) for fallback in plan.fallback_engines)


@pytest.mark.parametrize(
    ("nmemes_sent", "stage", "primary_engine"),
    [
        (5, COLD_START_1, "cold_start_explore"),
        (6, COLD_START_2, "cold_start_adapt"),
        (15, COLD_START_2, "cold_start_adapt"),
        (16, COLD_START_3, None),
        (29, COLD_START_3, None),
        (30, GROWING, None),
        (99, GROWING, None),
        (100, MATURE, None),
    ],
)
def test_stage_boundaries(nmemes_sent, stage, primary_engine):
    plan = plan_candidate_selection(nmemes_sent)

    assert plan.maturity_stage == stage
    assert plan.primary_engine == primary_engine


@pytest.mark.parametrize("nmemes_sent", [0, 5, 6, 15])
def test_cold_start_fallback_order_and_min_sends(nmemes_sent):
    assert _fallbacks(nmemes_sent) == (
        ("lr_smoothed", {"min_sends": 10}),
        ("best_uploaded_memes", {}),
    )


def test_transition_blend_and_empty_blend_fallback_order():
    plan = plan_candidate_selection(16)

    assert dict(plan.blend_weights) == {
        "cold_start_adapt": 0.5,
        "lr_smoothed": 0.3,
        "like_spread_and_recent_memes": 0.2,
    }
    assert dict(plan.fixed_pos) == {0: "cold_start_adapt"}
    assert _fallbacks(16) == (
        ("cold_start_adapt", {}),
        ("lr_smoothed", {"min_sends": 10}),
        ("best_uploaded_memes", {}),
    )


def test_growing_blend_plan():
    plan = plan_candidate_selection(30)

    assert dict(plan.blend_weights) == {
        "best_uploaded_memes": 0.1,
        "lr_smoothed": 0.3,
        "recently_liked": 0.2,
        "goat": 0.1,
        "es_ranked": 0.1,
        "like_spread_and_recent_memes": 0.2,
    }
    assert dict(plan.fixed_pos) == {0: "lr_smoothed"}
    assert plan.fallback_engines == ()


def test_mature_blend_plan():
    plan = plan_candidate_selection(100)

    assert dict(plan.blend_weights) == {
        "best_uploaded_memes": 0.3,
        "like_spread_and_recent_memes": 0.3,
        "lr_smoothed": 0.4,
        "recently_liked": 0.2,
        "goat": 0.1,
        "es_ranked": 0.1,
    }
    assert dict(plan.fixed_pos) == {0: "lr_smoothed"}
    assert plan.fallback_engines == ()


@pytest.mark.parametrize(
    ("limit", "user_type", "quota"),
    [
        (4, "moderator", 3),
        (15, "admin", 12),
        (1, "moderator", 1),
        (0, "admin", 0),
    ],
)
def test_low_sent_quota_for_moderators_and_admins(limit, user_type, quota):
    assert low_sent_quota(limit, user_type) == quota


@pytest.mark.parametrize("user_type", ["user", "active_user", "blocked_bot", "unknown", None])
def test_low_sent_quota_for_regular_or_unknown_user_types(user_type):
    assert low_sent_quota(15, user_type) == 0


def test_low_sent_quota_accepts_enum_like_values_without_importing_tgbot():
    class UserTypeLike:
        value = "moderator"

    assert low_sent_quota(4, UserTypeLike()) == 3


def test_planner_mappings_are_read_only():
    plan = plan_candidate_selection(30)

    with pytest.raises(TypeError):
        plan.blend_weights["lr_smoothed"] = 0.9
    with pytest.raises(TypeError):
        plan.fixed_pos[0] = "x"


def test_fallback_engines_coerced_to_tuple():
    from src.feed_turn.planner import CandidateSelectionPlan, EngineFallback

    plan = CandidateSelectionPlan(
        maturity_stage="x",
        primary_engine=None,
        fallback_engines=[EngineFallback("a")],
    )

    assert isinstance(plan.fallback_engines, tuple)
    with pytest.raises(AttributeError):
        plan.fallback_engines.append(EngineFallback("b"))


def test_engine_fallback_kwargs_are_read_only():
    cold_plan = plan_candidate_selection(0)
    lr_fallback = cold_plan.fallback_engines[0]

    assert lr_fallback.engine == "lr_smoothed"
    with pytest.raises(TypeError):
        lr_fallback.kwargs["min_sends"] = 1
