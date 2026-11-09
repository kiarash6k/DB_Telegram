"""Turn API objects into Telegram-friendly (HTML) text."""
from __future__ import annotations

from datetime import datetime
from html import escape

from .api import Departure, Journey


def _t(value: datetime | None) -> str:
    return value.strftime("%H:%M") if value else "--:--"


def _delay(minutes: int) -> str:
    return f" (+{minutes})" if minutes > 0 else ""


def format_departures(station: str, deps: list[Departure]) -> str:
    if not deps:
        return f"No departures found for <b>{escape(station)}</b>."
    lines = [f"🚉 <b>{escape(station)}</b>"]
    for d in deps:
        if d.cancelled:
            lines.append(f"❌ <s>{_t(d.planned)} {escape(d.line)} → {escape(d.direction)}</s> cancelled")
            continue
        plat = ""
        if d.platform:
            changed = d.planned_platform and d.planned_platform != d.platform
            plat = f" · Pl. {escape(d.platform)}" + (" ⚠️" if changed else "")
        lines.append(
            f"{_t(d.planned)}{_delay(d.delay_min)} <b>{escape(d.line)}</b> → {escape(d.direction)}{plat}"
        )
    return "\n".join(lines)


def format_journeys(origin: str, destination: str, journeys: list[Journey]) -> str:
    if not journeys:
        return f"No connections found from {escape(origin)} to {escape(destination)}."
    out = [f"🧭 <b>{escape(origin)} → {escape(destination)}</b>"]
    for i, j in enumerate(journeys, 1):
        if not j.legs:
            continue
        transit = [leg for leg in j.legs if leg.line != "walk"]
        first, last = j.legs[0], j.legs[-1]
        changes = max(len(transit) - 1, 0)
        out.append(
            f"\n<b>{i}.</b> {_t(first.departure)}{_delay(first.departure_delay_min)}"
            f" → {_t(last.arrival)}{_delay(last.arrival_delay_min)} · {changes} change(s)"
        )
        for leg in transit:
            plat = f" Pl. {escape(leg.platform)}" if leg.platform else ""
            flag = " ❌ cancelled" if leg.cancelled else ""
            out.append(
                f"   {_t(leg.departure)}{_delay(leg.departure_delay_min)} <b>{escape(leg.line)}</b> "
                f"{escape(leg.origin)}{plat} → {escape(leg.destination)}{flag}"
            )
    return "\n".join(out)
