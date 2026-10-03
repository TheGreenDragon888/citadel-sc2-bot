"""M6 ladder-environment test (DESIGN.md §8 "Ladder environment"): Citadel's actual ladder zip
played in AI Arena's arena client, one match at a time, with Citadel's ./data kept between matches
as the ladder keeps it with "bot data enabled".

    poetry run python scripts/ladder_env_test.py [--zip publish/Citadel.zip] [--workdir ladder_env]
        [--matches 1,3-5] [--keep-data] [--list]

Setup (the "hybrid" the user chose for M6): local-play-bootstrap's host-network layout
(`docker-compose-host-network.yml`) with AI Arena's official v0.8.0 proxy and bot images. The
official v0.8.0 `sc2_controller` program is taken from the last layer of
`aiarena/arenaclient-sc2:v0.8.0` (the image's other layers are SC2 4.10, which doesn't fit this
cloud machine's disk) and runs in the proxy image with this machine's SC2 4.10 mounted. On a kernel
without IPv6 (this cloud container), the proxy and the sc2 controller get an LD_PRELOAD shim
(`scripts/ladder_env/ipv4only.c`) because their port picker binds every port on IPv6 and IPv4; the
bots' containers are untouched. Each bot runs as on the ladder: `python run.py --GamePort ...
--LadderServer ... --StartPort ... --OpponentId <id>` inside `/bot` (VERIFY_NOTES, "M6 findings").

Opponents: local-play-bootstrap's `loser_bot` and `basic_bot`, the scripted cheese bots of
`scripts/test_bots` packaged as ladder bots, and a second copy of the zip (mirror). The three
worker-rush games share one opponent id, so the third pre-raises WORKER_RUSH from memory (§5).

Each match prints a `ROW` line. RESULT PASS when every match has an arena-client result that is not
Citadel's Crash, TimeOut, an InitializationError or an Error; Citadel's log has its STARTUP line
under §6's 5 s, its `METRIC game` line, and no traceback outside the M6 error guard's; the third
worker-rush game pre-raised WORKER_RUSH; and Citadel's ./data holds every opponent's memory file and
one game-log line per match, under 5 MB.
"""

import argparse
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT: Path = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from bot.constants import DATA_MAX_BYTES, GAME_LOG_FILE, LOGS_SUBDIR, STARTUP_WARN_MS  # noqa: E402
from bot.memory.opponent_store import file_name  # noqa: E402

IMAGE_TAG: str = "v0.8.0"  # local-play-bootstrap's images (docker-compose.yml at BOOTSTRAP_COMMIT)
PROXY_IMAGE: str = f"aiarena/arenaclient-proxy:{IMAGE_TAG}"
BOT_IMAGE: str = f"aiarena/arenaclient-bot:{IMAGE_TAG}"
SC2_IMAGE_REPO: str = "aiarena/arenaclient-sc2"
# the last layer of aiarena/arenaclient-sc2:v0.8.0: `COPY /app/target/*/sc2_controller /app/sc2_controller`
SC2_CONTROLLER_LAYER: str = "sha256:1e7d7a0d0262cd34689121d712bce70184423dc318a1fd3c6f0bd4dd5979a971"
BOOTSTRAP_REPO: str = "https://github.com/aiarena/local-play-bootstrap"
BOOTSTRAP_COMMIT: str = "6de4228"
SHIM_SOURCE: Path = ROOT / "scripts" / "ladder_env" / "ipv4only.c"
MATCH_TIMEOUT_S: int = 7500  # the arena client's MAX_REAL_TIME is 7200 s
CITADEL: str = "Citadel"
MIRROR: str = "Citadel2"


@dataclass(frozen=True)
class Match:
    opponent: str  # bot folder in <workdir>/bots
    race: str  # P/T/Z
    opponent_id: str  # what Citadel gets as --OpponentId
    citadel_seat: int  # 1 or 2
    map_name: str


# scripted cheese bots as ladder bots: folder -> (TEST_BOTS name, race, seed, variant)
CHEESE_BOTS: dict[str, tuple[str, str, int, Optional[str]]] = {
    "worker_rush_z": ("worker_rush", "Zerg", 101, None),
    "worker_rush_t": ("worker_rush", "Terran", 102, None),
    "worker_rush_p": ("worker_rush", "Protoss", 103, None),
    "cannon_rush": ("cannon_rush", "Protoss", 104, None),
    "twelve_pool": ("twelve_pool", "Zerg", 105, None),
    "proxy_rax": ("proxy_rax", "Terran", 106, None),
}

MATCHES: list[Match] = [
    Match("loser_bot", "T", "le-loser-bot", 1, "PylonAIE_v4"),
    Match("basic_bot", "T", "le-basic-bot", 2, "TorchesAIE_v4"),
    Match("worker_rush_z", "Z", "le-worker-rush", 1, "MagannathaAIE_v2"),
    Match("worker_rush_t", "T", "le-worker-rush", 2, "UltraloveAIE_v2"),
    Match("worker_rush_p", "P", "le-worker-rush", 1, "LeyLinesAIE_v3"),
    Match("cannon_rush", "P", "le-cannon-rush", 2, "PersephoneAIE_v4"),
    Match("twelve_pool", "Z", "le-twelve-pool", 1, "IncorporealAIE_v4"),
    Match("proxy_rax", "T", "le-proxy-rax", 2, "PylonAIE_v4"),
    Match(MIRROR, "P", "le-citadel2", 1, "TorchesAIE_v4"),
    Match("twelve_pool", "Z", "le-twelve-pool", 2, "LeyLinesAIE_v3"),
]
PRERAISE_MATCH: int = 5  # the third game against le-worker-rush

COMPOSE = """# Written by scripts/ladder_env_test.py: local-play-bootstrap's host-network layout with the
# official {tag} images; the official {tag} sc2_controller binary runs in the proxy image with this
# machine's SC2 mounted (the SC2 image doesn't fit this machine's disk).
services:
  sc2_controller:
    network_mode: host
    image: {proxy_image}
    entrypoint: ["./sc2_controller"]
    working_dir: /app
    environment:
      - "ACSC2_PORT=8083"
      - "ACSC2_PROXY_HOST=127.0.0.1"{shim_env}
    volumes:
      - "./logs:/logs"
      - "./sc2_controller:/app/sc2_controller:ro"{shim_volume}
      - "{sc2_path}:/root/StarCraftII:ro"
      - "./maps:/root/StarCraftII/Maps"

  bot_controller1:
    network_mode: host
    image: {bot_image}
    volumes:
      - "./bots:/bots"
      - "./logs/bot_controller1:/logs"
    environment:
      - "ACBOT_PORT=8081"
      - "ACBOT_PROXY_HOST=127.0.0.1"

  bot_controller2:
    network_mode: host
    image: {bot_image}
    volumes:
      - "./bots:/bots"
      - "./logs/bot_controller2:/logs"
    environment:
      - "ACBOT_PORT=8082"
      - "ACBOT_PROXY_HOST=127.0.0.1"

  proxy_controller:
    network_mode: host
    image: {proxy_image}
    environment:
      - "ACPROXY_PORT=8080"
      - "ACPROXY_BOT_CONT_1_HOST=127.0.0.1"
      - "ACPROXY_BOT_CONT_2_HOST=127.0.0.1"
      - "ACPROXY_SC2_CONT_HOST=127.0.0.1"{shim_env}
    volumes:
      - "./matches:/app/matches"
      - "./config.toml:/app/config.toml"
      - "./results.json:/app/results.json"
      - "./replays:/replays"
      - "./logs:/logs"{shim_volume}
"""

CHEESE_RUN = '''"""Ladder entry point for the scripted {name} bot, written by scripts/ladder_env_test.py."""
import sc2.main  # noqa: F401  (loads sc2.portconfig, which the template's ladder.py uses unimported)
from sc2.data import Race
from sc2.player import Bot

from ladder import run_ladder_game
from scripts.test_bots import TEST_BOTS

bot_class, _ = TEST_BOTS["{name}"]
result, opponent_id = run_ladder_game(Bot(Race.{race}, bot_class(seed={seed}, variant={variant!r})))
print(result, " against opponent ", opponent_id)
'''


def log(message: str) -> None:
    print(message, flush=True)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kwargs)


def ipv6_supported() -> bool:
    try:
        socket.socket(socket.AF_INET6, socket.SOCK_STREAM).close()
        return True
    except OSError:
        return False


def installed_package_dir(package: str) -> Path:
    spec = importlib.util.find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        raise SystemExit(f"{package} is not installed; run `poetry install`")
    return Path(list(spec.submodule_search_locations)[0]).resolve()


def fetch_sc2_controller(dest: Path) -> None:
    """The sc2_controller binary from its image layer on Docker Hub (sha256-checked)."""
    if dest.exists():
        return
    log(f"SETUP downloading sc2_controller ({SC2_IMAGE_REPO}:{IMAGE_TAG} layer {SC2_CONTROLLER_LAYER[:19]})")
    token_url = f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{SC2_IMAGE_REPO}:pull"
    with urllib.request.urlopen(token_url, timeout=60) as response:
        token = json.load(response)["token"]
    request = urllib.request.Request(
        f"https://registry-1.docker.io/v2/{SC2_IMAGE_REPO}/blobs/{SC2_CONTROLLER_LAYER}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        blob = response.read()
    digest = "sha256:" + hashlib.sha256(blob).hexdigest()
    if digest != SC2_CONTROLLER_LAYER:
        raise SystemExit(f"sc2_controller layer digest {digest} != {SC2_CONTROLLER_LAYER}")
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        member = tar.extractfile("app/sc2_controller")
        if member is None:
            raise SystemExit("app/sc2_controller not in the layer")
        dest.write_bytes(member.read())
    dest.chmod(0o755)


def prepare(workdir: Path, zip_path: Path, keep_data: bool, matches: list[Match]) -> None:
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        raise SystemExit("Docker isn't running (start it with `dockerd &` in this container)")
    for image in (PROXY_IMAGE, BOT_IMAGE):
        if subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode != 0:
            log(f"SETUP pulling {image}")
            run(["docker", "pull", image])
    workdir.mkdir(parents=True, exist_ok=True)
    fetch_sc2_controller(workdir / "sc2_controller")
    shim = not ipv6_supported()
    if shim:
        run(["gcc", "-shared", "-fPIC", "-O2", "-o", str(workdir / "ipv4only.so"), str(SHIM_SOURCE), "-ldl"])

    bootstrap = workdir / "local-play-bootstrap"
    if not bootstrap.exists():
        run(["git", "clone", "-q", BOOTSTRAP_REPO, str(bootstrap)])
    run(["git", "-C", str(bootstrap), "checkout", "-q", BOOTSTRAP_COMMIT])
    shutil.copy(bootstrap / "config.toml", workdir / "config.toml")

    sc2_path = Path(os.environ.get("SC2PATH", Path.home() / "StarCraftII")).resolve()
    maps = workdir / "maps"
    maps.mkdir(exist_ok=True)
    for name in sorted({m.map_name for m in matches}):
        if not (maps / f"{name}.SC2Map").exists():
            shutil.copy(sc2_path / "Maps" / f"{name}.SC2Map", maps)

    bots = workdir / "bots"
    bots.mkdir(exist_ok=True)
    for name in ("loser_bot", "basic_bot"):
        if not (bots / name).exists():
            shutil.copytree(bootstrap / "bots" / name, bots / name)
    # Citadel: a fresh copy of the zip every run; its ./data survives only with --keep-data
    install_zip(zip_path, bots / CITADEL, keep_data)
    if any(m.opponent == MIRROR for m in matches):
        install_zip(zip_path, bots / MIRROR, keep_data=False)
    for folder, (name, race, seed, variant) in CHEESE_BOTS.items():
        if any(m.opponent == folder for m in matches):
            package_cheese_bot(bots / folder, name, race, seed, variant)

    (workdir / "docker-compose.yml").write_text(
        COMPOSE.format(
            tag=IMAGE_TAG,
            proxy_image=PROXY_IMAGE,
            bot_image=BOT_IMAGE,
            sc2_path=sc2_path,
            shim_env='\n      - "LD_PRELOAD=/app/ipv4only.so"' if shim else "",
            shim_volume='\n      - "./ipv4only.so:/app/ipv4only.so:ro"' if shim else "",
        )
    )
    log(f"SETUP workdir {workdir}; IPv4 shim {'on (no IPv6 in this kernel)' if shim else 'off'}; SC2 {sc2_path}")


def install_zip(zip_path: Path, folder: Path, keep_data: bool) -> None:
    saved = None
    if keep_data and (folder / "data").exists():
        saved = folder.parent / f".{folder.name}-data"
        shutil.rmtree(saved, ignore_errors=True)
        shutil.move(str(folder / "data"), saved)
    shutil.rmtree(folder, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(folder)
    if saved is not None:
        shutil.move(str(saved), folder / "data")


def package_cheese_bot(folder: Path, name: str, race: str, seed: int, variant: Optional[str]) -> None:
    """A scripted test bot as a ladder bot: run.py, the template's ladder.py, scripts/test_bots and
    the same python-sc2 the Citadel zip carries."""
    shutil.rmtree(folder, ignore_errors=True)
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(ROOT / "scripts" / "test_bots", folder / "scripts" / "test_bots", ignore=ignore)
    shutil.copytree(installed_package_dir("sc2"), folder / "sc2", ignore=ignore)
    shutil.copy(ROOT / "ladder.py", folder / "ladder.py")
    (folder / "run.py").write_text(CHEESE_RUN.format(name=name, race=race, seed=seed, variant=variant))


def matches_line(match_no: int, match: Match) -> str:
    citadel = (f"le-{CITADEL.lower()}", CITADEL, "P", "python")
    opponent = (match.opponent_id, match.opponent, match.race, "python")
    first, second = (citadel, opponent) if match.citadel_seat == 1 else (opponent, citadel)
    return ",".join([*first, *second, match.map_name])


def play(workdir: Path, match_no: int, match: Match) -> tuple[Optional[dict], Path]:
    """One match through the arena client; returns its results.json entry and the archived logs."""
    (workdir / "matches").write_text(matches_line(match_no, match) + "\n")
    (workdir / "results.json").write_text('{\n  "results": [\n  ]\n}')
    for name in ("logs", "replays"):
        shutil.rmtree(workdir / name, ignore_errors=True)
        (workdir / name).mkdir()
    out = workdir / "runs" / f"{match_no:02d}"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    compose = ["docker", "compose", "-f", str(workdir / "docker-compose.yml")]
    with open(out / "compose.log", "w") as compose_log:
        try:
            subprocess.run(
                [*compose, "up", "--abort-on-container-exit", "--exit-code-from", "proxy_controller"],
                cwd=workdir, stdout=compose_log, stderr=subprocess.STDOUT, timeout=MATCH_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            compose_log.write("\nladder_env_test: match timed out\n")
        subprocess.run([*compose, "down"], cwd=workdir, stdout=compose_log, stderr=subprocess.STDOUT)
    shutil.copytree(workdir / "logs", out / "logs")
    shutil.copytree(workdir / "replays", out / "replays")
    shutil.copy(workdir / "results.json", out / "results.json")
    results = json.loads((workdir / "results.json").read_text()).get("results") or []
    return (results[-1] if results else None), out


def citadel_log(out: Path, seat: int) -> dict:
    """What Citadel's own log says: STARTUP ms, the METRIC game record, guarded errors, tracebacks."""
    path = out / "logs" / f"bot_controller{seat}" / CITADEL / "stderr.log"
    text = path.read_text(errors="replace") if path.exists() else ""
    startup = re.search(r"STARTUP on_start took (\d+) ms", text)
    record = None
    for line in text.splitlines():
        if "METRIC game " in line:
            record = json.loads(line.split("METRIC game ", 1)[1])
    guarded = len(re.findall(r" - ERROR in ", text))
    return {
        "found": path.exists(),
        "startup_ms": int(startup.group(1)) if startup else None,
        "record": record,
        "guarded_errors": guarded,
        "tracebacks": text.count("Traceback (most recent call last)"),
        "guarded_tracebacks": min(guarded, text.count("Traceback (most recent call last)")),
    }


def citadel_outcome(result: Optional[dict], seat: int) -> str:
    if result is None:
        return "NO RESULT"
    kind = str(result.get("type") or result.get("result") or "?")
    other = 2 if seat == 1 else 1
    if kind == f"Player{seat}Win" or kind == f"Player{other}Crash" or kind == f"Player{other}TimeOut":
        return "Win" if kind.endswith("Win") else f"Win (opponent {kind[7:]})"
    if kind == f"Player{other}Win" or kind == f"Player{seat}Surrender":
        return "Loss"
    if kind == "Tie":
        return "Tie"
    if kind in (f"Player{seat}Crash", f"Player{seat}TimeOut"):
        return f"CITADEL {kind[7:].upper()}"
    return kind


def parse_matches(text: Optional[str]) -> list[int]:
    if not text:
        return list(range(1, len(MATCHES) + 1))
    numbers: list[int] = []
    for part in text.split(","):
        start, _, end = part.partition("-")
        numbers += list(range(int(start), int(end or start) + 1))
    return numbers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--zip", default="publish/Citadel.zip")
    parser.add_argument("--workdir", default="ladder_env")
    parser.add_argument("--matches", help="match numbers, e.g. 1,3-5 (default: all)")
    parser.add_argument("--keep-data", action="store_true", help="keep Citadel's ./data from the last run")
    parser.add_argument("--list", action="store_true", help="print the matches and stop")
    args = parser.parse_args()
    numbers = parse_matches(args.matches)
    if args.list:
        for n in numbers:
            print(f"{n:>2}  {matches_line(n, MATCHES[n - 1])}")
        return 0
    zip_path = (ROOT / args.zip).resolve()
    workdir = (ROOT / args.workdir).resolve()
    with zipfile.ZipFile(zip_path) as archive:
        files = len(archive.namelist())
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()[:12]
    log(f"ZIP {zip_path.relative_to(ROOT)}: {files} files, {zip_path.stat().st_size} bytes, sha256 {digest}")
    prepare(workdir, zip_path, args.keep_data, [MATCHES[n - 1] for n in numbers])

    rows: list[dict] = []
    for n in numbers:
        match = MATCHES[n - 1]
        if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
            log(f"STOP Docker isn't running any more (before match {n}); the run is incomplete")
            return 1
        started = time.perf_counter()
        result, out = play(workdir, n, match)
        info = citadel_log(out, match.citadel_seat)
        record = info["record"] or {}
        step = record.get("step_ms") or {}
        row = {
            "n": n, "match": match, "result": result, "outcome": citadel_outcome(result, match.citadel_seat),
            "info": info, "real_s": time.perf_counter() - started,
        }
        rows.append(row)
        log(
            f"ROW {n:>2}  {match.map_name:<18} {match.opponent:<14} {match.race} seat={match.citadel_seat} "
            f"arena={result.get('type') if result else '-'} citadel={row['outcome']} "
            f"loops={(result or {}).get('game_steps', '-')} game={record.get('game_length_s', '-')}s startup={info['startup_ms']}ms "
            f"step={step.get('mean')}/{step.get('p99')}/{step.get('max')} "
            f"controller_avg_step={(result or {}).get(f'bot{match.citadel_seat}_avg_step_time')} "
            f"metric={'ok' if info['record'] else 'MISSING'} errors={info['guarded_errors']} "
            f"tracebacks={info['tracebacks']} pre={','.join(record.get('preraised') or []) or '-'} "
            f"mem_games={record.get('opponent_games_before', '-')} real={row['real_s']:.0f}s"
        )

    data = workdir / "bots" / CITADEL / "data"
    checks: list[tuple[str, bool, str]] = []
    bad = [f"{r['n']}: {r['outcome']}" for r in rows if r["outcome"] not in ("Win", "Loss", "Tie") and not r["outcome"].startswith("Win (")]
    checks.append(("no Citadel Crash/TimeOut/InitializationError/Error/missing result", not bad, "; ".join(bad)))
    slow = [f"{r['n']}: {r['info']['startup_ms']}" for r in rows if r["info"]["startup_ms"] is None or r["info"]["startup_ms"] >= STARTUP_WARN_MS]
    checks.append((f"STARTUP under {STARTUP_WARN_MS:g} ms in every match", not slow, "; ".join(slow)))
    missing = [str(r["n"]) for r in rows if not r["info"]["record"]]
    checks.append(("METRIC game line in every match", not missing, ", ".join(missing)))
    unguarded = [f"{r['n']}: {r['info']['tracebacks'] - r['info']['guarded_tracebacks']}" for r in rows
                 if r["info"]["tracebacks"] > r["info"]["guarded_tracebacks"]]
    checks.append(("no traceback outside the error guard's", not unguarded, "; ".join(unguarded)))
    if PRERAISE_MATCH in numbers and not args.keep_data and all(n in numbers for n in (3, 4)):
        pre = next(r for r in rows if r["n"] == PRERAISE_MATCH)
        preraised = (pre["info"]["record"] or {}).get("preraised") or []
        checks.append((f"match {PRERAISE_MATCH} (third vs le-worker-rush) pre-raised WORKER_RUSH", "WORKER_RUSH" in preraised, f"{preraised}"))
    files = {str(p.relative_to(data)): p.stat().st_size for p in data.rglob("*") if p.is_file()} if data.exists() else {}
    ids = sorted({r["match"].opponent_id for r in rows})
    memory_files = [f"opponents/{file_name(i)}" for i in ids]
    no_memory = [f for f in memory_files if f not in files]
    log_path = data / LOGS_SUBDIR / GAME_LOG_FILE
    log_lines = len(log_path.read_text().splitlines()) if log_path.exists() else 0
    total = sum(files.values())
    checks.append(("./data: a memory file per opponent id, a game-log line per match, under the size cap",
                   not no_memory and log_lines >= len(rows) and total <= DATA_MAX_BYTES,
                   f"{len(files)} files, {total} bytes; game log {log_lines} lines; missing {no_memory}"))
    for name, ok, detail in checks:
        log(f"CHECK {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    ok = all(good for _, good, _ in checks)
    log(f"M6 ladder environment: {len(rows)} matches; RESULT {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
