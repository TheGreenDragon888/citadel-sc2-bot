import zipfile, json, re, collections, os, statistics
rows = {r["match"]: r for r in json.load(open("cache/rows.json"))}
recs = {int(k): v for k, v in json.load(open("cache/records.json")).items()}
def ts(s):
    a, b = s.split(":"); return int(a) * 60 + int(b)
feats = {}
for m, rec in recs.items():
    if rec.get("version") != 7 or rows[m]["result"] not in ("win", "loss"): continue
    text = zipfile.ZipFile(f"cache/logs/{m}.zip").read("stdout.log").decode("utf-8", "replace")
    f = {"match": m, "opp": rows[m]["opp"], "race": rows[m]["race"], "map": rows[m]["map"], "result": rows[m]["result"], "len": rec["game_length_s"],
         "opener": rec.get("opener"), "probe_lost": [], "unit_lost": [], "snaps": [], "defend": [], "engage_lines": [], "enemy_types": collections.Counter()}
    for l in text.splitlines():
        if " - " not in l: continue
        body = l.split(" - ", 1)[1]
        if body.startswith("PROBE lost"):
            mm = re.search(r"\((\d+:\d+), (\w+)\); nearest enemy (\w+) at ([\d.]+)", body) or re.search(r"\((\d+:\d+), (\w+)\)", body)
            if mm: f["probe_lost"].append((ts(mm.group(1)), mm.group(2), mm.group(3) if mm.lastindex >= 3 else None))
        elif body.startswith("UNIT lost"):
            mm = re.search(r"UNIT lost (\w+) at .*?\((\d+:\d+), (\w+)", body)
            if mm: f["unit_lost"].append((ts(mm.group(2)), mm.group(1), mm.group(3)))
        elif body.startswith("METRIC snap"):
            d = dict(kv.split("=") for kv in body.split()[2:])
            sup = d["supply"].split("/")
            f["snaps"].append({"t": ts(d["t"]), "supply": int(sup[0]), "army": float(d["army_supply"]), "probes": int(d["probes"]), "bases": int(d["bases"]),
                               "min": int(d["minerals"]), "gas": int(d["vespene"]), "vl": int(d["value_lost"]), "vk": int(d["value_killed"])})
        elif body.startswith("DEFEND"):
            mm = re.match(r"DEFEND (\d+:\d+): (.*)", body)
            if mm: f["defend"].append((ts(mm.group(1)), mm.group(2)[:160]))
        elif body.startswith("ENGAGE"):
            mm = re.search(r"vs (.*?) \(\d+\) \|", body)
            if mm:
                for cnt, typ in re.findall(r"(\d+) ([A-Z_]+)", mm.group(1)): f["enemy_types"][typ] = max(f["enemy_types"][typ], int(cnt))
    f["engage"] = rec.get("engage", []); f["army_value"] = rec.get("army_value", {}); f["first_aggr"] = rec.get("first_aggression") or {}
    f["flags"] = [(x["threat"], x["source"], x["raised"]) for x in rec.get("flags", [])]; f["lost_by_intent"] = rec.get("lost_by_intent", {}); f["lost_far"] = rec.get("lost_far", {})
    f["probes"] = rec.get("probes", {}); f["bases"] = rec.get("bases", {}); f["unspent"] = rec.get("unspent", {}); f["counter"] = rec.get("counterattacks", [])
    f["tech_seen"] = rec.get("tech_seen", []); f["step"] = rec.get("step_ms", {}); f["errors"] = rec.get("errors", {}); f["preraised"] = rec.get("preraised", [])
    f["enemy_types"] = dict(f["enemy_types"]); f["blinks"] = rec.get("blinks"); f["storms"] = rec.get("storms"); f["mix_changes"] = rec.get("mix_changes", [])
    feats[m] = f
json.dump(feats, open("cache/feats.json", "w"))
print("games with features:", len(feats), collections.Counter(f["result"] for f in feats.values()))
