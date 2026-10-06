"""Check ./data/logs/games.jsonl (DESIGN.md §8 telemetry, M5) and the size of ./data (§2).

    poetry run python scripts/check_game_log.py [--last N] [--show]

Every line must be one JSON object with each §8 metric:
- result, opponent id/race, map, game length, opener, ruleset, tie flag;
- flags with their raise and expire reasons and times;
- probes at 4:00/6:00/8:00, bases at 6:00/10:00, supply-block seconds, unspent resources at 6:00/10:00;
- first enemy aggression time; army value lost vs killed;
- EngagementResult values at each attack/retreat decision; counterattack outcomes;
- startup ms; mean/p99/max step ms.
A value may be null where the game didn't reach it (no 10:00 snapshot in a 9-minute game).
Prints one summary row per game (the last N with --last), the file's line count and size, and
the size of ./data against the 5 MB limit. Exit 1 if a line is malformed or ./data is too big.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT: Path = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from bot.constants import DATA_DIR, DATA_MAX_BYTES, GAME_LOG_FILE, GAME_LOG_KEEP, LOGS_SUBDIR  # noqa: E402

# key -> type(s) of its value (None allowed where listed)
TOP: dict[str, tuple] = {
    "game_id": (str,), "result": (str,), "opponent_id": (str, type(None)), "opponent_race": (str,),
    "map": (str,), "game_length_s": (int, float), "tie": (bool,), "opener": (str,), "ruleset": (str, type(None)),
    "flags": (list,), "probes": (dict,), "bases": (dict,), "supply_blocked_s": (int, float), "unspent": (dict,),
    "first_aggression": (dict, type(None)), "army_value": (dict,), "engage": (list,), "counterattacks": (list,),
    "startup_ms": (int, float, type(None)), "step_ms": (dict,), "preraised": (list,),
}
# added in a later record version: key -> (first version with it, type(s))
SINCE: dict[str, tuple[int, tuple]] = {
    "errors": (2, (dict,)), "errors_first": (2, (dict,)),
    "tech_seen": (3, (list,)), "lost_by_intent": (3, (dict,)), "lost_far": (3, (dict,)),  # M7
}
# entries' keys added in a later record version: list name -> (first version, keys) (M7: version 3)
ENTRY_SINCE: dict[str, tuple[int, tuple[str, ...]]] = {"engage": (3, ("own_value", "enemy_value"))}
NESTED: dict[str, tuple[str, ...]] = {
    "probes": ("4:00", "6:00", "8:00"),
    "bases": ("6:00", "10:00"),
    "unspent": ("6:00", "10:00"),
    "army_value": ("lost", "killed"),
    "step_ms": ("mean", "p99", "max"),
}
FLAG_KEYS = ("threat", "raised", "reason", "expired", "expire_reason")
ENGAGE_KEYS = ("t", "action", "level", "reason")
COUNTER_KEYS = ("launched", "target", "units", "supply", "level", "ended", "reason", "workers_killed")


def problems(record: Any) -> list[str]:
    if not isinstance(record, dict):
        return ["not a JSON object"]
    out = []
    for key, types in TOP.items():
        if key not in record:
            out.append(f"missing {key}")
        elif not isinstance(record[key], types):
            out.append(f"{key} is {type(record[key]).__name__}")
    for key, (version, types) in SINCE.items():
        if record.get("version", 1) < version:
            continue
        if key not in record:
            out.append(f"missing {key}")
        elif not isinstance(record[key], types):
            out.append(f"{key} is {type(record[key]).__name__}")
    for key, subkeys in NESTED.items():
        value = record.get(key)
        if isinstance(value, dict):
            out += [f"missing {key}.{k}" for k in subkeys if k not in value]
    for name, keys in (("flags", FLAG_KEYS), ("engage", ENGAGE_KEYS), ("counterattacks", COUNTER_KEYS)):
        if name in ENTRY_SINCE and record.get("version", 1) >= ENTRY_SINCE[name][0]:
            keys = keys + ENTRY_SINCE[name][1]
        for i, entry in enumerate(record.get(name) or []):
            missing = [k for k in keys if not isinstance(entry, dict) or k not in entry]
            if missing:
                out.append(f"{name}[{i}] missing {','.join(missing)}")
    return out


def size_of(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) if folder.exists() else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--last", type=int, default=None, help="show only the last N games")
    parser.add_argument("--show", action="store_true", help="print the last game's record in full")
    args = parser.parse_args()
    path = ROOT / DATA_DIR / LOGS_SUBDIR / GAME_LOG_FILE
    if not path.exists():
        print(f"{path} not found")
        return 1
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    bad = 0
    records = []
    for n, line in enumerate(lines, start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"line {n}: not JSON ({e})")
            bad += 1
            continue
        issues = problems(record)
        if issues:
            print(f"line {n}: {'; '.join(issues)}")
            bad += 1
        records.append(record)
    shown = records[-args.last:] if args.last else records
    for r in shown:
        if not isinstance(r, dict):
            continue
        counters = r.get("counterattacks") or []
        actions = [e.get("action") for e in r.get("engage") or []]
        step = r.get("step_ms") or {}
        print(
            f"{r.get('game_id', '?'):<24} {str(r.get('opponent_id')):<16} {r.get('opponent_race', '?'):<8} "
            f"{r.get('map', '?'):<16} {r.get('result', '?'):<8} {r.get('game_length_s', 0) / 60:5.1f} min  "
            f"flags={len(r.get('flags') or [])} pre={','.join(r.get('preraised') or []) or '-'} "
            f"engage={actions.count('launch')}/{actions.count('retreat')}/{actions.count('recall')} "
            f"counter={len(counters)}({','.join(c.get('reason', '')[:12] for c in counters)}) "
            f"probes6={(r.get('probes') or {}).get('6:00')} startup={r.get('startup_ms')} "
            f"step={step.get('mean')}/{step.get('p99')}/{step.get('max')} guard={step.get('guard_activations')} "
            f"errors={sum((r.get('errors') or {}).values())}"
        )
    if args.show and records:
        print(json.dumps(records[-1], indent=1))
    data_bytes = size_of(ROOT / DATA_DIR)
    print(
        f"{path.relative_to(ROOT)}: {len(lines)} games (keeps {GAME_LOG_KEEP}), {path.stat().st_size} bytes, "
        f"{bad} malformed; ./data total {data_bytes} bytes (limit {DATA_MAX_BYTES})"
    )
    ok = bad == 0 and data_bytes <= DATA_MAX_BYTES and len(lines) <= GAME_LOG_KEEP
    print(f"RESULT {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
