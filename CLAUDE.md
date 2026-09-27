# Citadel

Protoss StarCraft II bot for the AI Arena ladder, built on the ares-sc2 bot template (ares is the `ares-sc2` git submodule). The spec is `docs/DESIGN.md` and it is the source of truth. Read only the sections the current task needs.

# Commands
- Run a local game: `poetry run python run.py`
- Build the ladder zip: `poetry run python scripts/create_ladder_zip.py`
- Check the zip: `unzip -l publish/*.zip | head` (`run.py` must be at the top level, not inside a folder)

# Environment
- SC2 is at `~/StarCraftII` (found via `SC2PATH`). Maps are in `~/StarCraftII/Maps`; the folder name is case-sensitive.
- Local games always use `realtime=False`.

# Rules
- IMPORTANT: anything marked VERIFY in the spec must be confirmed in the ares or python-sc2 source before use. Record findings in `docs/VERIFY_NOTES.md`. Never guess an API name or signature.
- Store unit tags across steps, never `Unit` objects.
- Don't hard-code unit stats or balance numbers; read game data at runtime. The AIE maps carry newer balance data than the 4.10 engine.
- Every TUNE value and threshold lives in `bot/constants.py`.
- Don't edit the `ares-sc2` submodule.
- Bot code makes no network calls, writes only under `./data`, and adds no dependencies beyond the template's without asking me.

# Workflow
- Work on one milestone (spec §7) at a time. Finish by showing evidence for each acceptance criterion (the command you ran and its output), then stop.
- If the spec is ambiguous or contradicts itself, stop and ask me. Don't pick silently.
- Commit after each working step with a descriptive message.
- When compacting, keep the current milestone number, the files changed so far, and the test commands.