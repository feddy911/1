"""Маленькая карта схватки, как сцена JRPG. Шаг по ней не ходят.

Не analog. Кость и 1–2–3 те же. Карты — .txt в data/maps/battle, не клиника.
"""
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
BATTLE_DIR = ROOT / "data" / "maps" / "battle"
MARKERS = frozenset("@&12")

_KIND_BY_MAP = (
    ("basement", "cellar"),
    ("street", "yard"),
    ("traktir", "yard"),
    ("tenement", "hall"),
)


def pick_kind(map_id: str) -> str:
    mid = map_id or ""
    for needle, kind in _KIND_BY_MAP:
        if needle in mid:
            return kind
    return "ward"


def load_stage(kind: str) -> Tuple[List[List[str]], Dict[str, Tuple[int, int]]]:
    path = BATTLE_DIR / f"{kind}.txt"
    if not path.is_file():
        path = BATTLE_DIR / "ward.txt"
    rows = [list(line.rstrip("\n")) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        rows = [list("######"), list("#.@&.#"), list("######")]
    width = max(len(row) for row in rows)
    tiles = [row + ["#"] * (width - len(row)) for row in rows]
    spots: Dict[str, Tuple[int, int]] = {}
    for y, row in enumerate(tiles):
        for x, char in enumerate(row):
            if char in MARKERS:
                spots[char] = (x, y)
                row[x] = "."
    return tiles, spots


def stage_kind_for(engine) -> str:
    stored = getattr(engine, "battle_kind", None) or ""
    if stored and (BATTLE_DIR / f"{stored}.txt").is_file():
        return stored
    return pick_kind(getattr(engine, "current_map_id", "") or "")
