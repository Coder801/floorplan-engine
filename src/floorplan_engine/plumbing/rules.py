"""Plumbing network rules: sizes, costs and norms shared by supply and sewer routing.

What each number means and where it comes from is in the comment beside it; the rules
themselves are in the network.py docstring and docs/plumbing.md.
"""

from __future__ import annotations

import re
from typing import Literal

from floorplan_engine.electrical.routing import (
    CLEARANCE,
    STEP,
)
from floorplan_engine.model.plumbing import (
    FixtureType,
    ObstacleType,
)

Kind = Literal["cold", "hot", "sewer"]
KINDS: tuple[Kind, ...] = ("cold", "hot", "sewer")

HOT_COLD_GAP = 150.0  # mm between the cold and hot water outlets
COLLECTOR_GAP = 200.0  # mm between the cold and hot manifolds in the unit
SUPPLY_D = 16  # Ø of a manifold branch and an end branch, mm (multilayer / PEX 16)
MAIN_D = 20  # Ø of the main, inlet and boiler feed, mm
# Sewer slope (routing spec 2026-11-02): 2–3 cm per metre, one over the whole fixture route,
# from a list (sewer_heights): 0.025 by default; 0.02 if the route fails at 0.025, Ø110
# only (Ø50 not below 0.025 per DBN V.2.5-64, like SNiP 2.04.01-85); 0.03 if the height
# allows it (a route with no branches off it: the main is no steeper than its branches)
SLOPE = {50: 0.025, 110: 0.025}
SLOPE_MIN = {50: 0.025, 110: 0.02}
SLOPE_MAX = 0.03
SCREED_MM = 90.0  # finished floor 90 mm above slab; sewer heights from slab
SCREED_COVER = 15.0  # mm above a pipe in the screed, at least
RISER_TEE_D = 110  # riser tee: inlet bottom is the inlet axis minus the Ø110 radius
# Hidden sewer zones are obstacles where the pipe is hidden: the highest pipe top from the
# finished floor (if the obstacle has no height, this one, as an assumption)
HIDDEN_HEIGHT = {
    ObstacleType.INSTALLATION: 1000.0,
    ObstacleType.BOX: 600.0,
    ObstacleType.BATH: 450.0,  # under the bath, behind the panel
    ObstacleType.SHOWER_TRAY: 100.0,  # under the tray
}
# Sewer grid cell cost is a step length multiplier (routing spec, change 2026-11-02): a hidden
# zone is cheapest, by a wall 1, farther out more expensive. Free grid cells are at least
# CLEARANCE (150 mm) from a wall, so "by the wall" is the first pipe axis band, up to WALL_BAND_MM
HIDDEN_COST = 0.7
WALL_COST = 1.0
NEAR_WALL_COST = 2.0
OPEN_ROOM_COST = 4.0  # ≥ 3: a diagonal is at most √2 times shorter than the path along walls
WALL_BAND_MM = CLEARANCE + STEP  # band by the wall: a box above the floor is allowed here
NEAR_WALL_MM = 400.0  # farther out: the middle of the room
# Sewer route variants (passes of route_sewer): costs of hidden, by the wall, near, middle
SEWER_VARIANTS: tuple[tuple[float, float, float, float], ...] = (
    (HIDDEN_COST, WALL_COST, NEAR_WALL_COST, OPEN_ROOM_COST),  # normal
    (0.2, WALL_COST * 3, NEAR_WALL_COST * 3, OPEN_ROOM_COST * 3),  # through hidden zones
    (HIDDEN_COST, WALL_COST, NEAR_WALL_COST * 5, OPEN_ROOM_COST * 10),  # only along walls
)
# Sewer grid cell kind (Grid.tag): hidden zone, by the wall, near, middle
TAG_HIDDEN, TAG_WALL, TAG_NEAR, TAG_OPEN = 0, 1, 2, 3
FALLBACK_COST = 1e6  # path without height pruning, only if the fixture is otherwise unreachable
# Hollow obstacles: pipes of their own fixture go inside (box, installation frame), others go around
HOLLOW = frozenset({ObstacleType.INSTALLATION, ObstacleType.BOX})
PARTITION_MAX = 150.0  # mm: thinner non-bearing walls are partitions
PARTITION_COST = 1000.0  # mm per cell at a partition: a pass ≈ a 4 m detour
UNDER_COST = 50.0  # mm per cell under a plasterboard wall inside a room: almost free
DOOR_COST = 20000.0  # mm per cell in a door opening: pipes through a door only as a last resort
HOLE_SHARE = 300.0  # mm: closer pipes share one hole
RISER_WALL = 400.0  # mm: riser in the wall to the room, at most
RISER_REACH = 800.0  # mm: how far from the riser to look for an approach on each side
WC_REACH = 1000.0  # mm along the pipe to the riser: a longer WC branch is an error
SEWER_BENDS = 6  # 45° plan bends on a sewer pipe; more than this needs a cleanout
DROP_TURN = 150.0  # mm: a drop at least this high takes two 90° turns (down, onto the floor);
# less takes an offset down with two 45° bends (a "duck")
# Pipe consumption ("tees" spec 2026-11-02): weight per metre by diameter and a 45° bend in mm
# of equivalent length; Ø50 tees come from merging fixture pairs by savings (merge_drains)
PIPE_WEIGHT = {50: 1.0, 110: 2.2}
TURN_COST_MM = 175.0  # 45° bend in mm of equivalent length: in the search and in tee savings
SEWER_BEND_COST = TURN_COST_MM
TEE_CANDIDATES = 20  # tee spots per pair: if the best is not allowed, the next by cost
REACH = CLEARANCE + 1.6 * STEP  # how far from the wall to look for the approach to a fixture
ALONG_COST = 3.0  # a metre along the wall counts as three on the floor: chasing costs more
PAIR_GAP = 80.0  # mm between hot and cold axes running as a pair to one fixture
# Shared line from the manifold (change 2026-11-02): neighbouring fixtures of one room on one
# wall no farther than SHARE_GAP share one pipe per water, with a Ø16 tee at the fixture: two
# basins (double vanity), a dishwasher off the sink's cold
SHARED_PAIRS = frozenset(
    {
        (FixtureType.SINK, FixtureType.SINK),
        (FixtureType.KITCHEN_SINK, FixtureType.DISHWASHER),
        (FixtureType.DISHWASHER, FixtureType.KITCHEN_SINK),
    }
)
SHARED_TYPES = frozenset(t for pair in SHARED_PAIRS for t in pair)
# Parallel lines (change 2026-11-02): a branch running alongside another (closer than PARALLEL_GAP)
# for at least PARALLEL_MIN is teed off it if that is shorter and the pipe can carry the flow
PARALLEL_GAP = 300.0  # mm between axes: running together, as one bundle
PARALLEL_MIN = 2000.0  # mm side by side already counts as "long"
BRANCH_SAVING = 1000.0  # mm: running together briefly; tee off only if it saves this much pipe
# Design flow of a water outlet, l/s, a guide: DBN V.2.5-64 / SNiP 2.04.01-85 (annex 3) for
# basin, sink, shower, bath, WC; washing machine and dishwasher from typical model datasheets
# (≈ 9 and 6 l/min)
FLOW: dict[FixtureType, float] = {
    FixtureType.SINK: 0.09,
    FixtureType.KITCHEN_SINK: 0.09,
    FixtureType.SHOWER: 0.09,
    FixtureType.HYGIENIC_SHOWER: 0.09,
    FixtureType.BATH: 0.18,
    FixtureType.WC: 0.10,
    FixtureType.WC_INSTALLATION: 0.10,
    FixtureType.WASHER: 0.15,
    FixtureType.DISHWASHER: 0.10,
    FixtureType.BOILER: 0.18,
}
# Pipe capacity, l/s, without a simultaneity factor (with a margin): Ø16 (12 mm inside) and
# Ø20 (16 mm inside) at about 1.75 m/s
CAPACITY: dict[int, float] = {16: 0.20, 20: 0.35}
SHARE_GAP = 1200.0  # mm between supply centres
COLLECTOR_HEIGHT = 400.0  # mm: manifold outlet axis from the floor (assumption)
COLLECTOR_HALF = 150.0  # mm: half a manifold with valves along the wall (wall space)
BOILER_NEAR = 1500.0  # mm: hot manifold in the unit if the boiler is closer
# Living rooms: sewer on the floor through them is a weak spot; rooms combined with a kitchen
# or hallway are not (they have their own sink)
LIVING_NAME = re.compile(
    r"спальн|кабінет|кабинет|вітальн|гостин|дитяч|детск|зал\b|кімнат|комнат", re.IGNORECASE
)
SERVICE_NAME = re.compile(r"кухн|коридор|передпок|прихож|хол\b", re.IGNORECASE)
FIXTURE_NAMES: dict[FixtureType, dict[str, str]] = {
    FixtureType.WC: {"ru": "Унитаз", "uk": "Унітаз"},
    FixtureType.WC_INSTALLATION: {"ru": "Унитаз на инсталляции", "uk": "Унітаз на інсталяції"},
    FixtureType.SINK: {"ru": "Умывальник", "uk": "Умивальник"},
    FixtureType.KITCHEN_SINK: {"ru": "Мойка", "uk": "Мийка"},
    FixtureType.BATH: {"ru": "Ванна", "uk": "Ванна"},
    FixtureType.SHOWER: {"ru": "Душ", "uk": "Душ"},
    FixtureType.WASHER: {"ru": "Стиральная машина", "uk": "Пральна машина"},
    FixtureType.DISHWASHER: {"ru": "Посудомоечная машина", "uk": "Посудомийна машина"},
    FixtureType.BOILER: {"ru": "Бойлер", "uk": "Бойлер"},
    FixtureType.HYGIENIC_SHOWER: {"ru": "Гигиенический душ", "uk": "Гігієнічний душ"},
}
