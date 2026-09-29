"""Small map helpers shared by the point searches in bot/ (Pylon fallback, main sampling,
Battery spots)."""

from typing import TYPE_CHECKING

from sc2.position import Point2

if TYPE_CHECKING:
    from sc2.bot_ai import BotAI


def in_map(bot: "BotAI", point: Point2) -> bool:
    """True if `point` rounds to a tile inside the map's grids. python-sc2's grid lookups
    (`get_terrain_z_height`, `in_pathing_grid`) index the arrays directly and raise IndexError
    past the edge (a Pylon search next to a map-edge base crashed a test game)."""
    grid = bot.game_info.terrain_height
    x, y = point.rounded
    return 0 <= x < grid.width and 0 <= y < grid.height
