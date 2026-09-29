"""Pylon timing after the opener (DESIGN.md §3 `macro/supply.py`).

During the opener the ares build runner builds Pylons itself (`AutoSupplyAtSupply` in
protoss_builds.yml). Afterwards ares's `AutoSupply` does the same job: it asks for more Pylons
as production structures are added. In a `MacroPlan` it returns True whenever supply is
needed, even when the Pylon can't be afforded yet, so the behaviors after it wait and the
minerals are kept for the Pylon.
"""

from typing import TYPE_CHECKING

from ares.behaviors.macro import AutoSupply

if TYPE_CHECKING:
    from ares import AresBot


def supply_behavior(bot: "AresBot") -> AutoSupply:
    """Pylons go in the main, where they also power later production."""
    return AutoSupply(base_location=bot.start_location)
