"""Squad roles (DESIGN.md §3 `army/squads.py`): which army unit belongs to which squad.

Every army unit (not a worker, not a structure, not a hallucination) is in exactly one role,
stored by tag (never `Unit` objects across steps):
- DEFEND: at home. New units start here; after a retreat the ATTACK squad comes back here.
- ATTACK: the main attack squad (§4.5.2).
- REINFORCE: a group of at least REINFORCE_MIN_SUPPLY walking out to join the ATTACK squad.
- HARASS: the §4.6 counterattack squad (M5; nothing is assigned to it in M4).
- SCOUT: units the scout planner has a task for (bot/intel/scout_planner.py controls them).
Units held by other modules (the wall-gap holder, pinned units) are in no squad while held.

Each role is mirrored as an ares `UnitRole` so ares's squad manager can split the ATTACK squad into
spatial groups (`mediator.get_squads`), which the army uses to pull in stragglers.
"""

from enum import Enum
from typing import TYPE_CHECKING, Iterable

from ares.consts import UnitRole
from sc2.unit import Unit

if TYPE_CHECKING:
    from ares import AresBot


class Role(Enum):
    DEFEND = "defend"
    ATTACK = "attack"
    REINFORCE = "reinforce"
    HARASS = "harass"
    SCOUT = "scout"


ARES_ROLE: dict[Role, UnitRole] = {
    Role.DEFEND: UnitRole.BASE_DEFENDER,
    Role.ATTACK: UnitRole.ATTACKING,
    Role.REINFORCE: UnitRole.CONTROL_GROUP_ONE,
    Role.HARASS: UnitRole.HARASSING,
    Role.SCOUT: UnitRole.SCOUTING,
}


class Squads:
    def __init__(self, bot: "AresBot"):
        self.bot = bot
        self.roles: dict[int, Role] = {}

    def update(self, army: Iterable[Unit], scout_tags: set[int], held_tags: set[int]) -> None:
        """Refresh roles from this step's army units: dead units drop out, scouts are SCOUT,
        held units leave their squad, and new units (or scouts back from a task) join DEFEND."""
        current: dict[int, Role] = {}
        for unit in army:
            tag = unit.tag
            if tag in held_tags:
                continue
            if tag in scout_tags:
                role = Role.SCOUT
            else:
                role = self.roles.get(tag, Role.DEFEND)
                if role == Role.SCOUT:
                    role = Role.DEFEND
            current[tag] = role
            if self.roles.get(tag) != role:
                self.bot.mediator.assign_role(tag=tag, role=ARES_ROLE[role])
        self.roles = current

    def assign(self, tags: Iterable[int], role: Role) -> None:
        for tag in tags:
            if tag in self.roles and self.roles[tag] != role:
                self.roles[tag] = role
                self.bot.mediator.assign_role(tag=tag, role=ARES_ROLE[role])

    def tags(self, role: Role) -> set[int]:
        return {tag for tag, r in self.roles.items() if r == role}

    def units(self, role: Role) -> list[Unit]:
        get = self.bot.unit_tag_dict.get
        return [u for tag, r in self.roles.items() if r == role and (u := get(tag)) is not None]

    def forget(self, tag: int) -> None:
        self.roles.pop(tag, None)
