"""Scheduled crosspost flows post at most one meme per catch-up burst."""

from unittest.mock import AsyncMock

import pytest

from src.flows.crossposting import meme as flow_mod


class _Log:
    def info(self, *a, **k): ...
    def warning(self, *a, **k): ...
    def error(self, *a, **k): ...


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "flow", [flow_mod.post_meme_to_tgchannelru, flow_mod.post_meme_to_tgchannelen]
)
async def test_skips_when_posted_recently(monkeypatch, flow):
    monkeypatch.setattr(flow_mod, "get_run_logger", lambda: _Log())
    monkeypatch.setattr(flow_mod, "posted_recently", AsyncMock(return_value=True))
    pick = AsyncMock(return_value=(None, None))
    monkeypatch.setattr(flow_mod, "get_next_meme_for_channel", pick)
    await flow.fn()
    pick.assert_not_awaited()


@pytest.mark.asyncio
async def test_runs_picker_when_not_posted_recently(monkeypatch):
    monkeypatch.setattr(flow_mod, "get_run_logger", lambda: _Log())
    monkeypatch.setattr(flow_mod, "posted_recently", AsyncMock(return_value=False))
    pick = AsyncMock(return_value=(None, None))
    monkeypatch.setattr(flow_mod, "get_next_meme_for_channel", pick)
    await flow_mod.post_meme_to_tgchannelru.fn()
    pick.assert_awaited_once()
