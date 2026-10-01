"""Offline tests for §5 opponent memory (bot/memory/opponent_store.py), the ./data file rules
(bot/data_files.py) and the §8 game log's bounds (`Telemetry.write_game_record`: the last 200
games, oldest dropped first to keep ./data under its byte budget); no game needed. Files go to a
temporary folder, not ./data.

    poetry run python scripts/test_opponent_memory.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT: Path = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import run  # noqa: E402,F401  (puts ares-sc2 on sys.path)

import bot.data_files as data_files  # noqa: E402
import bot.telemetry.logger as logger_module  # noqa: E402
from bot.constants import GAME_LOG_KEEP, MEMORY_KEEP_GAMES, MEMORY_SOURCE  # noqa: E402
from bot.memory.opponent_store import (  # noqa: E402
    OpponentStore,
    add_game,
    clean,
    empty_record,
    file_name,
    recurring_cheese,
)

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def raises(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


def games(*per_game: list[tuple[str, str, float]], results: tuple[str, ...] = ()) -> dict:
    record = empty_record()
    for i, raised in enumerate(per_game):
        record = add_game(record, results[i] if i < len(results) else "Victory", raised, None)
    return record


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="citadel-memory-"))
    data_files.DATA_DIR = str(tmp / "data")

    # -- file names and the ./data boundary -------------------------------------------------------
    check("file name: a normal id", file_name("4f2a-91c0_b") == "4f2a-91c0_b.json")
    check("file name: no id -> no memory", file_name(None) is None and file_name("") is None and file_name("  ") is None)
    check("file name: path parts can't escape", file_name("../../etc/passwd") == "etc_passwd.json", file_name("../../etc/passwd") or "")
    check("data_path refuses to leave ./data", raises(lambda: data_files.data_path("..", "x.json")))
    check("write_text refuses a path outside ./data", raises(lambda: data_files.write_text(tmp / "outside.json", "{}")))
    target = data_files.data_path("opponents", "x.json")
    data_files.write_text(target, "{}")
    check("write_text writes inside ./data, no temporary file left",
          target.read_text() == "{}" and not target.with_name("x.json.tmp").exists())

    # -- add_game ---------------------------------------------------------------------------------
    r = add_game(empty_record(), "Victory", [("POOL_12", "early_pool", 70.0), ("POOL_12", "early_pool", 90.0),
                                             ("POOL_12", "ares:ling", 80.0), ("PROXY", MEMORY_SOURCE, 0.0)], 95.0)
    check("add_game: counts the game and the win", (r["games"], r["wins"], r["losses"]) == (1, 1, 0))
    check("add_game: one entry per (threat, source), first raise time",
          [(e["threat"], e["source"], e["time"]) for e in r["threats_seen"]] == [("POOL_12", "early_pool", 70.0), ("POOL_12", "ares:ling", 80.0)],
          f"{r['threats_seen']}")
    check("add_game: flags pre-raised from memory are not recorded", all(e["source"] != MEMORY_SOURCE for e in r["threats_seen"]))
    r2 = add_game(r, "Defeat", [], 60.0)
    r3 = add_game(r2, "Tie", [], 120.0)
    check("add_game: losses and ties", (r3["games"], r3["wins"], r3["losses"]) == (3, 1, 1))
    check("add_game: first_aggression_time is the earliest", r3["first_aggression_time"] == 60.0)
    check("add_game: the input record is not changed", r["games"] == 1 and len(r["threats_seen"]) == 2)
    long = empty_record()
    for i in range(MEMORY_KEEP_GAMES + 5):
        long = add_game(long, "Victory", [("WORKER_RUSH", "worker_rush", 30.0), ("MACRO", "ares", 200.0)], None)
    kept = {e["game"] for e in long["threats_seen"]}
    check(f"add_game: keeps only the last {MEMORY_KEEP_GAMES} games' threats",
          min(kept) == 6 and max(kept) == MEMORY_KEEP_GAMES + 5 and len(json.dumps(long)) < 10_000,
          f"games {min(kept)}-{max(kept)}, {len(json.dumps(long))} bytes")

    # -- recurring_cheese (§5: same cheese flag in >= 2 of the last 3 games) -----------------------
    wr = ("WORKER_RUSH", "worker_rush", 35.0)
    check("pre-raise: 2 of the last 3 games", recurring_cheese(games([wr], [], [wr])) == {"WORKER_RUSH": 2})
    check("pre-raise: 1 of the last 3 games -> no", recurring_cheese(games([wr], [], [])) == {})
    check("pre-raise: 2 games but one older than the last 3 -> no", recurring_cheese(games([wr], [], [], [wr])) == {})
    check("pre-raise: two sources in one game count once", recurring_cheese(games([wr, ("WORKER_RUSH", "ares:w", 40.0)], [], [])) == {})
    ff = ("CANNON_RUSH", "forge_first", 80.0)
    probe = ("CANNON_RUSH", "cannon_probe", 70.0)
    cs = ("CANNON_RUSH", "cannon_structures", 50.0)
    check("pre-raise: Forge-first and probe-only CANNON_RUSH don't count", recurring_cheese(games([ff], [probe], [ff])) == {})
    check("pre-raise: Cannon structures count", recurring_cheese(games([cs], [ff], [cs])) == {"CANNON_RUSH": 2})
    ob = ("ONE_BASE_ALLIN", "no_natural", 170.0)
    check("pre-raise: ONE_BASE_ALLIN counts (user decision)", recurring_cheese(games([ob], [ob], [])) == {"ONE_BASE_ALLIN": 2})
    air = ("AIR_HARASS", "tech", 180.0)
    check("pre-raise: non-cheese threats don't", recurring_cheese(games([air], [air], [air])) == {})
    mem = ("PROXY", MEMORY_SOURCE, 0.0)
    check("pre-raise: a pre-raised flag doesn't keep itself going", recurring_cheese(games([mem], [mem], [mem])) == {})

    # -- clean (reading a file back) --------------------------------------------------------------
    check("clean: a saved record reads back unchanged", clean(json.loads(json.dumps(r3))) == r3)
    check("clean: not an object", raises(lambda: clean([1, 2])))
    check("clean: a negative count", raises(lambda: clean({**r3, "games": -1})))
    check("clean: a bad threats_seen entry", raises(lambda: clean({**r3, "threats_seen": [{"threat": 3}]})))
    check("clean: spec-only entries ({threat, time}) are accepted",
          clean({"games": 1, "wins": 1, "losses": 0, "threats_seen": [{"threat": "PROXY", "time": 50}],
                 "first_aggression_time": None})["threats_seen"][0]["game"] == 0)

    # -- OpponentStore end to end -----------------------------------------------------------------
    store = OpponentStore("opponent-1")
    store.load()
    check("store: a new opponent starts empty with no pre-raise", store.record == empty_record() and store.preraise() == {})
    for result, raised in (("Victory", [wr]), ("Defeat", []), ("Victory", [wr])):
        s = OpponentStore("opponent-1")
        s.load()
        s.save(result, raised, 40.0)
    s = OpponentStore("opponent-1")
    s.load()
    on_disk = json.loads(s.path.read_text())
    check("store: three games saved and loaded", s.loaded and on_disk["games"] == 3 and on_disk["wins"] == 2, f"{on_disk}")
    check("store: WORKER_RUSH in games 1 and 3 is pre-raised in game 4", s.preraise() == {"WORKER_RUSH": 2})
    check("store: the file has §5's keys",
          {"games", "wins", "losses", "threats_seen", "first_aggression_time"} <= set(on_disk))
    s.path.write_text("{not json")
    bad = OpponentStore("opponent-1")
    bad.load()
    check("store: an unreadable file starts a fresh record", not bad.loaded and bad.record == empty_record() and bad.preraise() == {})
    bad.save("Victory", [], None)
    check("store: and the next save replaces it", json.loads(bad.path.read_text())["games"] == 1)
    none = OpponentStore(None)
    none.load()
    check("store: no opponent id -> nothing written", none.path is None and none.save("Victory", [wr], 30.0) is False)
    check("store: only ./data/opponents was written",
          sorted(p.name for p in (tmp / "data" / "opponents").iterdir()) == ["opponent-1.json", "x.json"],
          ", ".join(sorted(str(p.relative_to(tmp)) for p in tmp.rglob("*") if p.is_file())))

    # -- the §8 game log's bounds -----------------------------------------------------------------
    telemetry = logger_module.Telemetry.__new__(logger_module.Telemetry)  # no game: only the writer is used
    log_path = data_files.data_path("logs", "games.jsonl")
    for i in range(GAME_LOG_KEEP + 5):
        telemetry.write_game_record({"game_id": f"g{i}", "pad": "x" * 100})
    lines = log_path.read_text().splitlines()
    check(f"game log: keeps the last {GAME_LOG_KEEP} games",
          len(lines) == GAME_LOG_KEEP and json.loads(lines[0])["game_id"] == "g5" and json.loads(lines[-1])["game_id"] == f"g{GAME_LOG_KEEP + 4}",
          f"{len(lines)} lines, first {json.loads(lines[0])['game_id']}")
    others = data_files.data_size(exclude=log_path)
    logger_module.DATA_MAX_BYTES = others + 20 * 130  # room for about 20 lines
    telemetry.write_game_record({"game_id": "budget", "pad": "x" * 100})
    lines = log_path.read_text().splitlines()
    check("game log: drops its oldest lines to stay inside the ./data budget",
          len(lines) < 25 and json.loads(lines[-1])["game_id"] == "budget" and data_files.data_size() <= logger_module.DATA_MAX_BYTES,
          f"{len(lines)} lines, ./data {data_files.data_size()} of {logger_module.DATA_MAX_BYTES} bytes")
    logger_module.DATA_MAX_BYTES = others  # no room at all
    wrote = telemetry.write_game_record({"game_id": "none", "pad": "x" * 100})
    check("game log: not written when ./data has no room left", wrote is False and "none" not in log_path.read_text())

    passed = sum(ok for _, ok, _ in RESULTS)
    print(f"\n{passed}/{len(RESULTS)} passed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
