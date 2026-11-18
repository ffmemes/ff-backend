"""Synthetic webhook journeys. Run with bash scripts/qa_first_five_reactions.sh."""

import asyncio
import json
import os
import socket
from itertools import count
from secrets import randbelow
from time import time
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from telegram.ext import Application
from telegram.request import BaseRequest, HTTPXRequest
from tests.factories import create_meme, create_meme_source, create_meme_stats

from src import localizer
from src.config import settings
from src.database import engine, meme, meme_source, user_language
from src.recommendations.service import get_user_reactions
from src.redis import (
    get_all_memes_in_queue_by_key,
    get_meme_queue_key,
    get_user_info_key,
    redis_client,
)
from src.tgbot import app, user_info
from src.tgbot.bot import bot as default_bot
from src.tgbot.service import get_user_languages

pytestmark = pytest.mark.skipif(
    "FIRST_FIVE_QA_DATABASE" not in os.environ,
    reason="requires the dedicated disposable services in scripts/qa_first_five_reactions.sh",
)

BOT_USER = {"id": 12345, "is_bot": True, "first_name": "QA", "username": "first_five_qa_bot"}
CAPTIONS = {"ru": "Синтетический мем", "en": "Synthetic meme"}
CATALOG = {"ru": range(80100, 80116), "en": range(80200, 80216)}
METRIC = text("""
    SELECT acquisition_channel, got_first_meme, first_tap, reached_5_reactions
    FROM v_new_user WHERE user_id = :uid AND segment <> 'excluded'
""")


class OfflineTelegram(BaseRequest):
    """Record real PTB requests and return minimal Bot API message JSON."""

    read_timeout = None

    def __init__(self):
        self.calls = []
        self.errors = []
        self.messages = {}
        self.ids = count(100)

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        params = request_data.parameters if request_data else {}
        if endpoint == "getMe":
            result = BOT_USER
        elif endpoint == "answerCallbackQuery":
            result = True
        else:
            chat_id = int(params["chat_id"])
            if endpoint == "deleteMessage" and (chat_id, params["message_id"]) not in self.messages:
                self.calls.append((endpoint, params, None))
                response = {
                    "ok": False,
                    "error_code": 400,
                    "description": "Bad Request: message to delete not found",
                }
                return 400, json.dumps(response).encode()
            try:
                result = self.apply_message_method(chat_id, endpoint, params)
            except Exception as exc:
                self.errors.append(exc)
                raise
        self.calls.append((endpoint, params, result))
        return 200, json.dumps({"ok": True, "result": result}).encode()

    def apply_message_method(self, chat_id, endpoint, params):
        if endpoint in {"sendMessage", "sendPhoto"}:
            msg = {
                "message_id": next(self.ids),
                "date": int(time()),
                "chat": {"id": chat_id, "type": "private" if chat_id > 0 else "supergroup"},
                "from": BOT_USER,
            }
        else:
            msg = self.messages[chat_id, params["message_id"]].copy()

        key = chat_id, msg["message_id"]
        if endpoint == "deleteMessage":
            del self.messages[key]
            return True
        if endpoint in {"sendMessage", "editMessageText"}:
            msg["text"] = params["text"]
        elif endpoint in {"sendPhoto", "editMessageMedia"}:
            media = params["media"] if endpoint == "editMessageMedia" else params
            file_id = media["media"] if endpoint == "editMessageMedia" else media["photo"]
            msg["photo"] = [
                {"file_id": file_id, "file_unique_id": file_id, "width": 1, "height": 1}
            ]
            msg["caption"] = media["caption"]
        elif endpoint == "editMessageCaption":
            msg["caption"] = params["caption"]
        else:
            raise AssertionError(f"Unsupported Bot API method: {endpoint}")
        if "reply_markup" in params:
            msg["reply_markup"] = params["reply_markup"]
        self.messages[key] = msg
        return msg


@pytest_asyncio.fixture(scope="module")
async def catalog():
    async with engine.begin() as conn:
        expected_db = os.environ["FIRST_FIVE_QA_DATABASE"]
        assert expected_db.startswith("first_five_")
        assert engine.url.host == "127.0.0.1"
        assert engine.url.port == int(os.environ["FIRST_FIVE_QA_PG_PORT"])
        assert (await conn.scalar(text("SELECT current_database()"))) == expected_db
        head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
        assert (await conn.scalar(text("SELECT version_num FROM alembic_version"))) == head
        assert (await conn.scalar(text("SELECT count(*) FROM meme"))) == 0
        # Historical role migrations seed two accounts even in a fresh schema.
        assert (await conn.scalar(text("SELECT count(*) FROM user_tg"))) == 0
        assert (await conn.scalar(text("SELECT count(*) FROM user_meme_reaction"))) == 0
        print(f"Fixture upgrade verified at {head}; catalog, Telegram users and reactions empty")
        for lang, ids in CATALOG.items():
            await create_meme_source(conn, ids.start, language_code=lang)
            for n, meme_id in enumerate(ids):
                await create_meme(
                    conn,
                    meme_id,
                    ids.start,
                    language_code=lang,
                    telegram_file_id=f"synthetic-{lang}-{n}",
                    caption=f"{CAPTIONS[lang]} {n}",
                )
                await create_meme_stats(
                    conn,
                    meme_id,
                    nlikes=40,
                    ndislikes=10,
                    nmemes_sent=50,
                    lr_smoothed=0.30 - n * 0.005,
                )
    yield
    # The legacy downgrade recreates an empty language table, then restores its FKs.
    # Remove only the catalog this fixture inserted before the session downgrade.
    async with engine.begin() as conn:
        for ids in CATALOG.values():
            await conn.execute(meme.delete().where(meme.c.id.in_(list(ids))))
            await conn.execute(meme_source.delete().where(meme_source.c.id == ids.start))
    await redis_client.connection_pool.disconnect()
    await engine.dispose()


@pytest_asyncio.fixture
async def telegram(monkeypatch, catalog, caplog):
    blocked = []
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    getaddrinfo = socket.getaddrinfo
    local_endpoints = {
        ("127.0.0.1", int(os.environ["FIRST_FIVE_QA_PG_PORT"])),
        ("127.0.0.1", int(os.environ["FIRST_FIVE_QA_REDIS_PORT"])),
    }

    def check_endpoint(address):
        if address not in local_endpoints:
            blocked.append("socket")
            raise AssertionError("The journey attempted a connection outside its fixtures")

    def allow_local_only(operation):
        def checked(sock, address):
            check_endpoint(address)
            return operation(sock, address)

        return checked

    async def reject_http(*args, **kwargs):
        blocked.append("Telegram HTTP")
        raise AssertionError("A request escaped the fake Telegram transport")

    def local_getaddrinfo(host, port, *args, **kwargs):
        check_endpoint((host, port))
        return getaddrinfo(host, port, *args, **kwargs)

    transport = OfflineTelegram()
    monkeypatch.setattr(socket.socket, "connect", allow_local_only(connect))
    monkeypatch.setattr(socket.socket, "connect_ex", allow_local_only(connect_ex))
    monkeypatch.setattr(socket, "getaddrinfo", local_getaddrinfo)
    monkeypatch.setattr(HTTPXRequest, "do_request", reject_http)
    monkeypatch.setattr(default_bot, "_request", (transport, transport))
    application = (
        Application.builder()
        .updater(None)
        .token(settings.TELEGRAM_BOT_TOKEN)
        .request(transport)
        .get_updates_request(transport)
        .build()
    )
    app.add_handlers(application)
    original_error_handler = next(iter(application.error_handlers))
    application.remove_error_handler(original_error_handler)

    async def capture_error(update, context):
        transport.errors.append(context.error)

    application.add_error_handler(capture_error)
    monkeypatch.setattr(app, "application", application)
    async with application:
        yield transport
    assert blocked == []
    assert transport.errors == []
    assert all("check_queue failed" not in record.message for record in caplog.get_records("call"))
    print(f"Bot API: {len(transport.calls)} fake requests, 0 network requests or escapes")


class Journey:
    def __init__(self, transport, locale):
        self.transport = transport
        # tests/conftest.py downgrades through the legacy 32-bit message_tg schema.
        self.uid = 1_100_000_000 + randbelow(900_000_000)
        self.locale = locale
        self.ids = count(1)
        self.user = {
            "id": self.uid,
            "is_bot": False,
            "first_name": "Тест" if locale == "ru" else "QA",
            "language_code": locale,
        }

    async def dispatch(self, payload):
        offset = len(self.transport.calls)
        before = asyncio.all_tasks()
        await app.process_event(payload)
        # The reaction handler and sender schedule follow-up work outside PTB.
        pending = asyncio.all_tasks() - before
        if pending:
            await asyncio.wait_for(asyncio.gather(*pending), timeout=10)
        if self.transport.errors:
            raise self.transport.errors[0]
        return [
            (method, result)
            for method, params, result in self.transport.calls[offset:]
            if params.get("chat_id") == self.uid
        ]

    async def command(self, command):
        event_id = next(self.ids)
        return await self.dispatch(
            {
                "update_id": event_id,
                "message": {
                    "message_id": event_id,
                    "date": int(time()),
                    "from": self.user,
                    "chat": {"id": self.uid, "type": "private"},
                    "text": command,
                    "entities": [{"type": "bot_command", "offset": 0, "length": len(command)}],
                },
            }
        )

    def callback(self, message, data=None, *, suffix=None):
        options = [
            button["callback_data"]
            for row in message["reply_markup"]["inline_keyboard"]
            for button in row
            if "callback_data" in button
        ]
        (chosen,) = (
            [option for option in options if option.endswith(suffix)]
            if suffix
            else [option for option in options if option == data]
        )
        event_id = next(self.ids)
        return {
            "update_id": event_id,
            "callback_query": {
                "id": str(event_id),
                "from": self.user,
                "chat_instance": str(self.uid),
                "data": chosen,
                "message": message,
            },
        }

    async def tap(self, payload):
        offset = len(self.transport.calls)
        events = await self.dispatch(payload)
        acks = [
            params["callback_query_id"]
            for method, params, _ in self.transport.calls[offset:]
            if method == "answerCallbackQuery"
        ]
        assert acks == [payload["callback_query"]["id"]]
        return events


@pytest_asyncio.fixture
async def journey(telegram, request):
    driver = Journey(telegram, getattr(request, "param", "ru"))
    yield driver
    # The restored legacy FK also applies to each journey's own language rows.
    async with engine.begin() as conn:
        await conn.execute(user_language.delete().where(user_language.c.user_id == driver.uid))


def assert_text(message, key, lang):
    assert message["text"] == localizer.t(key, lang)


def assert_meme(message, lang):
    assert message["photo"][0]["file_id"].startswith(f"synthetic-{lang}-")
    assert message["caption"].startswith(CAPTIONS[lang])
    share_button = message["reply_markup"]["inline_keyboard"][0][0]
    assert share_button["text"] == localizer.t("meme.share_button", lang)


async def activation(uid):
    async with engine.connect() as conn:
        params = {"uid": uid}
        live = (await conn.execute(METRIC, params)).mappings().one()
        # Preserve relative event times while making the view's 8-day gate observable.
        # This connection exits without committing, so the active journey stays new.
        for table, key, columns in (
            ('"user"', "id", ("created_at",)),
            ("user_deep_link_log", "user_id", ("created_at",)),
            ("user_meme_reaction", "user_id", ("sent_at", "reacted_at")),
        ):
            shifted = ", ".join(f"{col} = {col} - interval '9 days'" for col in columns)
            await conn.execute(text(f"UPDATE {table} SET {shifted} WHERE {key} = :uid"), params)
        aged = (await conn.execute(METRIC, params)).mappings().one()
        assert live["acquisition_channel"] == aged["acquisition_channel"] == "organic"
        assert live["got_first_meme"] and aged["got_first_meme"]
        assert live["first_tap"] == aged["first_tap"]
        return live["reached_5_reactions"], aged["reached_5_reactions"], live["first_tap"]


def describe(events):
    return (
        ", ".join(
            f"{method} {msg['photo'][0]['file_id']}"
            if isinstance(msg, dict) and msg.get("photo")
            else method
            for method, msg in events
        )
        or "none"
    )


@pytest.mark.parametrize("journey", ["ru", "en"], indirect=True)
async def test_new_user_reaches_five(journey):
    locale = journey.locale
    switched = "en" if locale == "ru" else "ru"
    assert not await get_user_reactions(journey.uid)
    assert not await redis_client.exists(get_user_info_key(journey.uid))
    async with engine.connect() as conn:
        assert not await conn.scalar(
            text('SELECT EXISTS(SELECT 1 FROM "user" WHERE id = :uid)'), {"uid": journey.uid}
        )

    events = await journey.command("/start")
    expected = ["sendMessage", "sendPhoto"] + (["sendMessage"] if locale == "en" else [])
    print(f"{locale} /start: {describe(events)}; interface={locale}")
    assert [method for method, _ in events] == expected
    assert_text(events[0][1], "onboarding.welcome_message", locale)
    card = events[1][1]
    assert_meme(card, locale)
    assert set(await get_user_languages(journey.uid)) == {locale}
    if locale == "en":
        picker = events[2][1]
        assert_text(picker, "onboarding.pick_language", locale)
        events = await journey.tap(journey.callback(picker, "ol:en"))
        print(f"en picker: {describe(events)}; interface=en")
        assert [method for method, _ in events] == ["deleteMessage", "sendPhoto"]
        card = events[-1][1]
        assert_meme(card, locale)
        assert all(row["reaction_id"] is None for row in await get_user_reactions(journey.uid))

    reacted = set()
    for step, reaction_id in enumerate([1, 2, 1, 2, 1], 1):
        payload = journey.callback(card, suffix=f":{reaction_id}")
        meme_id = int(payload["callback_query"]["data"].split(":")[1])
        reacted.add((meme_id, reaction_id))
        output_lang = switched if step >= 3 else locale
        events = await journey.tap(payload)
        print(f"{locale} reaction {step} on {meme_id}: {describe(events)}; UI={output_lang}")
        assert [method for method, _ in events] == (
            ["sendPhoto"] if reaction_id == 1 else ["editMessageMedia", "editMessageCaption"]
        )
        card = events[-1][1]
        assert_meme(card, output_lang)
        rows = await get_user_reactions(journey.uid)
        assert len({reaction_meme for reaction_meme, _ in reacted}) == step
        assert {
            (row["meme_id"], row["reaction_id"]) for row in rows if row["reaction_id"]
        } == reacted

        if step == 2:
            settings_events = await journey.command("/lang")
            assert [method for method, _ in settings_events] == ["sendMessage"]
            menu = settings_events[0][1]
            assert_text(menu, "onboarding.language_settings", locale)
            for choice in (f"l:{switched}:add", f"l:{locale}:del"):
                [(method, menu)] = await journey.tap(journey.callback(menu, choice))
                assert method == "editMessageText"
            assert_text(menu, "onboarding.language_settings", switched)
            assert set(await get_user_languages(journey.uid)) == {switched}
            assert await journey.tap(journey.callback(menu, "l:end")) == [("deleteMessage", True)]
            print(
                f"{locale} /lang: {locale} -> {switched}; Done deleted menu; card still clickable"
            )

        if step == 4:
            queue_key = get_meme_queue_key(journey.uid)
            queue = await get_all_memes_in_queue_by_key(queue_key)
            assert await journey.tap(payload) == []
            assert await get_user_reactions(journey.uid) == rows
            assert await get_all_memes_in_queue_by_key(queue_key) == queue
            print(f"{locale} duplicate reaction 4: acknowledged; card, rows and queue unchanged")

        if step in (4, 5):
            metric = await activation(journey.uid)
            print(f"{locale} {step} distinct: reached_5 fresh/mature, first_tap = {metric}")
            assert metric == (None, step == 5, locale == "ru")


class DuplicateWatchCount(AssertionError):
    """Only the observed extra cache increment is an expected failure."""


@pytest.mark.xfail(
    strict=True,
    raises=DuplicateWatchCount,
    reason="duplicate callbacks increment the watched counter before reaction deduplication",
)
async def test_duplicate_reaction_does_not_increment_watched_counter(journey, monkeypatch):
    events = await journey.command("/start")
    card = events[1][1]
    payload = journey.callback(card, suffix=":1")
    assert [method for method, _ in await journey.tap(payload)] == ["sendPhoto"]
    persisted = await get_user_reactions(journey.uid)

    writes = AsyncMock(wraps=user_info.cache_user_info)
    monkeypatch.setattr(user_info, "cache_user_info", writes)
    assert await journey.tap(payload) == []
    assert await get_user_reactions(journey.uid) == persisted
    watched_values = [call.args[1]["memes_watched_today"] for call in writes.await_args_list]
    assert sum(row["reaction_id"] is not None for row in persisted) == 1
    print(f"Duplicate-only cache writes for one actual reaction: {watched_values}")
    if any(value > 1 for value in watched_values):
        raise DuplicateWatchCount(f"duplicate wrote {watched_values} with one actual reaction")


class DuplicatePickerDelivery(AssertionError):
    """Only an extra meme on picker replay is an expected failure."""


@pytest.mark.xfail(
    strict=True,
    raises=DuplicatePickerDelivery,
    reason="replayed onboarding language selection sends another meme",
)
@pytest.mark.parametrize("journey", ["en"], indirect=True)
async def test_duplicate_onboarding_picker_does_not_advance_feed(journey):
    events = await journey.command("/start")
    assert [method for method, _ in events] == ["sendMessage", "sendPhoto", "sendMessage"]
    picker = events[-1][1]
    payload = journey.callback(picker, "ol:en")
    assert [method for method, _ in await journey.tap(payload)] == ["deleteMessage", "sendPhoto"]
    before = await get_user_reactions(journey.uid)

    events = await journey.tap(payload)
    after = await get_user_reactions(journey.uid)
    assert all(row["reaction_id"] is None for row in after)
    print(
        f"Duplicate EN picker: {describe(events)}; "
        f"unreacted deliveries {len(before)} -> {len(after)}"
    )
    if any(method == "sendPhoto" for method, _ in events):
        assert len(after) == len(before) + 1
        raise DuplicatePickerDelivery("same picker callback recorded an additional delivery")
    assert after == before
