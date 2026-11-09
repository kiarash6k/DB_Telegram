"""Thin async client for the community DB API (transport.rest, hafas-client)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://v6.db.transport.rest"


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


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _delay_min(seconds: int | None) -> int:
    return round(seconds / 60) if seconds else 0


class DbApi:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            timeout=15,
            headers={"User-Agent": "DB_Telegram (github.com/kiarash6k/DB_Telegram)"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        try:
            resp = await self._client.get(path, params=params)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ApiError(str(exc)) from exc

    async def find_stations(self, query: str, limit: int = 5) -> list[Station]:
        data = await self._get(
            "/locations",
            {"query": query, "results": limit, "stops": "true", "addresses": "false", "poi": "false"},
        )
        return [Station(s["id"], s["name"]) for s in data if s.get("type") in ("stop", "station") and s.get("id")]

    async def departures(self, station_id: str, results: int = 8, duration: int = 90) -> list[Departure]:
        data = await self._get(f"/stops/{station_id}/departures", {"results": results, "duration": duration})
        return [
            Departure(
                line=(d.get("line") or {}).get("name", "?"),
                direction=d.get("direction") or "?",
                planned=_dt(d.get("plannedWhen")),
                when=_dt(d.get("when")),
                delay_min=_delay_min(d.get("delay")),
                platform=d.get("platform"),
                planned_platform=d.get("plannedPlatform"),
                cancelled=bool(d.get("cancelled")),
            )
            for d in data.get("departures", [])
        ]

    async def journeys(self, from_id: str, to_id: str, results: int = 3) -> list[Journey]:
        data = await self._get("/journeys", {"from": from_id, "to": to_id, "results": results})
        journeys = []
        for j in data.get("journeys", []):
            legs = [
                Leg(
                    line="walk" if leg.get("walking") else (leg.get("line") or {}).get("name", "?"),
                    origin=(leg.get("origin") or {}).get("name", "?"),
                    destination=(leg.get("destination") or {}).get("name", "?"),
                    departure=_dt(leg.get("departure")),
                    arrival=_dt(leg.get("arrival")),
                    departure_delay_min=_delay_min(leg.get("departureDelay")),
                    arrival_delay_min=_delay_min(leg.get("arrivalDelay")),
                    platform=leg.get("departurePlatform"),
                    cancelled=bool(leg.get("cancelled")),
                )
                for leg in j.get("legs", [])
            ]
            journeys.append(Journey(legs))
        return journeys
