"""Unit tests for retention-broadcast HQ meme picker."""

from unittest.mock import AsyncMock, patch

import pytest

from src.recommendations.broadcast_pick import (
    BROADCAST_EXPLORE_RECOMMENDED_BY,
    BROADCAST_HQ_RECOMMENDED_BY,
    BROADCAST_RECOMMENDED_BY,
    pick_reengagement_meme,
)
from src.storage.constants import MemeType
from src.storage.schemas import MemeData


@pytest.mark.asyncio
async def test_hq_pick_uses_sql_row_and_hq_label(monkeypatch):
    monkeypatch.setattr(
        "src.recommendations.broadcast_pick.settings.BROADCAST_HIGH_QUALITY_PICK_ENABLED",
        True,
    )
    row = {
        "id": 42,
        "type": MemeType.IMAGE,
        "telegram_file_id": "file-42",
        "caption": "hi",
        "nlikes": 99,
    }
    with patch(
        "src.recommendations.broadcast_pick.fetch_one",
        new_callable=AsyncMock,
        return_value=row,
    ) as fetch_one:
        meme, label = await pick_reengagement_meme(7)

    fetch_one.assert_awaited_once()
    assert label == BROADCAST_HQ_RECOMMENDED_BY
    assert meme is not None
    assert meme.id == 42
    assert meme.recommended_by == BROADCAST_HQ_RECOMMENDED_BY


@pytest.mark.asyncio
async def test_hq_empty_falls_back_to_queue(monkeypatch):
    monkeypatch.setattr(
        "src.recommendations.broadcast_pick.settings.BROADCAST_HIGH_QUALITY_PICK_ENABLED",
        True,
    )
    queue_meme = MemeData(
        id=9,
        type=MemeType.IMAGE,
        telegram_file_id="q",
        caption=None,
        recommended_by="lr_smoothed",
    )
    with (
        patch(
            "src.recommendations.broadcast_pick.fetch_one",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.recommendations.broadcast_pick.check_queue",
            new_callable=AsyncMock,
        ) as check_queue,
        patch(
            "src.recommendations.broadcast_pick.get_next_meme_for_user",
            new_callable=AsyncMock,
            return_value=queue_meme,
        ) as get_next,
    ):
        meme, label = await pick_reengagement_meme(7)

    check_queue.assert_awaited_once_with(7)
    get_next.assert_awaited_once_with(7)
    assert meme is queue_meme
    assert label == BROADCAST_RECOMMENDED_BY


@pytest.mark.asyncio
async def test_hq_disabled_uses_queue_only(monkeypatch):
    monkeypatch.setattr(
        "src.recommendations.broadcast_pick.settings.BROADCAST_HIGH_QUALITY_PICK_ENABLED",
        False,
    )
    queue_meme = MemeData(
        id=3,
        type=MemeType.IMAGE,
        telegram_file_id="q",
        caption=None,
        recommended_by="goat",
    )
    with (
        patch(
            "src.recommendations.broadcast_pick.fetch_one",
            new_callable=AsyncMock,
        ) as fetch_one,
        patch(
            "src.recommendations.broadcast_pick.check_queue",
            new_callable=AsyncMock,
        ),
        patch(
            "src.recommendations.broadcast_pick.get_next_meme_for_user",
            new_callable=AsyncMock,
            return_value=queue_meme,
        ),
    ):
        meme, label = await pick_reengagement_meme(1)

    fetch_one.assert_not_called()
    assert meme is queue_meme
    assert label == BROADCAST_RECOMMENDED_BY


def _hq_rows(count=3):
    return [
        {
            "id": 100 + index,
            "type": MemeType.IMAGE,
            "telegram_file_id": f"file-{index}",
            "caption": None,
            "nlikes": 30,
            "hq_score": -0.7 + index * 0.1,
        }
        for index in range(count)
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["hq", "explore"])
@pytest.mark.parametrize("count", [1, 2, 3])
async def test_experiment_records_probabilities_for_actual_pool(monkeypatch, variant, count):
    from src.recommendations.broadcast_pick import pick_exploration_meme

    monkeypatch.setattr(
        "src.recommendations.broadcast_pick.settings.BROADCAST_HIGH_QUALITY_PICK_ENABLED", True
    )
    with (
        patch(
            "src.recommendations.broadcast_pick._fetch_exploration_candidates",
            new_callable=AsyncMock,
            return_value=_hq_rows(count),
        ) as fetch_all,
        patch("src.recommendations.broadcast_pick.check_queue", new_callable=AsyncMock) as queue,
    ):
        meme, label, metadata = await pick_exploration_meme(7, variant, "2026-11-21T10:00:00Z")
    fetch_all.assert_awaited_once()
    queue.assert_not_awaited()
    fetch_all.assert_awaited_once_with(7)
    assert label == (
        BROADCAST_HQ_RECOMMENDED_BY if variant == "hq" else BROADCAST_EXPLORE_RECOMMENDED_BY
    )
    assert metadata["candidate_ids"] == list(range(100, 100 + count))
    assert meme.id == metadata["candidate_ids"][metadata["chosen_index"]]
    conditional = 1.0 if variant == "hq" else 1.0 / count
    assert metadata["selection_probability"] == conditional
    assert metadata["joint_probability"] == 0.5 * conditional
    mixture = (0.5 if metadata["chosen_index"] == 0 else 0) + 0.5 / count
    assert metadata["mixture_probability"] == mixture
    assert metadata["fallback_reason"] is None
    if variant == "hq":
        assert meme.id == 100


@pytest.mark.asyncio
async def test_exploration_draw_replays_and_reaches_every_candidate(monkeypatch):
    from src.recommendations.broadcast_pick import pick_exploration_meme

    monkeypatch.setattr(
        "src.recommendations.broadcast_pick.settings.BROADCAST_HIGH_QUALITY_PICK_ENABLED", True
    )
    with patch(
        "src.recommendations.broadcast_pick._fetch_exploration_candidates",
        new_callable=AsyncMock,
        return_value=_hq_rows(),
    ):
        first = await pick_exploration_meme(7, "explore", "same-opportunity")
        replay = await pick_exploration_meme(7, "explore", "same-opportunity")
        choices = [
            (await pick_exploration_meme(7, "explore", f"opportunity-{index}"))[0].id
            for index in range(300)
        ]
    assert first == replay
    # A broad tolerance catches a draw accidentally shared across opportunities.
    assert all(60 < choices.count(candidate_id) < 140 for candidate_id in (100, 101, 102))


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_experiment_common_fallback_pops_queue_once_and_marks_unknown_propensity(
    monkeypatch, enabled
):
    from src.recommendations.broadcast_pick import pick_exploration_meme

    monkeypatch.setattr(
        "src.recommendations.broadcast_pick.settings.BROADCAST_HIGH_QUALITY_PICK_ENABLED", enabled
    )
    queue_meme = MemeData(
        id=9, type=MemeType.IMAGE, telegram_file_id="q", caption=None, recommended_by="goat"
    )
    with (
        patch(
            "src.recommendations.broadcast_pick._fetch_exploration_candidates",
            new_callable=AsyncMock,
            return_value=[],
        ) as query,
        patch("src.recommendations.broadcast_pick.check_queue", new_callable=AsyncMock) as check,
        patch(
            "src.recommendations.broadcast_pick.get_next_meme_for_user",
            new_callable=AsyncMock,
            return_value=queue_meme,
        ) as pop,
    ):
        meme, label, metadata = await pick_exploration_meme(7, "explore", "opportunity")
    assert meme is queue_meme
    assert label == BROADCAST_RECOMMENDED_BY
    assert query.await_count == int(enabled)
    check.assert_awaited_once_with(7)
    pop.assert_awaited_once_with(7)
    assert metadata["candidate_ids"] == []
    assert metadata["fallback_reason"] == ("hq_empty" if enabled else "hq_disabled")
    assert metadata["selection_probability"] is None
    assert metadata["joint_probability"] is None
    assert metadata["mixture_probability"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("variant, opportunity", [("bad", "x"), ("hq", "")])
async def test_experiment_rejects_invalid_decision_before_io(variant, opportunity):
    from src.recommendations.broadcast_pick import pick_exploration_meme

    with patch(
        "src.recommendations.broadcast_pick._fetch_exploration_candidates", new_callable=AsyncMock
    ) as query:
        with pytest.raises(ValueError):
            await pick_exploration_meme(7, variant, opportunity)
    query.assert_not_awaited()


@pytest.mark.asyncio
async def test_experiment_sql_timeout_is_local_and_top_three_query_runs_once():
    from unittest.mock import MagicMock

    from src.recommendations.broadcast_pick import _fetch_exploration_candidates

    connection = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = _hq_rows()
    connection.execute.side_effect = [MagicMock(), result]
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=connection)
    transaction.__aexit__ = AsyncMock(return_value=False)
    with patch("src.recommendations.broadcast_pick.engine") as engine:
        engine.begin.return_value = transaction
        rows = await _fetch_exploration_candidates(7)
    assert len(rows) == 3
    assert connection.execute.await_count == 2
    assert str(connection.execute.call_args_list[0].args[0]) == "SET LOCAL statement_timeout = '4s'"
    query = str(connection.execute.call_args_list[1].args[0])
    assert "LIMIT 3" in query
    assert "hq_score NULLS LAST, M.id" in query
    assert connection.execute.call_args_list[1].args[1]["user_id"] == 7
    transaction.__aexit__.assert_awaited_once()


def test_candidate_features_are_json_finite_and_capture_observation_watermarks():
    import json
    from datetime import datetime, timezone

    from src.recommendations.broadcast_pick import _candidate_snapshot, _finite_score

    observed = datetime(2026, 11, 21, tzinfo=timezone.utc)
    row = dict(_hq_rows()[0], observed_at=observed, lr_smoothed=0.75, source_nlikes=4)
    snapshot = _candidate_snapshot(row)
    assert snapshot["observed_at"] == observed.isoformat()
    assert snapshot["source_nlikes"] == 4
    assert snapshot["source_ndislikes"] is None
    assert snapshot["meme_stats_updated_at"] is None
    json.dumps(snapshot, allow_nan=False)
    for invalid in (float("nan"), float("inf"), -float("inf")):
        with pytest.raises(ValueError):
            _candidate_snapshot(dict(row, lr_smoothed=invalid))
        with pytest.raises(ValueError):
            _finite_score(invalid)
