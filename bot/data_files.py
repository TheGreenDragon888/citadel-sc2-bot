"""Citadel's file access under ./data (DESIGN.md §2: write only to ./data, keep it under 5 MB).

Every file Citadel writes goes through `write_text`, which refuses a path outside DATA_DIR and
writes atomically (a temporary file in the same folder, then `os.replace`), so a game killed in
the middle of a write leaves the previous file whole. DATA_DIR is relative to the working
directory, as ares's own `./data` is (`ares.consts.DATA_DIR`); on the ladder that is the bot's
folder, which AI Arena saves and restores when "bot data enabled" is on.
"""

import os
from pathlib import Path
from typing import Optional

from bot.constants import DATA_DIR


def data_root() -> Path:
    return Path(DATA_DIR).resolve()


def data_path(*parts: str) -> Path:
    """A path inside ./data; ValueError if `parts` would leave it."""
    root = data_root()
    path = root.joinpath(*parts).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"{path} is outside {root}")
    return path


def write_text(path: Path, text: str) -> None:
    root = data_root()
    path = path.resolve()
    if root not in path.parents:
        raise ValueError(f"refusing to write {path}: outside {root}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def data_size(exclude: Optional[Path] = None) -> int:
    """Total bytes of the files under ./data (`exclude` left out)."""
    root = data_root()
    total = 0
    if not root.exists():
        return 0
    skip = exclude.resolve() if exclude is not None else None
    for folder, _, files in os.walk(root):
        for name in files:
            p = Path(folder) / name
            if skip is not None and p.resolve() == skip:
                continue
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total
