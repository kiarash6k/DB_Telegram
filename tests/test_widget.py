import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import respx
from telegram.error import BadRequest

from db_bot import bot
from db_bot.api import BERLIN, DbApi, Departure
from db_bot.api import Journey, Leg
from db_bot.widget import (
    MAX_DATA_BYTES,
    TRIP_HTML,
    WIDGET_HTML,
    WidgetState,
    WidgetStore,
    encode_board,
    encode_trip,
    html_fits,
)

from test_bot import BASE, GEOCODE, PLAN, STOPTIMES

NOW = datetime(2026, 11, 9, 15, 40, tzinfo=BERLIN)


def _dep(i):
    return Departure(f"RE{i}", "Some Very Long Destination Name Hauptbahnhof", NOW, NOW, 3, "12", "11", False)


def test_widget_html_within_telegram_limits():
    for html in (WIDGET_HTML, TRIP_HTML):
        assert len(html.encode()) <= 32768 and html_fits(html)


def test_encode_board_fits_and_drops_rows_when_too_big():
    text = encode_board("Aachen Hbf", [_dep(i) for i in range(60)], now=NOW)
    assert len(text.encode()) <= MAX_DATA_BYTES
    data = json.loads(text)
    assert data["s"] == "Aachen Hbf" and data["t"] == "15:40" and 0 < len(data["d"]) < 60
    assert data["d"][0][:2] == ["15:40", 3] and data["d"][0][6] == 1  # platform changed


def test_encode_board_unicode_stays_in_byte_limit():
    deps = [Departure("ICE 1", "Nürnberg Hauptbahnhof Süd", NOW, NOW, 0, "1", "1", False)] * 60
    assert len(encode_board("München Hbf", deps, now=NOW).encode()) <= MAX_DATA_BYTES


def test_store_roundtrip():
    store = WidgetStore(":memory:")
    state = WidgetState("trip", "a", "A", "b", "B", "2026-11-09T10:00:00Z", "2026-11-09T11:00:00Z")
    store.save(1, 2, state)
    assert store.get(1, 2) == state and store.get(1, 3) is None


class FakeBot:
    def __init__(self, fail_send=False):
        self.calls, self.fail_send = [], fail_send

    async def do_api_request(self, endpoint, api_kwargs=None, **_):
        self.calls.append((endpoint, api_kwargs))
        if endpoint == "sendWidget":
            if self.fail_send:
                raise BadRequest("method not found")
            return {"message_id": 77}
        return True


def _ctx(api, fake_bot, args=()):
    app = SimpleNamespace(bot_data={"api": api, "widgets": WidgetStore(":memory:")})
    return SimpleNamespace(args=list(args), application=app, bot=fake_bot)


def _msg_update(chat_type="private"):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=5, type=chat_type),
        effective_message=SimpleNamespace(reply_text=AsyncMock()),
    )


@respx.mock
async def test_board_sends_widget_and_remembers_station():
    respx.get(f"{BASE}/v1/geocode").mock(return_value=httpx.Response(200, json=GEOCODE))
    respx.get(f"{BASE}/v5/stoptimes").mock(return_value=httpx.Response(200, json=STOPTIMES))
    fake = FakeBot()
    ctx = _ctx(DbApi(BASE), fake, ["Aachen", "Hbf"])
    await bot.cmd_board(_msg_update(), ctx)
    endpoint, kw = fake.calls[0]
    assert endpoint == "sendWidget" and kw["chat_id"] == 5 and kw["allow_queries"] is True
    assert kw["html"] == WIDGET_HTML and json.loads(kw["chat_data"])["s"] == "Aachen Hbf"
    assert ctx.application.bot_data["widgets"].get(5, 77) == WidgetState("board", "be-sncb_8015345", "Aachen Hbf")


@respx.mock
async def test_board_falls_back_to_text_if_widget_rejected():
    respx.get(f"{BASE}/v1/geocode").mock(return_value=httpx.Response(200, json=GEOCODE))
    respx.get(f"{BASE}/v5/stoptimes").mock(return_value=httpx.Response(200, json=STOPTIMES))
    update = _update = _msg_update()
    await bot.cmd_board(update, _ctx(DbApi(BASE), FakeBot(fail_send=True), ["Aachen"]))
    assert "ICE 17" in update.effective_message.reply_text.call_args.args[0]


async def test_board_refuses_group_chats():
    update = _msg_update("supergroup")
    fake = FakeBot()
    await bot.cmd_board(update, _ctx(DbApi(BASE), fake, ["Aachen"]))
    assert not fake.calls and "private" in update.effective_message.reply_text.call_args.args[0]


def _query_update(message_id=77):
    q = {"id": "q1", "chat": {"id": 5}, "message_id": message_id, "data": "r"}
    return SimpleNamespace(api_kwargs={"widget_query": q})


@respx.mock
async def test_refresh_query_answers_with_fresh_data_and_edits_message():
    respx.get(f"{BASE}/v5/stoptimes").mock(return_value=httpx.Response(200, json=STOPTIMES))
    fake = FakeBot()
    ctx = _ctx(DbApi(BASE), fake)
    ctx.application.bot_data["widgets"].save(5, 77, WidgetState("board", "be-sncb_8015345", "Aachen Hbf"))
    await bot.on_widget_query(_query_update(), ctx)
    (ep1, kw1), (ep2, kw2) = fake.calls
    assert ep1 == "answerWidgetQuery" and kw1["widget_query_id"] == "q1"
    assert json.loads(kw1["data"])["d"][0][2] == "ICE 17"
    assert ep2 == "editMessageWidgetData" and kw2["message_id"] == 77 and kw2["chat_data"] == kw1["data"]


async def test_refresh_for_unknown_widget_still_answers():
    fake = FakeBot()
    await bot.on_widget_query(_query_update(message_id=1), _ctx(DbApi(BASE), fake))
    assert fake.calls == [("answerWidgetQuery", {"widget_query_id": "q1"})]


async def test_other_updates_are_ignored():
    fake = FakeBot()
    await bot.on_widget_query(SimpleNamespace(api_kwargs={}), _ctx(DbApi(BASE), fake))
    assert not fake.calls
