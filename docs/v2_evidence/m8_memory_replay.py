"""M8 check: replay Citadel's ladder history through the opponent-memory rule (offline).

    poetry run python docs/v2_evidence/m8_memory_replay.py <cache dir with rows.json and records.json>

For every opponent, the flags each game actually raised (from its METRIC game record) are fed, in
match order, to the real `add_game` / `recurring_cheese`. Prints how many games would start with a
pre-raised flag under the current rule, next to how many did on the ladder (`preraised` in the
record). The in-game flags are the old code's, so this measures the memory rule alone.
"""
import collections, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "ares-sc2" / "src", ROOT / "ares-sc2"):
    sys.path.insert(0, str(p))
from bot.memory.opponent_store import add_game, empty_record, recurring_cheese  # noqa: E402

cache = Path(sys.argv[1])
rows = {r["match"]: r for r in json.loads((cache / "rows.json").read_text())}
recs = {int(k): v for k, v in json.loads((cache / "records.json").read_text()).items()}
memory: dict[str, dict] = collections.defaultdict(empty_record)
was, now, real_proxy = collections.Counter(), collections.Counter(), 0
games = 0
for match in sorted(recs):
    rec, row = recs[match], rows[match]
    if rec.get("version") != 7 or row["result"] not in ("win", "loss"):
        # earlier uploads still fill the memory, as they did on the ladder
        memory[rec["opponent_id"]] = add_game(memory[rec["opponent_id"]], rec["result"], [(f["threat"], f["source"], f["raised"]) for f in rec.get("flags", [])], None)
        continue
    games += 1
    pre = recurring_cheese(memory[rec["opponent_id"]])
    for name in rec.get("preraised", []):
        was[name] += 1
    for name in pre:
        now[name] += 1
    if "PROXY" in pre:
        real_proxy += any(f["source"] == "proxy_structure" for f in rec.get("flags", []))
    memory[rec["opponent_id"]] = add_game(memory[rec["opponent_id"]], rec["result"], [(f["threat"], f["source"], f["raised"]) for f in rec.get("flags", [])], None)
print(f"games replayed (current zip, with a record): {games}")
print(f"{'threat':<16}{'pre-raised on the ladder':>26}{'under the M8 rule':>20}")
for name in sorted(set(was) | set(now)):
    print(f"{name:<16}{was[name]:>26}{now[name]:>20}")
print(f"PROXY pre-raises under the M8 rule in games where a proxy structure was then seen: {real_proxy} of {now['PROXY']}")
