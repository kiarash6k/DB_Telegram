import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import respx

from db_bot import bot
from db_bot.api import BERLIN, DbApi, Journey, Leg
from db_bot.widget import MAX_DATA_BYTES, WidgetState, WidgetStore, encode_trip

from test_bot import BASE, GEOCODE, PLAN
from test_widget import FakeBot

NOW = datetime(2026, 11, 9, 15, 40, tzinfo=BERLIN)


def _leg(line, dest, dep_min, dur, delay=0, plat="9", cancelled=False):
    dep = NOW + timedelta(minutes=dep_min + delay)
    return Leg(line, "x", dest, dep, dep + timedelta(minutes=dur), delay, 0, plat, cancelled)


def _journey(n_legs=2, start=0):
    legs = [_leg("walk", "Stop", start, 5)]
    for i in range(n_legs):
        legs.append(_leg(f"ICE {100 + i}", f"Some Long Station Name {i}", start + 10 + 40 * i, 30, delay=i + 1))
    return Journey(legs)


def test_encode_trip_structure_and_planned_times():
    data = json.loads(encode_trip("A", "B", [_journey(2)], now=NOW))
    assert data["o"] == "A" and data["d"] == "B" and data["t"] == "15:40"
    walk, ice1, _ = data["i"][0]
    assert walk[0] == "Walk" and walk[6] == ""
    # planned time = actual time minus delay
    assert ice1[2] == "15:50" and ice1[3] == 1 and ice1[4] == "16:21" and ice1[7] == 0


def test_encode_trip_drops_alternatives_to_fit_and_keeps_one():
    journeys = [_journey(4, start=i * 20) for i in range(4)]
    text = encode_trip("Aachen Hauptbahnhof", "München Hauptbahnhof", journeys, now=NOW)
    assert len(text.encode()) <= MAX_DATA_BYTES
    assert 1 <= len(json.loads(text)["i"]) < 4


def test_encode_trip_skips_walk_only_and_names_end_placeholder():
    walk_only = Journey([_leg("walk", "END", 0, 5)])
    ride = Journey([_leg("RE1", "END", 0, 30)])
    data = json.loads(encode_trip("A", "Köln Hbf", [walk_only, ride], now=NOW))
    assert len(data["i"]) == 1 and data["i"][0][0][1] == "Köln Hbf"


def test_parse_trip():
    assert bot._parse_trip("Aachen Hbf > Köln Hbf") == ("Aachen Hbf", "Köln Hbf", None)
    assert bot._parse_trip("Aachen Hbf → Köln Hbf at 18:30") == ("Aachen Hbf", "Köln Hbf", (18, 30))
    assert bot._parse_trip("> Köln Hbf at 7.05") == ("", "Köln Hbf", (7, 5))
    assert bot._parse_trip("Köln Hbf") is None and bot._parse_trip("A > ") is None
    assert bot._parse_trip("A > B at 25:00") is None


def _ctx(api, fake, args=(), user_data=None):
    app = SimpleNamespace(bot_data={"api": api, "widgets": WidgetStore(":memory:")})
    return SimpleNamespace(args=list(args), application=app, bot=fake, user_data=user_data if user_data is not None else {})


def _update():
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=5, type="private"),
        effective_message=SimpleNamespace(reply_text=AsyncMock()),
    )


@respx.mock
async def test_trip_command_sends_widget_and_stores_state():
    respx.get(f"{BASE}/v1/geocode").mock(return_value=httpx.Response(200, json=GEOCODE))
    route = respx.get(f"{BASE}/v5/plan").mock(return_value=httpx.Response(200, json=PLAN))
    fake = FakeBot()
    ctx = _ctx(DbApi(BASE), fake, ["Aachen", "Hbf", ">", "Köln", "Hbf", "at", "23:59"])
    await bot.cmd_trip(_update(), ctx)
    endpoint, kw = fake.calls[0]
    assert endpoint == "sendWidget" and kw["allow_queries"] is True
    assert "time" in route.calls[0].request.url.params
    state = ctx.application.bot_data["widgets"].get(5, 77)
    assert state.kind == "trip" and state.a_id == "be-sncb_8015345" and state.after.endswith("Z")


@respx.mock
async def test_trip_from_my_location_uses_coordinates():
    respx.get(f"{BASE}/v1/geocode").mock(return_value=httpx.Response(200, json=GEOCODE))
    route = respx.get(f"{BASE}/v5/plan").mock(return_value=httpx.Response(200, json=PLAN))
    ctx = _ctx(DbApi(BASE), FakeBot(), ["", ">", "Köln"], user_data={"loc": "50.77530,6.08390"})
    ctx.args = [">", "Köln"]
    await bot.cmd_trip(_update(), ctx)
    assert route.calls[0].request.url.params["fromPlace"] == "50.77530,6.08390"
    assert ctx.application.bot_data["widgets"].get(5, 77).a_name == bot.MY_LOCATION


async def test_trip_without_location_asks_for_it():
    update = _update()
    ctx = _ctx(DbApi(BASE), FakeBot(), [">", "Köln"])
    await bot.cmd_trip(update, ctx)
    assert "location" in update.effective_message.reply_text.call_args.args[0]


def _query(code):
    return SimpleNamespace(api_kwargs={"widget_query": {"id": "q9", "chat": {"id": 5}, "message_id": 77, "data": code}})


def _trip_ctx():
    fake = FakeBot()
    ctx = _ctx(DbApi(BASE), fake)
    state = WidgetState("trip", "A_ID", "Aachen Hbf", "B_ID", "Köln Hbf", "", "2026-11-09T14:51:00Z")
    ctx.application.bot_data["widgets"].save(5, 77, state)
    return ctx, fake


@respx.mock
async def test_swap_reverses_direction():
    route = respx.get(f"{BASE}/v5/plan").mock(return_value=httpx.Response(200, json=PLAN))
    ctx, fake = _trip_ctx()
    await bot.on_widget_query(_query("s"), ctx)
    params = route.calls[0].request.url.params
    assert params["fromPlace"] == "B_ID" and params["toPlace"] == "A_ID"
    data = json.loads(fake.calls[0][1]["data"])
    assert data["o"] == "Köln Hbf" and data["d"] == "Aachen Hbf"
    assert ctx.application.bot_data["widgets"].get(5, 77).a_name == "Köln Hbf"


@respx.mock
async def test_later_searches_after_last_seen_departure():
    route = respx.get(f"{BASE}/v5/plan").mock(return_value=httpx.Response(200, json=PLAN))
    ctx, fake = _trip_ctx()
    await bot.on_widget_query(_query("n"), ctx)
    assert route.calls[0].request.url.params["time"] == "2026-11-09T14:52:00Z"
    assert fake.calls[0][0] == "answerWidgetQuery" and "data" in fake.calls[0][1]


@respx.mock
async def test_later_with_no_results_answers_empty_and_keeps_state():
    respx.get(f"{BASE}/v5/plan").mock(return_value=httpx.Response(200, json={"itineraries": []}))
    ctx, fake = _trip_ctx()
    await bot.on_widget_query(_query("n"), ctx)
    assert fake.calls == [("answerWidgetQuery", {"widget_query_id": "q9"})]
    assert ctx.application.bot_data["widgets"].get(5, 77).seen == "2026-11-09T14:51:00Z"


@respx.mock
async def test_refresh_and_api_outage():
    respx.get(f"{BASE}/v5/plan").mock(side_effect=httpx.ConnectError("down"))
    ctx, fake = _trip_ctx()
    await bot.on_widget_query(_query("r"), ctx)
    assert fake.calls == [("answerWidgetQuery", {"widget_query_id": "q9"})]  # no crash, empty answer


def test_clean_name():
    from db_bot.api import clean_name
    assert clean_name("AACHEN Hauptbahnhof") == "Aachen Hbf"
    assert clean_name("S+U Berlin Hauptbahnhof") == "Berlin Hbf"
    assert clean_name("Frankfurt (Main) Hauptbahnhof") == "Frankfurt (Main) Hbf"
    assert clean_name("Köln Hbf") == "Köln Hbf" and clean_name("RE") == "RE"


def test_long_names_get_an_ellipsis_not_a_cut_word():
    ride = Journey([_leg("RE1", "Eschweiler-Weisweiler Industriegebiet", 0, 30)])
    leg = json.loads(encode_trip("A", "B", [ride], now=NOW))["i"][0][0]
    assert leg[1].endswith("…") and len(leg[1]) <= 18
