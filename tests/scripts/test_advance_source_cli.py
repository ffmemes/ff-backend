"""Argparse-only sanity tests for the admin source CLI (FFM-1154).

The DB-touching path is covered by `tests/storage/test_moderation.py`.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from scripts.admin import advance_source as cli


def test_parser_accepts_status_and_language():
    parser = cli._build_parser()
    args = parser.parse_args(
        [
            "--id",
            "21848",
            "--language",
            "ru",
            "--status",
            "parsing_enabled",
            "--moderator-id",
            "agent:cto",
        ]
    )
    assert args.meme_source_id == 21848
    assert args.language_code == "ru"
    assert args.status == "parsing_enabled"
    assert args.moderator_id == "agent:cto"
    assert args.trigger_parse is True


def test_parser_no_trigger_parse_flag():
    parser = cli._build_parser()
    args = parser.parse_args(
        [
            "--id",
            "1",
            "--status",
            "snoozed",
            "--moderator-id",
            "x",
            "--no-trigger-parse",
        ]
    )
    assert args.trigger_parse is False


def test_parser_rejects_unknown_status():
    parser = cli._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--id",
                "1",
                "--status",
                "bogus",
                "--moderator-id",
                "x",
            ]
        )


@pytest.mark.asyncio
async def test_run_passes_args_to_service_and_emits_json(capsys):
    fake_source = {
        "status": "parsing_enabled",
        "language_code": "ru",
    }
    fake_result = {
        "source": fake_source,
        "before_status": "in_moderation",
        "before_language_code": None,
        "snoozed_count": 0,
        "unsnoozed_count": 0,
        "parsed": True,
    }
    args = cli._build_parser().parse_args(
        [
            "--id",
            "21848",
            "--language",
            "ru",
            "--status",
            "parsing_enabled",
            "--moderator-id",
            "agent:cto",
        ]
    )
    with patch.object(
        cli, "advance_meme_source", new=AsyncMock(return_value=fake_result)
    ) as mock_advance:
        rc = await cli._run(args)

    assert rc == 0
    mock_advance.assert_awaited_once_with(
        21848,
        moderator_id="agent:cto",
        language_code="ru",
        status="parsing_enabled",
        trigger_parse=True,
    )
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["after_status"] == "parsing_enabled"
    assert out["before_status"] == "in_moderation"
    assert out["moderator_id"] == "agent:cto"


@pytest.mark.asyncio
async def test_run_returns_error_on_missing_source(capsys):
    from src.storage.moderation import MemeSourceNotFoundError

    args = cli._build_parser().parse_args(
        [
            "--id",
            "999999",
            "--status",
            "parsing_enabled",
            "--moderator-id",
            "agent:cto",
        ]
    )
    with patch.object(
        cli,
        "advance_meme_source",
        new=AsyncMock(side_effect=MemeSourceNotFoundError("not found")),
    ):
        rc = await cli._run(args)

    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out == {"ok": False, "error": "not_found", "message": "not found"}


@pytest.mark.asyncio
async def test_run_returns_error_when_no_change_requested(capsys):
    args = cli._build_parser().parse_args(
        [
            "--id",
            "21848",
            "--moderator-id",
            "agent:cto",
        ]
    )
    rc = await cli._run(args)
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["error"] == "no_change_requested"


@pytest.mark.asyncio
async def test_run_show_only_prints_source(capsys):
    args = cli._build_parser().parse_args(
        [
            "--id",
            "21848",
            "--moderator-id",
            "agent:cto",
            "--show",
        ]
    )
    with patch.object(
        cli,
        "get_source",
        new=AsyncMock(return_value={"id": 21848, "status": "in_moderation"}),
    ):
        rc = await cli._run(args)

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["source"]["id"] == 21848
