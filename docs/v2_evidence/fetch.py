"""Read-only fetch of the bot's ladder history from the AI Arena API into ./cache (token from env, never printed).
Signed file URLs are stripped before anything is written to disk."""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests

API = "https://aiarena.net/api"
OUT = Path(__file__).resolve().parent / "cache"
LOGS = OUT / "logs"
LOGS.mkdir(parents=True, exist_ok=True)
TOKEN = os.environ["UPLOAD_API_TOKEN"]
BOT = int(os.environ["UPLOAD_BOT_ID"])

def session():
    s = requests.Session()
    s.headers["Authorization"] = f"Token {TOKEN}"
    return s

S = session()

def get(path, **params):
    for attempt in range(5):
        r = S.get(f"{API}/{path}", params=params, timeout=90)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
    r.raise_for_status()

def all_pages(path, **params):
    out, offset = [], 0
    params.setdefault("limit", 100)
    while True:
        page = get(path, offset=offset, **params)
        out += page["results"]
        offset += len(page["results"])
        if not page.get("next") or not page["results"]:
            return out

def strip_urls(obj):
    if isinstance(obj, dict):
        return {k: strip_urls(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [strip_urls(v) for v in obj]
    if isinstance(obj, str) and obj.startswith("http") and "X-Amz" in obj:
        return obj.split("?", 1)[0]
    return obj

def save(name, data):
    (OUT / name).write_text(json.dumps(strip_urls(data)))

matches = all_pages("matches/", bot=BOT, ordering="id")
save("matches.json", matches)
print("matches", len(matches), flush=True)
parts = all_pages("match-participations/", bot=BOT, ordering="id")
save("participations.json", parts)
print("participations", len(parts), flush=True)
comps = {}
for cid in (37, 38):
    comps[cid] = {"competition": get(f"competitions/{cid}/"), "participants": all_pages("competition-participations/", competition=cid)}
    print("competition", cid, len(comps[cid]["participants"]), flush=True)
save("competitions.json", comps)

# bots: every competition-38 participant, plus anything else referenced
bot_ids = {p["bot"] for c in comps.values() for p in c["participants"]}
bots = {}
bots_file = OUT / "bots.json"
if bots_file.exists():
    bots = {int(k): v for k, v in json.loads(bots_file.read_text()).items()}
def fetch_bot(bid):
    s = session()
    r = s.get(f"{API}/bots/{bid}/", timeout=60)
    if r.status_code != 200:
        return bid, None
    b = r.json()
    return bid, {"id": b["id"], "name": b["name"], "race": (b.get("plays_race") or {}).get("label"), "type": b.get("type"),
                 "zip_updated": b.get("bot_zip_updated"), "zip_public": b.get("bot_zip_publicly_downloadable"), "created": b.get("created")}
todo = sorted(bot_ids - set(bots))
with ThreadPoolExecutor(4) as ex:
    for bid, b in ex.map(fetch_bot, todo):
        if b:
            bots[bid] = b
save("bots.json", bots)
print("bots", len(bots), flush=True)
maps = {}
for mid in sorted({m["map"] for m in matches}):
    mp = get(f"maps/{mid}/")
    maps[mid] = mp.get("name")
save("maps.json", maps)
print("maps", maps, flush=True)

# match logs (owner only). Skip ones already on disk or cleaned by the site.
def fetch_log(p):
    dest = LOGS / f"{p['match']}.zip"
    if dest.exists():
        return "have"
    if not p.get("match_log") or p.get("match_log_has_been_cleaned"):
        return "none"
    s = session()
    for attempt in range(4):
        r = s.get(f"{API}/match-participations/{p['id']}/match-log/", timeout=180)
        if r.status_code == 200:
            dest.write_bytes(r.content)
            return "ok"
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        return f"http{r.status_code}"
    return "fail"
counts = {}
with ThreadPoolExecutor(4) as ex:
    for i, res in enumerate(ex.map(fetch_log, parts)):
        counts[res] = counts.get(res, 0) + 1
        if i % 100 == 99:
            print("logs", i + 1, counts, flush=True)
print("logs done", counts, flush=True)
