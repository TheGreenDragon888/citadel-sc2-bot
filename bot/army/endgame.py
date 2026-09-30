"""End-game rules and the 60-minute tie (DESIGN.md §4.7).

Games reaching 60:00 are ties. From END_GAME_FROM_S (40:00), if no enemy structure has been in
vision for END_GAME_HUNT_UNSEEN_S, Citadel runs a structure hunt:
- Observers (and a hallucinated Phoenix, from a Sentry that exists) visit every expansion, then
  the map-analyzer region centres (islands included), the playable area's corners and a grid over
  the map (bot/intel/scout_planner.py gives the trips);
- the army's own hunt (bot/army/army.py, when no enemy structure is known) walks the ground points,
  and lifted Terran buildings become targets for the units that can shoot up.
The other §4.7 rules are in bot/army/attack_decision.py: from 45:00 ATTACK_START drops to 6 while
our army value is >= 1.2x the enemy's, and from 40:00 no attack launches while we are behind.
"""

from typing import TYPE_CHECKING

from loguru import logger
from sc2.position import Point2

from bot.constants import (
    END_GAME_CORNER_INSET,
    END_GAME_FROM_S,
    END_GAME_HUNT_UNSEEN_S,
    HUNT_GRID_STEP,
    HUNT_VISIT_RADIUS,
)

if TYPE_CHECKING:
    from ares import AresBot


class EndGame:
    def __init__(self, bot: "AresBot"):
        self.bot = bot
        self.last_structure_seen: float = 0.0
        self.hunting: bool = False
        self.hunt_started_at: list[float] = []
        self._points: list[Point2] = []
        self.visited: set[Point2] = set()

    def update(self) -> None:
        bot = self.bot
        now = bot.time
        if any(s.is_visible for s in bot.enemy_structures):
            self.last_structure_seen = now
        hunting = now >= END_GAME_FROM_S and now - self.last_structure_seen >= END_GAME_HUNT_UNSEEN_S
        if hunting != self.hunting:
            self.hunting = hunting
            if hunting:
                self.hunt_started_at.append(now)
            logger.info(
                f"ENDGAME {bot.time_formatted}: structure hunt {'on' if hunting else 'off'} "
                f"(enemy structure last seen at {int(self.last_structure_seen) // 60}:{int(self.last_structure_seen) % 60:02d})"
            )
        if hunting:
            for p in self.points():
                if p not in self.visited and bot.is_visible(p):
                    self.visited.add(p)
            if len(self.visited) >= len(self._points):
                self.visited.clear()  # every point seen: sweep again

    def points(self) -> list[Point2]:
        """Every expansion, the region centres, the corners, then a grid (any may be air-only)."""
        if self._points:
            return self._points
        bot = self.bot
        area = bot.game_info.playable_area
        points: list[Point2] = list(bot.expansion_locations_list)
        points += [Point2(r.center) for r in bot.mediator.get_map_data_object.regions.values()]
        inset = END_GAME_CORNER_INSET
        points += [
            Point2((area.x + inset, area.y + inset)), Point2((area.right - inset, area.y + inset)),
            Point2((area.x + inset, area.top - inset)), Point2((area.right - inset, area.top - inset)),
        ]
        x = area.x + HUNT_GRID_STEP / 2
        while x < area.right:
            y = area.y + HUNT_GRID_STEP / 2
            while y < area.top:
                points.append(Point2((x, y)))
                y += HUNT_GRID_STEP
            x += HUNT_GRID_STEP
        unique: list[Point2] = []
        for p in points:
            if all(p.distance_to(q) > HUNT_VISIT_RADIUS for q in unique):
                unique.append(p)
        self._points = unique
        return unique

    def unvisited(self) -> list[Point2]:
        return [p for p in self.points() if p not in self.visited]
