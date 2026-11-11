import json, collections, statistics
from pathlib import Path
c = Path("cache")
matches = {m["id"]: m for m in json.loads((c/"matches.json").read_text())}
parts = sorted(json.loads((c/"participations.json").read_text()), key=lambda p: p["match"])
comps = json.loads((c/"competitions.json").read_text())
bots = {int(k): v for k, v in json.loads((c/"bots.json").read_text()).items()}
maps = {int(k): v for k, v in json.loads((c/"maps.json").read_text()).items()}
name2bot = {b["name"]: b for b in bots.values()}
elo38 = {p["bot"]: p for p in comps["38"]["participants"]}
active38 = sorted([p for p in comps["38"]["participants"] if p["active"]], key=lambda p: -p["elo"])
rank38 = {p["bot"]: i for i, p in enumerate(active38, 1)}
ME = 1358
print("Season 2: active bots", len(active38), "| my rank", rank38[ME], "elo", elo38[ME]["elo"], "| 10th elo", active38[9]["elo"], "| 1st", active38[0]["elo"], "| 5th", active38[4]["elo"], "| 20th", active38[19]["elo"])
divs = collections.Counter(p["division_num"] for p in active38)
print("division sizes:", dict(sorted(divs.items())))
for d in sorted(divs):
    ps = [p["elo"] for p in active38 if p["division_num"] == d]
    if ps: print(f"  div {d}: n={len(ps)} elo {min(ps)}..{max(ps)}")

rows = []
for p in parts:
    m = matches.get(p["match"])
    if not m or not m.get("result"): continue
    r = m["result"]
    opp_name = r["bot2_name"] if r["bot1_name"] == "Citadel" else r["bot1_name"]
    opp = name2bot.get(opp_name, {})
    rows.append({
        "match": p["match"], "created": m["created"], "started": m.get("started"), "map": maps.get(m["map"], m["map"]),
        "opp": opp_name, "opp_id": opp.get("id"), "race": opp.get("race", "?"), "result": p["result"], "cause": p["result_cause"],
        "type": r["type"], "steps": r.get("game_steps"), "elo0": p["starting_elo"], "elo1": p["resultant_elo"], "delta": p["elo_change"],
        "pnum": p["participant_number"], "avg_step": p.get("avg_step_time"),
    })
json.dump(rows, open("cache/rows.json", "w"))
print("\nfinished games:", len(rows))
print("result x cause:", collections.Counter((r["result"], r["cause"]) for r in rows).most_common())
print("result types:", collections.Counter(r["type"] for r in rows).most_common())

# uploads: known zip-update times from the docs (M6 2026-10-05?, M7 2026-10-16 16:01 UTC); split by date eras
def era(r):
    t = r["started"] or r["created"]
    if t < "2026-10-16T16:01:41": return "A: before M7 zip (to 10-16)"
    if t < "2026-10-26T07:02:51": return "B: M7 zip, Pre-Season 2"
    return "C: M7 zip, Season 2"
def rec(rs):
    played = [r for r in rs if r["result"] in ("win", "loss", "tie")]
    w = sum(r["result"] == "win" for r in played); l = sum(r["result"] == "loss" for r in played); t = len(played) - w - l
    return f"{w}-{l}-{t} ({100*w/max(1,len(played)):.0f}% of {len(played)})"
print("\nBy era:")
for e in sorted({era(r) for r in rows}):
    rs = [r for r in rows if era(r) == e]
    print(f"  {e}: {rec(rs)}  first {min(r['created'] for r in rs)[:10]} last {max(r['created'] for r in rs)[:10]} elo {rs[0]['elo0']} -> {rs[-1]['elo1']}")
m7 = [r for r in rows if not era(r).startswith("A")]
played = [r for r in m7 if r["result"] in ("win", "loss", "tie")]
print("\nM7 zip (all games since 2026-10-16):", rec(m7))
print("  by race:", {race: rec([r for r in played if r["race"] == race]) for race in "TZPR?"})
print("  by map:", {mp: rec([r for r in played if r["map"] == mp]) for mp in sorted({r['map'] for r in played})})
print("  loss causes:", collections.Counter(r["cause"] for r in played if r["result"] == "loss").most_common())
def mins(r): return (r["steps"] or 0) / 22.4 / 60
L = [mins(r) for r in played if r["result"] == "loss" and r["steps"]]; W = [mins(r) for r in played if r["result"] == "win" and r["steps"]]
def dist(x):
    x = sorted(x); q = lambda f: x[int(f*(len(x)-1))]
    return f"n={len(x)} min {x[0]:.1f} p25 {q(.25):.1f} median {q(.5):.1f} p75 {q(.75):.1f} max {x[-1]:.1f}"
print("  loss length (min):", dist(L)); print("  win length (min): ", dist(W))
buckets = [(0,4),(4,6),(6,8),(8,10),(10,13),(13,17),(17,25),(25,61)]
print("  length buckets (min): wins / losses")
for a,b in buckets:
    w = sum(a <= x < b for x in W); l = sum(a <= x < b for x in L)
    print(f"    {a:>2}-{b:<2}: {w:>3} / {l:>3}   loss share {100*l/max(1,w+l):.0f}%")
# by opponent strength (Season 2 Elo of the opponent)
print("\nM7 zip record by opponent's current Season-2 Elo band:")
bands = [(2000,3000),(1850,2000),(1790,1850),(1740,1790),(1700,1740),(1650,1700),(1600,1650),(1500,1600),(0,1500)]
for lo,hi in bands:
    rs = [r for r in played if r["opp_id"] in elo38 and lo <= elo38[r["opp_id"]]["elo"] < hi]
    opps = len({r["opp"] for r in rs})
    print(f"  elo {lo:>4}-{hi:<4}: {rec(rs)}  ({opps} opponents)")
rs = [r for r in played if r["opp_id"] not in elo38]
print("  not in Season 2:", rec(rs))
print("\nM7 zip vs current top-25 (rank, name, race, elo): record")
for p in active38[:25]:
    rs = [r for r in played if r["opp_id"] == p["bot"]]
    if rs: print(f"  #{rank38[p['bot']]:>2} {bots[p['bot']]['name']:<20} {bots[p['bot']]['race']} {p['elo']}: {rec(rs)}  lengths(min) {[round(mins(r),1) for r in rs][:12]}")
# worst matchups (>=4 games)
print("\nM7 zip: opponents with >= 4 games, sorted by win rate (worst 25):")
byopp = collections.defaultdict(list)
for r in played: byopp[r["opp"]].append(r)
tbl = []
for o, rs in byopp.items():
    if len(rs) >= 4:
        w = sum(r["result"] == "win" for r in rs)
        oid = rs[0]["opp_id"]; e = elo38.get(oid, {}).get("elo"); rk = rank38.get(oid)
        tbl.append((w/len(rs), o, rs[0]["race"], e, rk, len(rs), w, statistics.median(mins(r) for r in rs if r["result"]=="loss") if any(r["result"]=="loss" for r in rs) else None))
for wr, o, race, e, rk, n, w, ml in sorted(tbl)[:25]:
    print(f"  {o:<24} {race} elo {e} rank {rk}: {w}/{n} wins; median loss length {ml and round(ml,1)} min")
print("\nElo trajectory (every ~40th finished game):", [(r["created"][5:10], r["elo1"]) for r in rows[::40] if r["elo1"]])
