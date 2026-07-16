from unittest.mock import AsyncMock, patch

import pytest

from src.recommendations.candidates import (
    COLD_START_ADAPT_GUARDED_RECOMMENDED_BY,
    COLD_START_ADAPT_RECOMMENDED_BY,
    COLD_START_EXPLORE_GUARDED_RECOMMENDED_BY,
    COLD_START_GUARDRAIL_SOURCE_URLS,
    cold_start_adapt,
    cold_start_explore,
)


def _fetch_call_sql_and_params(fetch_all: AsyncMock) -> tuple[str, dict]:
    query, params = fetch_all.call_args.args
    return str(query), params


@pytest.mark.asyncio
async def test_cold_start_explore_guardrails_exclude_weak_sources_and_mark_treatment():
    with patch(
        "src.recommendations.candidates.fetch_all",
        new_callable=AsyncMock,
        return_value=[],
    ) as fetch_all:
        await cold_start_explore(123, limit=5, candidate_guardrails_enabled=True)

    query_sql, params = _fetch_call_sql_and_params(fetch_all)
    assert "INNER JOIN meme_source S" in query_sql
    assert "S.url = ANY(:cold_start_guardrail_source_urls)" in query_sql
    assert params["recommended_by"] == COLD_START_EXPLORE_GUARDED_RECOMMENDED_BY
    assert params["cold_start_guardrail_source_urls"] == list(COLD_START_GUARDRAIL_SOURCE_URLS)


@pytest.mark.asyncio
async def test_cold_start_adapt_guardrails_exclude_weak_sources_and_mark_treatment():
    with patch(
        "src.recommendations.candidates.fetch_all",
        new_callable=AsyncMock,
        return_value=[],
    ) as fetch_all:
        await cold_start_adapt(123, limit=5, candidate_guardrails_enabled=True)

    query_sql, params = _fetch_call_sql_and_params(fetch_all)
    assert "INNER JOIN meme_source S" in query_sql
    assert "S.url = ANY(:cold_start_guardrail_source_urls)" in query_sql
    assert params["recommended_by"] == COLD_START_ADAPT_GUARDED_RECOMMENDED_BY
    assert params["cold_start_guardrail_source_urls"] == list(COLD_START_GUARDRAIL_SOURCE_URLS)


@pytest.mark.asyncio
async def test_cold_start_guardrails_default_off_preserves_control_query():
    with patch(
        "src.recommendations.candidates.fetch_all",
        new_callable=AsyncMock,
        return_value=[],
    ) as fetch_all:
        await cold_start_adapt(123, limit=5)

    query_sql, params = _fetch_call_sql_and_params(fetch_all)
    assert "cold_start_guardrail_source_urls" not in query_sql
    assert "cold_start_guardrail_source_urls" not in params
    assert params["recommended_by"] == COLD_START_ADAPT_RECOMMENDED_BY
