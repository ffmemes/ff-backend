"""Tests for experiment_assignment table and helper functions."""

import pytest
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from src.database import engine, experiment_assignment, user
from src.tgbot.service import assign_experiment, get_experiment_assignment, get_experiment_variant


@pytest.fixture(autouse=True)
async def cleanup():
    """Clean up experiment_assignment and test users after each test."""
    yield
    async with engine.begin() as conn:
        await conn.execute(experiment_assignment.delete())
        await conn.execute(user.delete().where(user.c.id >= 90000))


async def _create_test_user(conn, user_id: int) -> None:
    await conn.execute(insert(user).values(id=user_id, type="user").on_conflict_do_nothing())


@pytest.mark.asyncio
async def test_assign_and_get_variant():
    """Assign a user to an experiment and retrieve the variant."""
    async with engine.begin() as conn:
        await _create_test_user(conn, 90001)

    await assign_experiment(90001, "test_experiment", "treatment")
    variant = await get_experiment_variant(90001, "test_experiment")
    assert variant == "treatment"


@pytest.mark.asyncio
async def test_assign_and_get_assignment_metadata():
    """Experiment assignments can store audit metadata for measurement."""
    async with engine.begin() as conn:
        await _create_test_user(conn, 90008)

    metadata = {"lr_quartile": 2, "high_volume_skipper": False}
    await assign_experiment(90008, "test_experiment", "treatment", metadata)
    assignment = await get_experiment_assignment(90008, "test_experiment")

    assert assignment is not None
    assert assignment["variant"] == "treatment"
    assert assignment["assignment_metadata"] == metadata


@pytest.mark.asyncio
async def test_get_variant_not_assigned():
    """Getting variant for unassigned user returns None."""
    async with engine.begin() as conn:
        await _create_test_user(conn, 90002)

    variant = await get_experiment_variant(90002, "nonexistent_experiment")
    assert variant is None


@pytest.mark.asyncio
async def test_assign_idempotent():
    """Assigning the same user twice is idempotent (ON CONFLICT DO NOTHING)."""
    async with engine.begin() as conn:
        await _create_test_user(conn, 90003)

    await assign_experiment(90003, "test_experiment", "treatment")
    await assign_experiment(90003, "test_experiment", "control")  # should NOT override

    variant = await get_experiment_variant(90003, "test_experiment")
    assert variant == "treatment"  # first assignment wins


@pytest.mark.asyncio
async def test_multiple_experiments():
    """A user can be in multiple experiments simultaneously."""
    async with engine.begin() as conn:
        await _create_test_user(conn, 90004)

    await assign_experiment(90004, "experiment_a", "treatment")
    await assign_experiment(90004, "experiment_b", "control")

    assert await get_experiment_variant(90004, "experiment_a") == "treatment"
    assert await get_experiment_variant(90004, "experiment_b") == "control"


@pytest.mark.asyncio
async def test_multi_variant_experiment():
    """An experiment can have 3+ variants (A/B/C)."""
    async with engine.begin() as conn:
        await _create_test_user(conn, 90005)
        await _create_test_user(conn, 90006)
        await _create_test_user(conn, 90007)

    await assign_experiment(90005, "abc_test", "control")
    await assign_experiment(90006, "abc_test", "variant_a")
    await assign_experiment(90007, "abc_test", "variant_b")

    assert await get_experiment_variant(90005, "abc_test") == "control"
    assert await get_experiment_variant(90006, "abc_test") == "variant_a"
    assert await get_experiment_variant(90007, "abc_test") == "variant_b"


@pytest.mark.asyncio
async def test_v_experiment_results_view_exists():
    """The v_experiment_results view is queryable."""
    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT * FROM v_experiment_results LIMIT 1"))
        columns = list(result.keys())
        assert "experiment_id" in columns
        assert "variant" in columns
        assert "users" in columns
        assert "like_rate_pct" in columns
        assert "median_session_length" in columns
        assert "users_who_uploaded" in columns


@pytest.mark.asyncio
async def test_recently_liked_blender_v2_measurement_views_exist():
    """The recently_liked v2 measurement views expose Analyst query hooks."""
    async with engine.begin() as conn:
        assignment = await conn.execute(
            text("SELECT * FROM v_recently_liked_blender_v2_assignment LIMIT 1")
        )
        assignment_columns = list(assignment.keys())
        assert "lr_quartile" in assignment_columns
        assert "high_volume_skipper" in assignment_columns
        assert "assigned_weights" in assignment_columns

        sample_gate = await conn.execute(
            text("SELECT * FROM v_recently_liked_blender_v2_sample_gate LIMIT 1")
        )
        sample_gate_columns = list(sample_gate.keys())
        assert "assigned_users" in sample_gate_columns
        assert "sample_gate_met" in sample_gate_columns

        engine_metrics = await conn.execute(
            text("SELECT * FROM v_recently_liked_blender_v2_engine_metrics LIMIT 1")
        )
        engine_columns = list(engine_metrics.keys())
        assert "recommended_by" in engine_columns
        assert "allocation_pct" in engine_columns
        assert "continuation_rate_pct" in engine_columns


@pytest.mark.asyncio
async def test_meme_like_count_measurement_views_exist():
    """The like-count experiment has direct result and sample-gate views."""
    async with engine.begin() as conn:
        results = await conn.execute(
            text("SELECT * FROM v_meme_like_count_experiment_results LIMIT 1")
        )
        result_columns = list(results.keys())
        assert "assigned_users" in result_columns
        assert "current_threshold_eligible_events" in result_columns
        assert "explicit_reaction_rate_pct" in result_columns
        assert "continuation_rate_pct" in result_columns

        sample_gate = await conn.execute(
            text("SELECT * FROM v_meme_like_count_experiment_sample_gate LIMIT 1")
        )
        sample_gate_columns = list(sample_gate.keys())
        assert "assigned_users" in sample_gate_columns
        assert "sample_gate_met" in sample_gate_columns
