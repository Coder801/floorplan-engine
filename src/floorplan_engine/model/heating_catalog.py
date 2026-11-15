"""Floor heating cable catalogue: series of two-core heating cable sections (decision 2026-11-14,
second step of the "Floor heating" section).

A section is sold by its heating length; its power is the linear power × that length. The cold
(supply) lead to the controller is attached at the factory and is not part of the heating
length. A two-core section is connected at one end only: the far end is an end sleeve, so the
cable may finish anywhere in the zone.

The only series now is `generic`: a typical row of lengths and 18 W/m, an ASSUMPTION — not the
data of any manufacturer. A real series is added here only with the manufacturer's catalogue
(lengths, linear power, cold lead, cable diameter) and its source; prices are never here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HeatingSeries:
    id: str  # «generic»
    title: dict[str, str]  # by language: what the estimate and the sheet call it
    watts_per_m: float  # linear power, W/m
    lengths: tuple[float, ...]  # heating section lengths on sale, m, ascending
    diameter_mm: float  # cable outer diameter: the bend radius is MIN_BEND_DIAMETERS of it
    assumed: bool  # True: not the data of a manufacturer, the sheet says "assumption"
    source: str = ""  # where the data comes from (catalogue, page, date)


GENERIC = HeatingSeries(
    id="generic",
    title={
        "ru": "Кабель нагревательный двужильный 18 Вт/м",
        "uk": "Кабель нагрівальний двожильний 18 Вт/м",
    },
    watts_per_m=18.0,
    # A row like the ones on sale; to be checked against the catalogue of the chosen maker
    lengths=(10, 15, 20, 27, 34, 41, 49, 56, 64, 71, 82, 92, 105, 120),
    diameter_mm=6.5,
    assumed=True,
)

SERIES: dict[str, HeatingSeries] = {s.id: s for s in (GENERIC,)}
DEFAULT_SERIES = GENERIC.id
