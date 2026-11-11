"""Download the bot's own match logs (owner-only endpoint) into cache/logs. Read-only on AI Arena."""
import json, os, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests
LOGS = Path("cache/logs"); LOGS.mkdir(parents=True, exist_ok=True)
TOKEN = os.environ["UPLOAD_API_TOKEN"]
parts = sorted(json.load(open("cache/participations.json")), key=lambda p: p["match"])
def fetch(p):
    dest = LOGS / f"{p['match']}.zip"
    if dest.exists():
        return "have"
    if not p.get("match_log"):
        return "none"
    s = requests.Session(); s.headers["Authorization"] = f"Token {TOKEN}"
    for attempt in range(4):
        try:
            r = s.get(f"https://aiarena.net/api/match-participations/{p['id']}/match-log/", timeout=180)
        except requests.RequestException:
            time.sleep(2 ** attempt); continue
        if r.status_code == 200:
            dest.write_bytes(r.content); return "ok"
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt); continue
        return f"http{r.status_code}"
    return "fail"
counts = {}
with ThreadPoolExecutor(4) as ex:
    for i, res in enumerate(ex.map(fetch, parts)):
        counts[res] = counts.get(res, 0) + 1
        if i % 100 == 99: print("logs", i + 1, counts, flush=True)
print("logs done", counts, flush=True)
