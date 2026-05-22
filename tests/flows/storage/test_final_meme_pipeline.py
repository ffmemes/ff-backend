from unittest.mock import AsyncMock

import pytest

from src.flows.storage import memes
from src.storage.deduplication import DeduplicationResult


@pytest.mark.asyncio
async def test_final_meme_pipeline_deduplicates_batch_before_ok_promotion(monkeypatch):
    calls = []

    class FakeLogger:
        def info(self, *args):
            calls.append(("log_info", args))

    pending_memes = [
        {"id": 10001, "caption": None},
        {"id": 10002, "caption": None},
    ]

    async def fake_analyse(meme):
        calls.append(("analyse", meme["id"]))

    async def fake_deduplicate(meme):
        calls.append(("dedup", meme["id"]))
        return DeduplicationResult(meme["id"])

    async def fake_update_ready(meme_ids):
        calls.append(("promote", meme_ids))
        return [{"id": meme_ids[0]}]

    async def fake_sweep():
        calls.append(("sweep",))
        return {"resolved": 0, "reactions_moved": 0, "reactions_dropped": 0}

    monkeypatch.setattr(memes, "get_run_logger", lambda: FakeLogger())
    monkeypatch.setattr(memes, "get_pending_memes", AsyncMock(return_value=pending_memes))
    monkeypatch.setattr(memes, "analyse_meme_caption", fake_analyse)
    monkeypatch.setattr(memes, "deduplicate_pending_meme", fake_deduplicate)
    monkeypatch.setattr(memes, "update_meme_status_of_ready_memes", fake_update_ready)
    monkeypatch.setattr(memes, "sweep_file_id_duplicates", fake_sweep)
    monkeypatch.setattr(memes, "safe_emit", lambda *args, **kwargs: calls.append(("emit", args)))

    await memes.final_meme_pipeline.fn()

    assert calls.index(("dedup", 10001)) < calls.index(("promote", [10001, 10002]))
    assert calls.index(("dedup", 10002)) < calls.index(("promote", [10001, 10002]))
    assert calls.index(("promote", [10001, 10002])) < calls.index(("sweep",))
