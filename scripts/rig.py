"""M8 test rig: Citadel's ladder zip against real ladder bots, in AI Arena's own containers.

    poetry run python scripts/rig.py fetch Thssprtssbt Mulebot norman sludgement2-revived
    poetry run python scripts/rig.py list
    poetry run python scripts/rig.py play --opponent Thssprtssbt --games 20 --label baseline [--jobs 2]
    poetry run python scripts/rig.py report data/rig/baseline

`fetch` downloads bots whose authors set "bot zip publicly downloadable" on AI Arena (read-only API
calls with UPLOAD_API_TOKEN) into ladder_env/sparring/<name>/, with a `rig.json` beside each
(race, type, md5, download time). `list` shows what is there.

`play` runs matches through scripts/ladder_env_test.py's setup (official arena-client images, this
machine's SC2 4.10): the zip in --zip is unpacked as the ladder would, and each bot starts with
`--OpponentId`, so opponent memory and ares's opener data behave as on the ladder. Games cycle
through the 7 pool maps and alternate seats. `--jobs N` runs N lanes side by side; each lane has
its own work folder (ladder_env/rig/lane<k>), private Docker network and Citadel ./data, and plays its games one
after another, so within a lane the memory builds up game by game as it does on the ladder.

Every finished match appends one JSON line to data/rig/<label>/results.jsonl: opponent, map, seat,
outcome, the arena client's result, Citadel's whole `METRIC game` record, error counts, the zip's
content hash. `report` (also printed after `play`) counts wins and losses per opponent with a 95%
interval, and the share of games on one base at 6:00.

The opponents are other people's programs: they only ever run inside the bot containers, never on
this machine directly. Nothing here uploads anything.
"""

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from datetime import datetime, timezone
from itertools import cycle, islice
from pathlib import Path
from typing import Optional

ROOT: Path = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import scripts.ladder_env_test as env  # noqa: E402
from scripts.create_ladder_zip import zip_content_hash  # noqa: E402

API: str = "https://aiarena.net/api"
SPARRING: Path = ROOT / "ladder_env" / "sparring"
LANES: Path = ROOT / "ladder_env" / "rig"
RESULTS: Path = ROOT / "data" / "rig"
POOL_MAPS: tuple[str, ...] = (
    "MagannathaAIE_v2", "UltraloveAIE_v2", "LeyLinesAIE_v3", "TorchesAIE_v4",
    "PylonAIE_v4", "PersephoneAIE_v4", "IncorporealAIE_v4",
)
MAX_ZIP_BYTES: int = 300 * 1024 * 1024  # a sanity cap (one ladder zip was 86 MB)
WRITE_LOCK = threading.Lock()


def log(message: str) -> None:
    print(message, flush=True)


# -- fetch ------------------------------------------------------------------------------------------

def fetch(names: list[str]) -> int:
    import requests

    token = os.environ.get("UPLOAD_API_TOKEN")
    if not token:
        log("Set UPLOAD_API_TOKEN (the AI Arena API token) first.")
        return 2
    session = requests.Session()
    session.headers["Authorization"] = f"Token {token}"
    failed = 0
    for name in names:
        found = session.get(f"{API}/bots/", params={"name": name}, timeout=60)
        found.raise_for_status()
        exact = [b for b in found.json().get("results", []) if b.get("name") == name]
        if len(exact) != 1:
            log(f"FETCH {name}: {len(exact)} bots with exactly that name; skipped")
            failed += 1
            continue
        bot = exact[0]
        if not bot.get("bot_zip_publicly_downloadable"):
            log(f"FETCH {name}: its author has not made the zip downloadable; skipped")
            failed += 1
            continue
        response = session.get(f"{API}/bots/{bot['id']}/zip/", timeout=300)
        if response.status_code != 200 or len(response.content) > MAX_ZIP_BYTES:
            log(f"FETCH {name}: download failed (HTTP {response.status_code}, {len(response.content)} bytes); skipped")
            failed += 1
            continue
        folder = SPARRING / name
        shutil.rmtree(folder, ignore_errors=True)
        (folder / "bot").mkdir(parents=True)
        zip_path = folder / "bot.zip"
        zip_path.write_bytes(response.content)
        with zipfile.ZipFile(zip_path) as archive:
            root = (folder / "bot").resolve()
            for member in archive.namelist():  # refuse paths that would leave the folder
                if not (root / member).resolve().is_relative_to(root):
                    raise SystemExit(f"FETCH {name}: zip entry {member!r} points outside its folder")
            archive.extractall(root)
        meta = {
            "name": name, "id": bot["id"], "race": (bot.get("plays_race") or {}).get("label"), "type": bot.get("type"),
            "md5": hashlib.md5(response.content).hexdigest(), "site_md5": bot.get("bot_zip_md5hash"),
            "zip_updated": bot.get("bot_zip_updated"), "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        # some bots need the data folder the ladder keeps for them; take it when its author shares it
        meta["data"] = None
        if bot.get("bot_data_publicly_downloadable") and bot.get("bot_data"):
            data = session.get(f"{API}/bots/{bot['id']}/data/", timeout=300)
            if data.status_code == 200 and len(data.content) <= MAX_ZIP_BYTES:
                (folder / "data").mkdir()
                (folder / "data.zip").write_bytes(data.content)
                with zipfile.ZipFile(folder / "data.zip") as archive:
                    root = (folder / "data").resolve()
                    for member in archive.namelist():
                        if not (root / member).resolve().is_relative_to(root):
                            raise SystemExit(f"FETCH {name}: data zip entry {member!r} points outside its folder")
                    archive.extractall(root)
                meta["data"] = f"{len(data.content)} bytes, {len(list(root.rglob('*')))} entries"
            else:
                meta["data"] = f"download failed (HTTP {data.status_code})"
        (folder / "rig.json").write_text(json.dumps(meta, indent=1))
        ok = "md5 matches the site" if meta["md5"] == meta["site_md5"] else "MD5 DIFFERS FROM THE SITE"
        log(f"FETCH {name}: race {meta['race']}, type {meta['type']}, {len(response.content)} bytes, {ok}; shared data: {meta['data'] or 'none'}")
    return 1 if failed else 0


def sparring_bots() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for meta in sorted(SPARRING.glob("*/rig.json")):
        out[meta.parent.name] = json.loads(meta.read_text())
    return out


# -- play -------------------------------------------------------------------------------------------

def install_opponent(workdir: Path, name: str) -> None:
    """A fresh copy of the downloaded bot, keeping the ./data it wrote in this lane's earlier games."""
    target = workdir / "bots" / name
    saved = workdir / "bots" / f".{name}-data"
    if (target / "data").exists():
        shutil.rmtree(saved, ignore_errors=True)
        shutil.move(str(target / "data"), saved)
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(SPARRING / name / "bot", target)
    if saved.exists():
        shutil.rmtree(target / "data", ignore_errors=True)
        shutil.move(str(saved), target / "data")
    elif (SPARRING / name / "data").exists() and not (target / "data").exists():
        shutil.copytree(SPARRING / name / "data", target / "data")  # the data its author shares, as a start


def play_lane(lane: int, games: list[tuple[int, str, int]], meta: dict, args: argparse.Namespace, out_file: Path, zip_hash: str) -> None:
    name = meta["name"]
    workdir = LANES / f"lane{lane}"
    matches = [
        env.Match(name, meta["race"], f"rig-{name}", seat, map_name, opponent_type=meta["type"])
        for _, map_name, seat in games
    ]
    with WRITE_LOCK:  # the one-time downloads (images, sc2_controller, bootstrap) must not race
        env.prepare(workdir, (ROOT / args.zip).resolve(), keep_data=not args.fresh_data, matches=matches,
                    bridge=True)
        install_opponent(workdir, name)
    for (number, map_name, seat), match in zip(games, matches):
        started = time.perf_counter()
        result, run_dir = env.play(workdir, number, match)
        info = env.citadel_log(run_dir, seat)
        record = info["record"] or {}
        row = {
            "label": args.label, "game": number, "lane": lane, "opponent": name, "opponent_race": meta["race"],
            "opponent_md5": meta["md5"], "map": map_name, "seat": seat,
            "outcome": env.citadel_outcome(result, seat), "arena_result": (result or {}).get("type"),
            "game_steps": (result or {}).get("game_steps"), "real_s": round(time.perf_counter() - started, 1),
            "zip_content_hash": zip_hash, "startup_ms": info["startup_ms"], "guarded_errors": info["guarded_errors"],
            "tracebacks": info["tracebacks"], "record": record, "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        with WRITE_LOCK:
            with open(out_file, "a") as f:
                f.write(json.dumps(row, separators=(",", ":")) + "\n")
        log(
            f"ROW {number:>3} lane={lane} {name:<22} {map_name:<18} seat={seat} citadel={row['outcome']:<8} "
            f"arena={row['arena_result']} game={record.get('game_length_s', '-')}s opener={record.get('opener', '-')} "
            f"pre={','.join(record.get('preraised') or []) or '-'} errors={info['guarded_errors']} "
            f"tracebacks={info['tracebacks']} real={row['real_s']:.0f}s"
        )


def play(args: argparse.Namespace) -> int:
    bots = sparring_bots()
    if args.opponent not in bots:
        log(f"No downloaded bot named {args.opponent!r}. Run `rig.py fetch {args.opponent}` first; have: {', '.join(bots) or 'none'}")
        return 2
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        log("Docker isn't running.")
        return 2
    zip_path = (ROOT / args.zip).resolve()
    zip_hash = zip_content_hash(str(zip_path))
    out_dir = RESULTS / args.label
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "results.jsonl"
    maps = list(islice(cycle(POOL_MAPS), args.games))
    games = [(i + 1, maps[i], 1 + i % 2) for i in range(args.games)]
    lanes = [games[k::args.jobs] for k in range(args.jobs)]
    log(f"PLAY {args.games} games vs {args.opponent} in {args.jobs} lane(s); zip content hash {zip_hash[:12]}; results {out_file.relative_to(ROOT)}")
    threads = [
        threading.Thread(target=play_lane, args=(args.first_lane + k, lane, bots[args.opponent], args, out_file, zip_hash))
        for k, lane in enumerate(lanes) if lane
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return report(out_dir)


# -- report -----------------------------------------------------------------------------------------

def wilson(wins: int, n: int) -> tuple[float, float]:
    """95% Wilson interval for a win rate."""
    if n == 0:
        return 0.0, 1.0
    z, p = 1.96, wins / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def report(folder: Path) -> int:
    path = folder / "results.jsonl"
    if not path.exists():
        log(f"No {path}")
        return 2
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    log(f"\nREPORT {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}: {len(rows)} games")
    log(f"{'opponent':<24}{'games':>6}{'W':>4}{'L':>4}{'T':>4}{'other':>6}  {'win rate (95% interval)':<26}{'1 base at 6:00':>15}{'errors':>8}")
    bad = 0
    for name in sorted({r["opponent"] for r in rows}):
        rs = [r for r in rows if r["opponent"] == name]
        wins = sum(r["outcome"].startswith("Win") for r in rs)
        losses = sum(r["outcome"] == "Loss" for r in rs)
        ties = sum(r["outcome"] == "Tie" for r in rs)
        other = len(rs) - wins - losses - ties
        bad += other
        decided = wins + losses + ties
        low, high = wilson(wins, decided)
        one_base = [r for r in rs if (r["record"].get("bases") or {}).get("6:00") == 1]
        with_bases = [r for r in rs if (r["record"].get("bases") or {}).get("6:00") is not None]
        errors = sum(r["guarded_errors"] + r["tracebacks"] for r in rs)
        rate = f"{100 * wins / decided:.0f}% ({100 * low:.0f}-{100 * high:.0f}%)" if decided else "-"
        log(f"{name:<24}{len(rs):>6}{wins:>4}{losses:>4}{ties:>4}{other:>6}  {rate:<26}{f'{len(one_base)}/{len(with_bases)}':>15}{errors:>8}")
    if bad:
        log(f"{bad} game(s) ended without a normal result (crash, time-out, no result): see the outcome field")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_fetch = sub.add_parser("fetch", help="download publicly downloadable ladder bots by name")
    p_fetch.add_argument("names", nargs="+")
    sub.add_parser("list", help="show the downloaded bots")
    p_play = sub.add_parser("play", help="play the zip against a downloaded bot")
    p_play.add_argument("--opponent", required=True)
    p_play.add_argument("--games", type=int, default=20)
    p_play.add_argument("--jobs", type=int, default=1, help="lanes run side by side (about 2 CPU cores each)")
    p_play.add_argument("--first-lane", type=int, default=0, help="number of the first lane (to run two `play` commands at once)")
    p_play.add_argument("--label", default=datetime.now().strftime("%Y%m%d-%H%M"), help="results go to data/rig/<label>/")
    p_play.add_argument("--zip", default="publish/Citadel.zip")
    p_play.add_argument("--fresh-data", action="store_true", help="start each lane with an empty Citadel ./data")
    p_report = sub.add_parser("report", help="summarise a results folder")
    p_report.add_argument("folder", type=Path)
    args = parser.parse_args()
    if args.command == "fetch":
        return fetch(args.names)
    if args.command == "list":
        for name, meta in sparring_bots().items():
            log(f"{name:<24} race {meta['race']}  type {meta['type']:<10} zip of {str(meta['zip_updated'])[:10]}  fetched {meta['fetched'][:10]}")
        return 0
    if args.command == "play":
        if args.games < 1 or args.jobs < 1:
            parser.error("--games and --jobs must be at least 1")
        return play(args)
    return report(args.folder.resolve())


if __name__ == "__main__":
    sys.exit(main())
