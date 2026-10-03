"""M6: watch Citadel's ladder games on AI Arena (DESIGN.md §7 M6 "watch the first ladder games").

    poetry run python scripts/ladder_watch.py [--first 20] [--since-match N] [--no-logs]

Reads the AI Arena API with the token in UPLOAD_API_TOKEN for the bot in UPLOAD_BOT_ID (the same
variables `scripts/upload_to_ai_arena.py` uses). The endpoints are from aiarena-web's source
(docs/VERIFY_NOTES.md, "M6 findings"):
- GET /api/bots/<id>/: the bot's settings (`bot_data_enabled`, `bot_zip_md5hash`, `bot_zip_updated`);
- GET /api/match-participations/?bot=<id>: one entry per game with `result` (win/loss/tie/none),
  `result_cause` (game_rules, crash, timeout, race_mismatch, match_cancelled,
  initialization_failure, error), `avg_step_time` (s) and `match_log`;
- GET /api/match-participations/?match=<id>: the opponent's entry; GET /api/bots/<id>/: its name;
- GET /api/matches/<id>/: map and time; GET /api/results/?match=<id>: game length (`game_steps`);
- GET /api/match-participations/<id>/match-log/: Citadel's log for that game (a zip; only the bot's
  owner can download it), saved to ladder_logs/<match>.zip and searched for Citadel's lines
  (STARTUP, METRIC game, the M6 error guard's `ERROR in`, tracebacks).

Prints one row per game (oldest first, games after the latest zip upload unless --since-match) and
the M6 acceptance line: no Crash, TimeOut or initialization failure by Citadel in the first N games.
Reads only; never changes anything on AI Arena.
"""

import argparse
import io
import json
import os
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests

ROOT: Path = Path(__file__).resolve().parent.parent
API: str = "https://aiarena.net/api"
LOG_DIR: Path = ROOT / "ladder_logs"
FAILURE_CAUSES: tuple[str, ...] = ("crash", "timeout", "initialization_failure")
LOOPS_PER_SECOND: float = 22.4


class Api:
    def __init__(self, token: str) -> None:
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Token {token}"
        self._bots: dict[int, dict] = {}

    def get(self, path: str, **params) -> Any:
        response = self.session.get(f"{API}/{path}", params=params, timeout=60)
        response.raise_for_status()
        return response.json()

    def all(self, path: str, **params) -> list[dict]:
        """Every page of a list endpoint (LimitOffsetPagination, 100 per page)."""
        out: list[dict] = []
        params.setdefault("limit", 100)
        page = self.get(path, **params)
        while True:
            out += page.get("results", [])
            if not page.get("next"):
                return out
            response = self.session.get(page["next"], timeout=60)
            response.raise_for_status()
            page = response.json()

    def bot(self, bot_id: int) -> dict:
        if bot_id not in self._bots:
            self._bots[bot_id] = self.get(f"bots/{bot_id}/")
        return self._bots[bot_id]

    def match_log(self, participation_id: int) -> Optional[bytes]:
        response = self.session.get(f"{API}/match-participations/{participation_id}/match-log/", timeout=120)
        return response.content if response.status_code == 200 else None


def scan_log(blob: bytes) -> dict:
    """Citadel's lines in a match-log zip (every text file in it)."""
    text = ""
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        for name in archive.namelist():
            if not name.endswith("/"):
                text += archive.read(name).decode("utf-8", errors="replace") + "\n"
    startup = re.search(r"STARTUP on_start took (\d+) ms", text)
    record = None
    for line in text.splitlines():
        if "METRIC game " in line:
            try:
                record = json.loads(line.split("METRIC game ", 1)[1])
            except json.JSONDecodeError:
                pass
    return {
        "startup_ms": int(startup.group(1)) if startup else None,
        "record": record,
        "guarded": len(re.findall(r" - ERROR in ", text)),
        "tracebacks": text.count("Traceback (most recent call last)"),
        "step_warnings": len(re.findall(r" - STEP \d+ ms", text)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--first", type=int, default=20, help="games the acceptance counts (default 20)")
    parser.add_argument("--since-match", type=int, help="count games from this match id on (default: after the last zip upload)")
    parser.add_argument("--no-logs", action="store_true", help="don't download Citadel's match logs")
    args = parser.parse_args()
    token, bot_id = os.environ.get("UPLOAD_API_TOKEN"), os.environ.get("UPLOAD_BOT_ID")
    if not token or not bot_id:
        print("Set UPLOAD_API_TOKEN and UPLOAD_BOT_ID (environment variables) first.")
        return 2
    api = Api(token)
    bot = api.bot(int(bot_id))
    print(
        f"BOT {bot['name']} (id {bot['id']}): bot_data_enabled={bot['bot_data_enabled']} "
        f"zip md5 {bot.get('bot_zip_md5hash')} updated {bot.get('bot_zip_updated')}"
    )
    uploaded = bot.get("bot_zip_updated")
    parts = sorted(api.all("match-participations/", bot=bot_id), key=lambda p: p["match"])
    rows = []
    for part in parts:
        if args.since_match is not None and part["match"] < args.since_match:
            continue
        match = api.get(f"matches/{part['match']}/")
        if args.since_match is None and uploaded and match.get("created") and match["created"] < uploaded:
            continue  # played by an earlier upload
        if part.get("result") in (None, "", "none") and part.get("result_cause") is None:
            continue  # not finished yet
        others = [p for p in api.all("match-participations/", match=part["match"]) if p["id"] != part["id"]]
        opponent = api.bot(others[0]["bot"]) if others else {}
        results = api.all("results/", match=part["match"])
        steps = results[0].get("game_steps") if results else None
        scan = None
        if not args.no_logs and part.get("match_log"):
            blob = api.match_log(part["id"])
            if blob:
                LOG_DIR.mkdir(exist_ok=True)
                (LOG_DIR / f"{part['match']}.zip").write_bytes(blob)
                scan = scan_log(blob)
        rows.append((part, match, opponent, steps, scan))

    failures = 0
    for i, (part, match, opponent, steps, scan) in enumerate(rows, 1):
        failed = part.get("result") == "loss" and part.get("result_cause") in FAILURE_CAUSES
        failures += failed and i <= args.first
        race = (opponent.get("plays_race") or {}).get("label", "?")  # BotRaceSerializer: {id, label}
        record = (scan or {}).get("record") or {}
        step = record.get("step_ms") or {}
        length = f"{steps / LOOPS_PER_SECOND / 60:.1f}min" if steps else "-"
        avg = part.get("avg_step_time")
        avg_text = f"{avg * 1000:.1f}ms" if avg is not None else "-"
        print(
            f"GAME {i:>2}  match {part['match']}  {str(match.get('created', ''))[:16]}  vs {opponent.get('name', '?')} ({race})  "
            f"map {match.get('map')}  {part.get('result')}/{part.get('result_cause')}  {length}  avg_step={avg_text}",
            end="",
        )
        if scan is not None:
            print(
                f"  startup={scan['startup_ms']}ms metric={'ok' if scan['record'] else 'MISSING'} "
                f"step={step.get('mean')}/{step.get('p99')}/{step.get('max')} guard={step.get('guard_activations')} "
                f"errors={scan['guarded']} tracebacks={scan['tracebacks']} pre={','.join(record.get('preraised') or []) or '-'}",
                end="",
            )
        print("  CITADEL FAILURE" if failed else "")
    counted = min(len(rows), args.first)
    done = counted >= args.first
    print(
        f"M6 acceptance: {counted}/{args.first} games so far, {failures} with a Citadel crash/timeout/initialization failure: "
        + ("PASS" if done and not failures else "FAIL" if failures else "WAITING")
    )
    print(f"(checked {datetime.now().strftime('%Y-%m-%d %H:%M')}; logs in {LOG_DIR.relative_to(ROOT)}/)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
