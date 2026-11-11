import json, collections, statistics
F = list(json.load(open("cache/feats.json")).values())
W = [f for f in F if f["result"] == "win"]; L = [f for f in F if f["result"] == "loss"]
AIR = {"ORACLE","BANSHEE","VOIDRAY","PHOENIX","LIBERATOR","LIBERATORAG","MUTALISK","TEMPEST","CARRIER","INTERCEPTOR","BATTLECRUISER","BROODLORD","CORRUPTOR","VIKINGFIGHTER","MEDIVAC","RAVEN","OBSERVER","OVERLORD","OVERSEER","WARPPRISM","WARPPRISMPHASING"}
HARASS_AIR = {"ORACLE","BANSHEE","VOIDRAY","PHOENIX","LIBERATOR","LIBERATORAG","MUTALISK"}
WORKERS = {"SCV","PROBE","DRONE"}
def snap(f, t, k):
    for s in f["snaps"]:
        if s["t"] == t: return s[k]
    return None
def launches(f): return [e for e in f["engage"] if e["action"] == "launch"]
def classify(f):
    pl = sorted((t, en) for t, role, en in f["probe_lost"] if role == "GATHERING")
    first = pl[:20]
    air = sum(1 for t, en in first if en in HARASS_AIR); wk = sum(1 for t, en in first if en in WORKERS)
    t20 = first[-1][0] if len(first) >= 10 else None
    n_l = len(launches(f)); v = f["army_value"]; ratio = v.get("lost", 0) / max(1, v.get("killed", 0))
    if f["len"] < 420: return "1 rush/cheese: dead before 7:00"
    if len(first) >= 10 and air >= 0.6 * len(first) and (not launches(f) or t20 < launches(f)[0]["t"]): return "2 air harassment broke the mineral line first"
    if n_l == 0: return "3 ground attack at home, never launched (7:00+)"
    if ratio > 1.3: return "4 launched, traded badly (lost/killed > 1.3)"
    return "5 launched, traded evenly or better, still lost"
cls = collections.defaultdict(list)
for f in L: cls[classify(f)].append(f)
print(f"LOSSES by cause (M7 zip, {len(L)} losses with a game record)")
for k in sorted(cls):
    fs = cls[k]
    races = collections.Counter(f["race"] for f in fs)
    opps = collections.Counter(f["opp"] for f in fs).most_common(6)
    print(f"\n{k}: {len(fs)} ({100*len(fs)/len(L):.0f}%)  races {dict(races)}  median length {statistics.median(f['len'] for f in fs)/60:.1f} min")
    print("   top opponents:", opps)
    print("   median probes 5:00 / 7:00:", statistics.median([snap(f,300,'probes') or 0 for f in fs]), "/", statistics.median([snap(f,420,'probes') or 0 for f in fs]),
          "| median own army supply 5:00 / 7:00:", statistics.median([snap(f,300,'army') or 0 for f in fs]), "/", statistics.median([snap(f,420,'army') or 0 for f in fs]),
          "| median mining probes lost:", statistics.median([sum(1 for t,r,e in f['probe_lost'] if r=='GATHERING') for f in fs]))
    kill = collections.Counter(en for f in fs for t, r, en in sorted(f["probe_lost"])[:20] if r == "GATHERING")
    print("   who killed the first 20 mining probes:", kill.most_common(8))
json.dump({str(f["match"]): classify(f) for f in L}, open("cache/classes.json", "w"))

# Category 3 split by when the killing started and by one-base-at-5:00
c3 = cls["3 ground attack at home, never launched (7:00+)"]
def first_big(f):
    pl = sorted(t for t, r, e in f["probe_lost"] if r == "GATHERING"); return pl[9] if len(pl) >= 10 else None
tb = [first_big(f) for f in c3 if first_big(f)]
print("\nCategory 3: time of the 10th mining-probe death (min):", sorted(round(t/60,1) for t in tb)[::6])
print("   before 6:00:", sum(t < 360 for t in tb), " 6:00-8:00:", sum(360 <= t < 480 for t in tb), " 8:00-10:00:", sum(480 <= t < 600 for t in tb), " after 10:00:", sum(t >= 600 for t in tb))

# economy self-harm: bases at 5:00 and win rate
print("\nWin rate by number of our bases at 5:00 (all M7-zip games):")
for b in (0, 1, 2, 3):
    ws = sum(1 for f in W if snap(f,300,'bases') == b); ls = sum(1 for f in L if snap(f,300,'bases') == b)
    if ws + ls: print(f"   {b} base(s): {ws}-{ls} ({100*ws/(ws+ls):.0f}%)")
print("Win rate by early flag (raised before 4:00), by source:")
src = collections.defaultdict(lambda: [0, 0])
for f in F:
    for key in {(t, s) for t, s, r in f["flags"] if r < 240 and t != "ARMY_OUT_OF_POSITION"}:
        src[key][f["result"] == "loss"] += 1
for key, (w, l) in sorted(src.items(), key=lambda kv: -sum(kv[1])):
    if w + l >= 6: print(f"   {key[0]:<16} {key[1]:<32} {w}-{l} ({100*w/(w+l):.0f}%)")
noflag = [f for f in F if not any(r < 240 and t != "ARMY_OUT_OF_POSITION" for t, s, r in f["flags"])]
print(f"   no early flag at all: {sum(f['result']=='win' for f in noflag)}-{sum(f['result']=='loss' for f in noflag)}")
print("Win rate by pre-raised flag from memory:", {k: f"{sum(1 for f in W if k in f['preraised'])}-{sum(1 for f in L if k in f['preraised'])}" for k in sorted({p for f in F for p in f['preraised']})}, "| none:", f"{sum(1 for f in W if not f['preraised'])}-{sum(1 for f in L if not f['preraised'])}")
# opener by race
print("\nOpener record by enemy race:")
for race in "TZP":
    print("  ", race, {o: f"{sum(1 for f in W if f['opener']==o and f['race']==race)}-{sum(1 for f in L if f['opener']==o and f['race']==race)}" for o in sorted({f['opener'] for f in F if f['race']==race})})
# mining probes lost while own army >= 20 supply and probes lost to units our army could have fought
tot = sum(1 for f in F for t, r, e in f["probe_lost"] if r == "GATHERING")
print("\nMining probes lost, all 367 games:", tot, "| in losses:", sum(1 for f in L for t, r, e in f["probe_lost"] if r == "GATHERING"), "| in wins:", sum(1 for f in W for t, r, e in f["probe_lost"] if r == "GATHERING"))
print("Wins with >= 20 mining probes lost:", sum(1 for f in W if sum(1 for t,r,e in f['probe_lost'] if r=='GATHERING') >= 20), "of", len(W))
# launches analysis
al = [(a, b) for f in F for a, b in zip(f["engage"], f["engage"][1:]) if a["action"] == "launch" and b["action"] == "retreat"]
und = [(a, b) for a, b in al if b.get("enemy_value", 0) > 2 * max(1, a.get("enemy_value", 0))]
print(f"\nLaunch->retreat pairs: {len(al)}; enemy value at retreat more than double the value seen at launch: {len(und)} ({100*len(und)/max(1,len(al)):.0f}%)")
print("median enemy value seen at launch:", statistics.median(a.get("enemy_value", 0) for a, b in al), "| at retreat:", statistics.median(b.get("enemy_value", 0) for a, b in al), "| median seconds to retreat:", statistics.median(b["t"] - a["t"] for a, b in al))
