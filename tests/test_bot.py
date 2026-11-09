"""Offline tests: Transitous (MOTIS 2) responses are mocked with the real shape."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import respx

from db_bot import bot
from db_bot.api import ApiError, Departure, DbApi
from db_bot.formatting import format_departures, format_journeys

BASE = "https://api.test/api"

GEOCODE = [
    {"type": "STOP", "id": "de-DELFI_bus", "name": "Aachen, Hauptbahnhof (Bus)", "modes": ["BUS"]},
    {"type": "STOP", "id": "be-sncb_8015345", "name": "Aachen Hbf", "modes": ["REGIONAL_RAIL", "BUS"]},
    {"type": "ADDRESS", "id": "addr", "name": "Somewhere"},
]


def _place(sched, actual, track=None, sched_track=None, name="Aachen, Hbf", **extra):
    return {
        "name": name, "scheduledDeparture": sched, "departure": actual,
        "scheduledArrival": sched, "arrival": actual,
        "track": track, "scheduledTrack": sched_track, **extra,
    }


STOPTIMES = {
    "stopTimes": [
        {"displayName": "ICE 17", "headsign": "Frankfurt (Main) Hbf", "mode": "HIGHSPEED_RAIL",
         "place": _place("2026-11-09T14:38:00Z", "2026-11-09T14:40:00Z", "9", "8")},
        {"displayName": "RB33 (10380)", "headsign": "Heinsberg", "mode": "REGIONAL_RAIL",
         "place": _place("2026-11-09T14:37:00Z", "2026-11-09T14:37:00Z")},
        {"displayName": "RE1", "headsign": "Hamm", "mode": "REGIONAL_RAIL", "cancelled": True,
         "place": _place("2026-11-09T14:51:00Z", "2026-11-09T14:51:00Z")},
    ]
}

PLAN = {
    "itineraries": [{
        "legs": [
            {"mode": "WALK", "from": _place("2026-11-09T14:30:00Z", "2026-11-09T14:30:00Z", name="A"),
             "to": _place("2026-11-09T14:35:00Z", "2026-11-09T14:35:00Z", name="Aachen, Hbf")},
            {"mode": "HIGHSPEED_RAIL", "displayName": "ICE 17",
             "from": _place("2026-11-09T14:38:00Z", "2026-11-09T14:40:00Z", "9", "9"),
             "to": _place("2026-11-09T15:15:00Z", "2026-11-09T15:15:00Z", name="Köln Hbf")},
        ]
    }]
}


@respx.mock
async def test_find_stations_prefers_rail_and_drops_non_stops():
    respx.get(f"{BASE}/v1/geocode").mock(return_value=httpx.Response(200, json=GEOCODE))
    stations = await DbApi(BASE).find_stations("aachen hbf")
    assert [s.id for s in stations] == ["be-sncb_8015345", "de-DELFI_bus"]


@respx.mock
async def test_departures_use_berlin_time_delay_and_platform():
    route = respx.get(f"{BASE}/v5/stoptimes").mock(return_value=httpx.Response(200, json=STOPTIMES))
    deps = await DbApi(BASE).departures("be-sncb_8015345")
    assert route.calls[0].request.url.params["stopId"] == "be-sncb_8015345"
    ice, rb, re1 = deps
    assert ice.delay_min == 2 and ice.platform == "9" and ice.planned_platform == "8"
    assert rb.line == "RB33"  # trip number stripped
    assert re1.cancelled
    text = format_departures("Aachen Hbf", deps)
    assert "15:38 (+2)" in text  # 14:38 UTC is 15:38 in Berlin
    assert "Pl. 9 ⚠️" in text and "cancelled" in text


@respx.mock
async def test_journeys_hide_walking_and_show_delay():
    respx.get(f"{BASE}/v5/plan").mock(return_value=httpx.Response(200, json=PLAN))
    journeys = await DbApi(BASE).journeys("a", "b")
    assert [leg.line for leg in journeys[0].legs] == ["walk", "ICE 17"]
    text = format_journeys("Aachen Hbf", "Köln Hbf", journeys)
    assert "ICE 17" in text and "walk" not in text and "0 change(s)" in text
    assert "15:40 (+2)" in text


@respx.mock
async def test_api_error_is_wrapped():
    respx.get(f"{BASE}/v1/geocode").mock(return_value=httpx.Response(503))
    try:
        await DbApi(BASE).find_stations("x")
    except ApiError:
        return
    raise AssertionError("expected ApiError")


def test_html_is_escaped():
    d = Departure("RE <1>", "A&B", None, None, 0, None, None, False)
    text = format_departures("S", [d])
    assert "&lt;1&gt;" in text and "A&amp;B" in text


def _update_and_context(args, api):
    update = SimpleNamespace(effective_message=SimpleNamespace(reply_text=AsyncMock()))
    context = SimpleNamespace(
        args=args, application=SimpleNamespace(bot_data={"api": api})
    )
    return update, context


@respx.mock
async def test_departures_command_end_to_end():
    respx.get(f"{BASE}/v1/geocode").mock(return_value=httpx.Response(200, json=GEOCODE))
    respx.get(f"{BASE}/v5/stoptimes").mock(return_value=httpx.Response(200, json=STOPTIMES))
    update, context = _update_and_context(["Aachen", "Hbf"], DbApi(BASE))
    await bot.cmd_departures(update, context)
    sent = update.effective_message.reply_text.call_args.args[0]
    assert "Aachen Hbf" in sent and "ICE 17" in sent


@respx.mock
async def test_route_command_end_to_end():
    respx.get(f"{BASE}/v1/geocode").mock(return_value=httpx.Response(200, json=GEOCODE))
    respx.get(f"{BASE}/v5/plan").mock(return_value=httpx.Response(200, json=PLAN))
    update, context = _update_and_context(["Aachen", "Hbf", ">", "Köln", "Hbf"], DbApi(BASE))
    await bot.cmd_route(update, context)
    assert "ICE 17" in update.effective_message.reply_text.call_args.args[0]


@respx.mock
async def test_command_survives_api_outage():
    respx.get(f"{BASE}/v1/geocode").mock(side_effect=httpx.ConnectError("dns"))
    update, context = _update_and_context(["Aachen"], DbApi(BASE))
    await bot.cmd_departures(update, context)
    assert "isn't responding" in update.effective_message.reply_text.call_args.args[0]
