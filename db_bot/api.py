"""Async client for Transitous (https://transitous.org), a free MOTIS 2 transit API.

The old transport.rest DB endpoint is gone, so this uses Transitous, which serves
German rail (DB and regional) with live delays and needs no API key.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

DEFAULT_BASE_URL = "https://api.transitous.org/api"
USER_AGENT = "DB_Telegram/0.2 (+https://github.com/kiarash6k/DB_Telegram)"
BERLIN = ZoneInfo("Europe/Berlin")
RAIL_MODES = "HIGHSPEED_RAIL,LONG_DISTANCE,NIGHT_RAIL,REGIONAL_RAIL,SUBURBAN"
RAIL_WORDS = {"HIGHSPEED_RAIL", "LONG_DISTANCE", "NIGHT_RAIL", "REGIONAL_RAIL", "SUBURBAN"}
WALK_MODES = {"WALK", "BIKE", "CAR", "RENTAL", "ODM", "FLEX"}


class ApiError(Exception):
    """The upstream API failed or returned something unusable."""


@dataclass(frozen=True)
class Station:
    id: str
    name: str


@dataclass(frozen=True)
class Departure:
    line: str
    direction: str
    planned: datetime | None
    when: datetime | None
    delay_min: int
    platform: str | None
    planned_platform: str | None
    cancelled: bool


@dataclass(frozen=True)
class Leg:
    line: str  # "walk" for walking legs
    origin: str
    destination: str
    departure: datetime | None
    arrival: datetime | None
    departure_delay_min: int
    arrival_delay_min: int
    platform: str | None
    cancelled: bool


@dataclass(frozen=True)
class Journey:
    legs: list[Leg]


def clean_name(name: str) -> str:
    """Tidy station names: "AACHEN Hauptbahnhof" -> "Aachen Hbf", "S+U Berlin Hbf" -> "Berlin Hbf"."""
    first, _, rest = name.partition(" ")
    if len(first) > 2 and first.isupper() and first.isalpha():
        name = f"{first.capitalize()} {rest}".strip()
    name = re.sub(r"^S\+U\s+", "", name)
    name = re.sub(r"\bHauptbahnhof\b", "Hbf", name)
    return re.sub(r"\bBahnhof\b", "Bf", name)


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value).astimezone(BERLIN) if value else None


def _delay(actual: str | None, scheduled: str | None) -> int:
    a, s = _dt(actual), _dt(scheduled)
    return round((a - s).total_seconds() / 60) if a and s else 0


def _line(item: dict[str, Any]) -> str:
    name = item.get("displayName") or item.get("routeShortName") or item.get("routeLongName") or "?"
    return re.sub(r"\s*\(\d+\)$", "", name)  # drop trip numbers: "RB33 (10380)" -> "RB33"


class DbApi:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(
            base_url=base_url, timeout=20, headers={"User-Agent": USER_AGENT}
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        try:
            resp = await self._client.get(path, params=params)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ApiError(f"{type(exc).__name__}: {exc}") from exc

    async def find_stations(self, query: str, limit: int = 5) -> list[Station]:
        data = await self._get("/v1/geocode", {"text": query, "type": "STOP", "language": "de"})
        stops = [s for s in data if s.get("type") == "STOP" and s.get("id")]
        # Prefer real train stations over bus stops with a similar name.
        stops.sort(key=lambda s: not (RAIL_WORDS & set(s.get("modes", []))))
        return [Station(s["id"], clean_name(s["name"])) for s in stops[:limit]]

    async def departures(self, station_id: str, results: int = 8, **_: Any) -> list[Departure]:
        data = await self._get(
            "/v5/stoptimes", {"stopId": station_id, "n": results, "mode": RAIL_MODES}
        )
        deps = []
        for st in data.get("stopTimes", []):
            place = st.get("place", {})
            dep, sched = place.get("departure"), place.get("scheduledDeparture")
            deps.append(
                Departure(
                    line=_line(st),
                    direction=clean_name(st.get("headsign") or "?"),
                    planned=_dt(sched),
                    when=_dt(dep),
                    delay_min=_delay(dep, sched),
                    platform=place.get("track"),
                    planned_platform=place.get("scheduledTrack"),
                    cancelled=bool(st.get("cancelled") or st.get("tripCancelled")),
                )
            )
        return deps

    async def journeys(
        self, from_id: str, to_id: str, results: int = 3, when: datetime | None = None
    ) -> list[Journey]:
        """Connections between two stop ids or "lat,lon" coordinates, optionally leaving after `when`."""
        params: dict[str, Any] = {"fromPlace": from_id, "toPlace": to_id, "numItineraries": results}
        if when is not None:
            params["time"] = when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = await self._get("/v5/plan", params)
        journeys = []
        for it in data.get("itineraries", []):
            legs = []
            for leg in it.get("legs", []):
                frm, to = leg.get("from", {}), leg.get("to", {})
                legs.append(
                    Leg(
                        line="walk" if leg.get("mode") in WALK_MODES else _line(leg),
                        origin=clean_name(frm.get("name", "?")),
                        destination=clean_name(to.get("name", "?")),
                        departure=_dt(frm.get("departure") or leg.get("startTime")),
                        arrival=_dt(to.get("arrival") or leg.get("endTime")),
                        departure_delay_min=_delay(frm.get("departure"), frm.get("scheduledDeparture")),
                        arrival_delay_min=_delay(to.get("arrival"), to.get("scheduledArrival")),
                        platform=frm.get("track"),
                        cancelled=bool(leg.get("cancelled")),
                    )
                )
            journeys.append(Journey(legs))
        return journeys
