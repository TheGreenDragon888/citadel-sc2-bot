"""Opponent memory (DESIGN.md §5): ./data/opponents/<OpponentId>.json.

The record is §5's `{games, wins, losses, threats_seen: [{threat, time}], first_aggression_time}`;
each `threats_seen` entry also carries the game number and the detector source (Citadel, so "the
last 3 games" can be counted and weak sources left out):
- loaded in `on_start` from the ladder's `--OpponentId` (python-sc2's `opponent_id`, which the
  template's ladder.py sets) and written in `on_end`; with no opponent id (local games) there is no
  memory, and an id is reduced to letters, digits, `_`, `-` and `.` before it names a file;
- `threats_seen`: every threat raised in a game, once per (threat, source), with its first raise
  time; entries from the last MEMORY_KEEP_GAMES games are kept. Flags pre-raised from memory
  (source MEMORY_SOURCE) are never recorded, or a pre-raise would keep itself going;
- `first_aggression_time`: the earliest §8 first-aggression time over all games;
- pre-raise (§5): a cheese threat (MEMORY_CHEESE, user decision) raised in at least
  MEMORY_MIN_GAMES of the last MEMORY_LAST_GAMES games, not counting MEMORY_IGNORED_SOURCES.
A missing or unreadable file starts a fresh record (logged); it never stops the game.
"""

import json
import re
from typing import Any, Iterable, Optional

from loguru import logger

from bot.constants import (
    MEMORY_CHEESE,
    MEMORY_IGNORED_SOURCES,
    MEMORY_KEEP_GAMES,
    MEMORY_LAST_GAMES,
    MEMORY_MIN_GAMES,
    MEMORY_SOURCE,
    OPPONENTS_SUBDIR,
)
from bot.data_files import data_path, read_text, write_text

UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")
MAX_NAME = 100


def file_name(opponent_id: Optional[str]) -> Optional[str]:
    """`<id>.json` with anything but letters, digits, `_`, `-`, `.` replaced; None without an id."""
    if opponent_id is None:
        return None
    name = UNSAFE.sub("_", str(opponent_id)).strip("._")[:MAX_NAME]
    return f"{name}.json" if name else None


def empty_record() -> dict[str, Any]:
    return {"games": 0, "wins": 0, "losses": 0, "threats_seen": [], "first_aggression_time": None}


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def clean(raw: Any) -> dict[str, Any]:
    """A record read from disk, checked field by field; ValueError if it isn't one."""
    if not isinstance(raw, dict):
        raise ValueError("not a JSON object")
    record = empty_record()
    for key in ("games", "wins", "losses"):
        value = raw.get(key, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{key} is not a count: {value!r}")
        record[key] = value
    threats = raw.get("threats_seen", [])
    if not isinstance(threats, list):
        raise ValueError("threats_seen is not a list")
    for entry in threats:
        if not (
            isinstance(entry, dict) and isinstance(entry.get("threat"), str) and _number(entry.get("time"))
            and isinstance(entry.get("game", 0), int)
        ):
            raise ValueError(f"bad threats_seen entry: {entry!r}")
        record["threats_seen"].append(
            {"threat": entry["threat"], "time": entry["time"], "game": entry.get("game", 0), "source": str(entry.get("source", ""))}
        )
    first = raw.get("first_aggression_time")
    if first is not None and not _number(first):
        raise ValueError(f"first_aggression_time is not a time: {first!r}")
    record["first_aggression_time"] = first
    return record


def recurring_cheese(record: dict[str, Any]) -> dict[str, int]:
    """Cheese threats raised in >= MEMORY_MIN_GAMES of the last MEMORY_LAST_GAMES games: name -> games."""
    games = record["games"]
    last = set(range(games - MEMORY_LAST_GAMES + 1, games + 1))
    ignored = set(MEMORY_IGNORED_SOURCES)
    seen: dict[str, set[int]] = {}
    for entry in record["threats_seen"]:
        threat, source, game = entry["threat"], entry.get("source", ""), entry.get("game", 0)
        if threat in MEMORY_CHEESE and (threat, source) not in ignored and game in last:
            seen.setdefault(threat, set()).add(game)
    return {threat: len(g) for threat, g in sorted(seen.items()) if len(g) >= MEMORY_MIN_GAMES}


def add_game(
    record: dict[str, Any],
    result: str,
    raised: Iterable[tuple[str, str, float]],
    first_aggression: Optional[float],
) -> dict[str, Any]:
    """A copy of `record` with one more game. `raised`: (threat, source, game seconds) for every
    flag raised this game; `result`: "Victory", "Defeat", "Tie" (or anything else: counted as a game)."""
    out = {**record, "threats_seen": list(record["threats_seen"])}
    out["games"] += 1
    game = out["games"]
    if result == "Victory":
        out["wins"] += 1
    elif result == "Defeat":
        out["losses"] += 1
    first: dict[tuple[str, str], float] = {}
    for threat, source, t in raised:
        if source == MEMORY_SOURCE:
            continue
        key = (threat, source)
        first[key] = min(first.get(key, t), t)
    for (threat, source), t in sorted(first.items(), key=lambda kv: kv[1]):
        out["threats_seen"].append({"threat": threat, "time": round(t, 1), "game": game, "source": source})
    out["threats_seen"] = [e for e in out["threats_seen"] if e["game"] > game - MEMORY_KEEP_GAMES]
    if first_aggression is not None:
        old = out.get("first_aggression_time")
        out["first_aggression_time"] = round(first_aggression if old is None else min(old, first_aggression), 1)
    return out


class OpponentStore:
    def __init__(self, opponent_id: Optional[str]):
        self.opponent_id = opponent_id
        name = file_name(opponent_id)
        self.path = data_path(OPPONENTS_SUBDIR, name) if name is not None else None
        self.record: dict[str, Any] = empty_record()
        self.loaded: bool = False
        self.saved: bool = False

    def load(self) -> None:
        if self.path is None:
            logger.info("MEMORY off: no opponent id (local game)")
            return
        text = read_text(self.path)
        if text is None:
            logger.info(f"MEMORY new opponent {self.opponent_id}: {self.path.name} not found")
            return
        try:
            self.record = clean(json.loads(text))
            self.loaded = True
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning(f"MEMORY {self.path.name} unreadable ({e}); starting a fresh record")
            return
        r = self.record
        logger.info(
            f"MEMORY {self.opponent_id}: {r['games']} games ({r['wins']} won, {r['losses']} lost), "
            f"first aggression {r['first_aggression_time']}, recurring cheese {recurring_cheese(r) or 'none'}"
        )

    def preraise(self) -> dict[str, int]:
        return recurring_cheese(self.record) if self.loaded else {}

    def save(self, result: str, raised: Iterable[tuple[str, str, float]], first_aggression: Optional[float]) -> bool:
        if self.path is None:
            return False
        record = add_game(self.record, result, raised, first_aggression)
        write_text(self.path, json.dumps(record, separators=(",", ":")))
        self.record = record
        self.saved = True
        logger.info(f"MEMORY saved {self.path.name}: game {record['games']} ({result}), {len(record['threats_seen'])} threat entries")
        return True
