import httpx
import respx

from db_bot.api import ApiError, DbApi
from db_bot.formatting import format_departures, format_journeys

BASE = "https://api.test"

LOCATIONS = [
    {"type": "stop", "id": "8000001", "name": "Aachen Hbf"},
    {"type": "location", "id": "x", "name": "Some address"},
]
DEPARTURES = {
    "departures": [
        {"plannedWhen": "2026-11-09T10:00:00+01:00", "when": "2026-11-09T10:05:00+01:00",
         "delay": 300, "platform": "5", "plannedPlatform": "4", "direction": "Köln Hbf",
         "line": {"name": "RE 1"}},
        {"plannedWhen": "2026-11-09T10:10:00+01:00", "when": None, "delay": None,
         "direction": "Düren", "line": {"name": "RB 20"}, "cancelled": True},
    ]
}
JOURNEYS = {
    "journeys": [{
        "legs": [
            {"walking": True, "origin": {"name": "A"}, "destination": {"name": "B"}},
            {"line": {"name": "ICE 10"}, "origin": {"name": "Aachen Hbf"},
             "destination": {"name": "Köln Hbf"}, "departure": "2026-11-09T10:00:00+01:00",
             "arrival": "2026-11-09T10:40:00+01:00", "departureDelay": 120,
             "arrivalDelay": 0, "departurePlatform": "6"},
        ]
    }]
}


@respx.mock
async def test_find_stations_filters_non_stops():
    respx.get(f"{BASE}/locations").mock(return_value=httpx.Response(200, json=LOCATIONS))
    api = DbApi(BASE)
    stations = await api.find_stations("aachen")
    assert [s.id for s in stations] == ["8000001"]


@respx.mock
async def test_departures_parse_and_format():
    respx.get(f"{BASE}/stops/8000001/departures").mock(return_value=httpx.Response(200, json=DEPARTURES))
    deps = await DbApi(BASE).departures("8000001")
    assert deps[0].delay_min == 5 and deps[1].cancelled
    text = format_departures("Aachen Hbf", deps)
    assert "10:00 (+5)" in text and "Pl. 5 ⚠️" in text and "cancelled" in text


@respx.mock
async def test_journeys_skip_walking_in_output():
    respx.get(f"{BASE}/journeys").mock(return_value=httpx.Response(200, json=JOURNEYS))
    journeys = await DbApi(BASE).journeys("1", "2")
    text = format_journeys("Aachen Hbf", "Köln Hbf", journeys)
    assert "ICE 10" in text and "walk" not in text and "0 change(s)" in text


@respx.mock
async def test_api_error_is_wrapped():
    respx.get(f"{BASE}/locations").mock(return_value=httpx.Response(503))
    try:
        await DbApi(BASE).find_stations("x")
    except ApiError:
        return
    raise AssertionError("expected ApiError")


def test_html_is_escaped():
    from db_bot.api import Departure
    d = Departure("RE <1>", "A&B", None, None, 0, None, None, False)
    assert "&lt;1&gt;" in format_departures("S", [d]) and "A&amp;B" in format_departures("S", [d])
