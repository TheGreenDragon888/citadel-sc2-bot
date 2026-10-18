# Postmortem: ladder TimeOut vs Voltron (5054944) and the crash vs Nothing (5055364)

**Date:** 2026-10-17 / 2026-10-18 | **Severity:** SEV4 (one loss, -4 Elo, no Citadel code defect found) | **Status:** Draft, plan waiting on decisions D1-D4
**Zip:** md5 `650fd9ec...` (the M7 upload, 2026-10-16 16:01 UTC), code `aae618e`

## Summary

- **Match 5055364 (vs Nothing, TorchesAIE_v4): the opponent crashed, not Citadel.** Citadel won. Nothing (player 1) closed its connection at 10:55 and its process exited with status 1. Citadel's log is clean. No action needed.
- **Match 5054944 (vs Voltron, PylonAIE_v4): scored as Citadel's TimeOut, but the evidence points to the match machine, not Citadel.** At 7:03 game time **both** bots stopped sending requests at the same moment, after a normal step. The arena controller timed both of them out 45 ms apart. When both players time out, its result rule always blames player 1, and Citadel was player 1.
- Nothing in Citadel's code could have prevented this loss. The plan below (1) makes the next stall diagnosable from Citadel's own logs, (2) teaches `ladder_watch.py` to tell these cases apart, and (3) reports the double-timeout rule to AI Arena.

**Method.** Data from the AI Arena API (`UPLOAD_API_TOKEN`): match, result and participation records, Citadel's match logs, the arena client logs and both replays. Replays parsed with s2protocol (build 75689) in a scratch venv. Controller behaviour read in `aiarena/sc2-ai-match-controller` at `b5f6c9b` (main, 2026-10-18). The deployed v0.8.0 binary's commit is not confirmed, but its log lines carry the same file:line numbers (`player.rs:373`, `:408`, `ws_routes.rs:226-232`). python-sc2's loop read in `burnysc2` 7.1.0 (the version in `poetry.lock`). No games were run (this container has no SC2).

## Match 5054944: Citadel vs Voltron (Terran), TimeOut

### Timeline (UTC, 2026-10-17; arena client 504)

| Time | Event |
|---|---|
| 17:36:33 | Match starts. Citadel is player 1 (seat 10001, the game host) |
| 17:36:56 | `STARTUP on_start took 1166 ms`; opener A_Standard; memory: 11 games vs this opponent (1 won) |
| 17:39:22 | Slowest step of the game: 133 ms at 5:00 (`ares 120`). Mean step 8.7 ms per AI Arena |
| 17:40:47.7 | **Citadel's last log line:** `ARMY 07:00 state=gather ... defend=none`. 117/134 supply, 64 probes, no fight in progress. Pace normal (0.83 wall-s per game-s, rising slowly all game as in other games) |
| ~17:40:50 (estimate) | Game reaches loop 9,472 (7:03). **Both** players' last commands are at loop 9,471, issued every 2 loops right up to the end (replay). The game never advances again |
| 17:41:43.862 | Controller: Citadel's seat `BotTimeout(30s)` |
| 17:41:43.907 | Controller: Voltron's seat `BotTimeout(30s)` (45 ms later) |
| 17:42:38.48 | Both SC2 processes finish saving the replay (3 ms apart) |
| 17:42:39.104 | Citadel's seat closes. 3 ms later Citadel logs `Cannot receive: Connection already closed` (it was waiting on a reply) |
| 17:42:39.14 | Result `Player1TimeOut`, `game_steps` 9472. Both bots exit with status 0. Citadel's `on_end` never ran (no `METRIC game` line, no opponent-memory update) |

### What the arena controller measures (source)

- The seat loop is strictly one request at a time (`player.rs:292-331`): wait for the bot's request with a 30 s limit (`bot_recv_message`, `player.rs:45`), send it to SC2 and wait for the reply with a 60 s limit (`sc2_ws_timeout`, `:37`), send the reply to the bot, repeat.
- So the 30 s clock only runs while the controller waits on the bot. A bot blocked in a lockstep step (waiting for the opponent) sits in the SC2 wait. If that lasts 60 s, its seat logs `Sc2Timeout(60s)`, not `BotTimeout`.
- When both seats report a timeout, the result is decided in a fixed order: `(Some(Timeout), _) => Player1TimeOut` (`game_result.rs:95`). Player 1 is blamed regardless of who stopped first.

### Why this points to the machine, not Citadel

1. **Both seats timed out, 45 ms apart, and neither logged `Sc2Timeout`.** That means both bots had gone 30 s without sending a request, starting from nearly the same instant. If only Citadel had hung, Voltron would have been stuck in the SC2 wait. That is what a one-bot hang looks like in every other case we have:

   | Match | Who hung | Controller log |
   |---|---|---|
   | 5051673 (Citadel vs dantalion, 2026-10-16) | dantalion | dantalion's seat `BotTimeout`; Citadel's seat `Sc2Timeout(60s)` 31 s later |
   | 5054762, 5055701, 5045292 (arena client 504, other bots) | one bot | one seat `BotTimeout`, nothing from the other |
   | 5046723 (client 504) | one bot, then the other | two `BotTimeout`s **57 s apart** |
   | **5054944 (this match)** | **both at once** | **two `BotTimeout`s 45 ms apart, no `Sc2Timeout`** |

   Of the last 1,000 games on arena client 504 (2026-10-11 to 10-18), 5 ended in a TimeOut. This is the only one with this signature.
2. **Both bots were acting normally on the last step.** The replay has command events from both players at every odd loop from 9,449 to 9,471 (Citadel 15-22 per loop, Voltron 6-26), then nothing. There was no slowdown or flood of commands before the stop.
3. **Citadel showed no slowdown.** No step over 30 ms after 6:39. The step log and game pace match its other ladder games (the win vs Nothing: 0.70 wall-s per game-s at 7:30).
4. **The controller itself was probably stalled too.** Loop 9,472 should have been reached around 17:40:50 at the game's pace, so the 30 s timers were due around 17:41:20. They fired at 17:41:43, about 23 s late. (This is an estimate from the pace. Items 1-3 don't depend on it.)
5. **Citadel was waiting on a reply when the connection closed**, and it never logged a slow step. So its `on_step` was not running long when the stall began. (A stall elsewhere in its process would not show in its log. See "What went poorly".)

**Root cause (most likely):** something on arena client 504 paused both bot processes (and probably the controller) for 30 s or more at 7:03. Candidates are the machine running out of memory or CPU, or a disk stall. AI Arena runs that machine, so we can't see its system logs. The loss went to Citadel because of the controller's fixed order for a double timeout.

### 5 whys

1. Why did Citadel lose by TimeOut? The controller scored `Player1TimeOut`, and Citadel was player 1.
2. Why player 1? Both seats timed out, and `game_result.rs:95` checks player 1 first.
3. Why did both seats time out? Neither bot sent a request for 30 s after its last reply, and the two replies were 45 ms apart.
4. Why did both bots go silent together? Both were playing normally up to loop 9,471. The one thing they share is the machine they ran on.
5. Why can't we name the machine's fault, or prove where Citadel's process was? The arena client is AI Arena's machine, and Citadel only times `on_step`. python-sc2's own work between steps (building the game state, the game-info request, `_prepare_step`, the unit event hooks, `_after_step` sending actions, the step request; `sc2/main.py:146-201`) is untimed, so a stall there leaves no line in Citadel's log.

## Match 5055364: Nothing (Protoss) vs Citadel, crash: not Citadel

- The result is `Player1Crash`. Player 1 is Nothing. Its seat got a websocket Close frame at 07:16:15 (`BotUnexpectedMessage(Close ...)`, `player.rs:390-399`, scored as Crash), its replay has a `SGameUserLeaveEvent` at loop 14,681 (10:55), and its process exited with **status 1**. Citadel's process exited 0.
- Citadel's side was clean: Victory recorded, `METRIC game` written (0 guarded errors, 0 tracebacks, max step 123.5 ms, step guard never on), opponent memory saved. Army value killed 5,575, lost 2,125.
- Nothing crashed in 4 of its last 84 played games, including vs CodexExplorer the same day (5054735). Citadel's other "win by crash" since the upload (5055959) was Creepy_macro's crash.
- `ladder_watch.py` already counts only *losses* by crash or timeout as Citadel failures, so this game was never counted against Citadel.

## Citadel's ladder record since the M7 upload (match ≥ 5051000)

71 finished games: 32 wins and 34 losses by the game rules, 1 tie, 2 wins by opponent crash, **1 loss by TimeOut (this one)**, 1 not played (dantalion's timeout before a result). 16 more were waiting to be played.

## What went well

- The M6 notes on the controller's rules (VERIFY_NOTES "M6 findings") made the timer's meaning quick to confirm.
- Citadel's step warnings and 30 s snapshots showed its pace and step times right up to the stall, which rules out a slow build-up on its side.
- The error guard and telemetry did their job in the crash match: clean record, memory saved.

## What went poorly

- **Citadel's log can't say where its process was during a stall.** Only `on_step` is timed (`bot/main.py:164-267`, `_check_step_time` at `:286`). The event hooks, ares's after-step and python-sc2's own work are not.
- **No end-of-game record.** The connection closed before `on_end`, so `games.jsonl` and the opponent memory miss this game (as with the 60:00 tie vs zergid0).
- **`ladder_watch.py` doesn't fetch the arena client log or classify failures**, so telling "Citadel hung", "the opponent hung" and "both stopped" apart took manual work. The presigned S3 links for the arena client log and replay also return HTTP 400 if they're fetched with the API token header attached. They work without it.
- **The platform's double-timeout rule assigns the loss by seat order.**

## Revision plan

None of these changes would have saved this game. They make the next one diagnosable and keep the record straight. Every new TUNE value goes in `bot/constants.py`. Every new API is checked in its source and recorded in `docs/VERIFY_NOTES.md` before use (marked **VERIFY**).

### Decisions

| # | Question | Recommendation |
|---|---|---|
| D1 | Report to AI Arena: ask them to review match 5054944, and suggest that a double timeout (both seats within a few seconds, no `Sc2Timeout`) be scored `Error` (no Elo change), as an SC2 crash already is | Yes. You post it (Discord or an issue on `aiarena/sc2-ai-match-controller`); draft below. I don't post anything |
| D2 | Approve a small spec change to §6 "Measure" and §8: time the whole step loop (not only `on_step`), add a stall watchdog, record peak memory (Phase B) | Yes |
| D3 | Milestone label for this work (the spec has none after M7) | "M8: ladder diagnostics" (small; Phases A and B) |
| D4 | Upload timing. Phase B changes bot code, so a new upload restarts the 20-game no-failure count | Ship B together with the next gameplay upload. If none is planned within about a week, upload B alone |

### Phase A: ladder tooling and notes (no bot change, no upload)

- **A1 `scripts/ladder_watch.py`:**
  - Also download the arena client log (`results/?match=<id>` → `arenaclient_log`, fetched *without* the token header) next to the match log in `ladder_logs/`.
  - Classify each crash or timeout from the controller log: **Citadel**, **opponent**, **both seats at once (platform)**, or **SC2**. Count `BotTimeout` per seat and their spacing, and look for `Sc2Timeout` and `BotUnexpectedMessage`. Citadel's seat is its participant number: player 1 is seat 10001, the websocket that logs `Game created successfully`.
  - Add `--match N` to inspect one match.
  - Keep counting only Citadel-caused failures against the acceptance line, but print platform ones so they're never silent.
- **A2 offline test** `scripts/test_ladder_watch.py`: the classifier on short controller-log snippets for each case above (taken from 5054944, 5055364, 5051673 and 5054762).
- **A3 docs:** VERIFY_NOTES gets the double-timeout rule (`game_result.rs:90-96`), the signature table above, and the S3/token-header finding. STATUS "Known issues" links this postmortem.
- **Acceptance:** `poetry run python scripts/ladder_watch.py --match 5054944` prints "both seats timed out (platform)"; `--match 5055364` prints "opponent crashed"; `--match 5051673` prints "opponent timed out". The offline test passes.

### Phase B: stall diagnostics in the bot (spec change D2; needs an upload)

- **B1 gap timer.** Time the wall-clock gap from the end of one `on_step` to the start of the next. Warn when it's over `STEP_GAP_WARN_MS` (TUNE, start at 2,000), with the game time and loop. Record `gap_max` and `gaps_over` in the game record's `step_ms`. This covers everything `on_step`'s timer misses: python-sc2's work, the event hooks, ares's after-step, and waits on SC2 or the opponent. Each gap is measured when the next step starts, so it only shows a stall that ends. B2 covers one that doesn't.
- **B2 stall watchdog.** Python's built-in `faulthandler.dump_traceback_later` (standard library, no new dependency) runs a C watchdog thread that writes every thread's stack to stderr (it lands in the match log zip). Re-arm it from `on_step` about once a second, so it fires only after `WATCHDOG_S` (TUNE, 20 s, under the arena's 30 s) with no step. The stack shows whether Citadel's process was in its own code (a Citadel bug, with the exact line) or waiting on the connection (not Citadel). Cancel it in `on_end`. **VERIFY** in CPython 3.12's `faulthandler`: re-arming cancels the previous timer, the per-call cost (it starts a thread), and that it can dump while the main thread holds the GIL in C code.
- **B3 peak memory.** Peak resident memory (`resource.getrusage(RUSAGE_SELF).ru_maxrss`, standard library, KB on Linux) in the 30 s snapshot and the game record, so a future stall can be checked against Citadel's own memory use. **VERIFY** the units on the ladder image (Debian 12).
- **B4** Game record version 8; `scripts/check_game_log.py` accepts the new fields.
- **Acceptance:**
  - A dev-only test (`scripts/test_stall_watch.py`, the `external_tags`/`InjectedError` pattern) injects a 25 s pause in three places: inside `on_step`, in an event hook, and in `_after_step`. Each time the watchdog stack names the paused function and a GAP line reports about 25 s. A 5 s pause gives a GAP line and no stack.
  - Step-time mean within 0.1 ms of the M7 batches (`--game-seed` A/B on the same games).
  - Pre-upload checks as for M7: error guard 15/15, M5 7/7, the ladder-environment test (10 matches), zip on Python 3.12, `unzip -l publish/*.zip | head`.
  - After upload: 20 ladder games with no Citadel-caused crash or timeout.
  - Needs SC2 4.10 installed here (README, about 4 GB) or the Windows desktop.

### Phase C: platform report (D1, you post)

Draft:

> Match 5054944 (Citadel vs Voltron, arena client 504) was scored Player1TimeOut, but both seats logged `BotTimeout(30s)` 45 ms apart (17:41:43.862 and .907) and neither logged `Sc2Timeout`. The replay shows both bots issuing commands every 2 loops up to loop 9,471, then nothing. That looks like the machine stalled both bots at once. `game_result.rs:95` resolves a double timeout as Player1TimeOut whatever the order. Could double timeouts within a few seconds be scored as Error (no Elo change), like SC2Crash? And could this match be reviewed?

### Not planned

- No gameplay change: the game was normal up to the stall.
- No change to how Citadel logs or writes files (we have no evidence that Citadel's own I/O was involved).
