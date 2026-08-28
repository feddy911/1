"""Этаж бреда: каркас 1-го этажа, мебель и пятна — по семени партии."""
import random
from collections import deque
from pathlib import Path
from typing import List

from engine.constants import WALKABLE_TILES

FURNITURE = "BTCHO"
PROTECTED = set("#DdSsE@W")
CORRIDOR_Y = range(8, 12)


def _load(path: Path) -> List[List[str]]:
    rows = path.read_text(encoding="utf-8").splitlines()
    width = max(len(row) for row in rows)
    return [list(row.ljust(width)) for row in rows]


def _flood(grid: List[List[str]], start) -> set:
    height, width = len(grid), len(grid[0])
    allow = set(WALKABLE_TILES) | {"D", "@"}
    seen = {start}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if (nx, ny) in seen:
                continue
            if grid[ny][nx] not in allow:
                continue
            seen.add((nx, ny))
            queue.append((nx, ny))
    return seen


def _doors_ok(grid: List[List[str]], reachable: set) -> bool:
    height, width = len(grid), len(grid[0])
    for y, row in enumerate(grid):
        for x, tile in enumerate(row):
            if tile not in {"D", "d", "S", "s", "E"}:
                continue
            neighbors = ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
            if not any(pos in reachable for pos in neighbors) and (x, y) not in reachable:
                return False
    return True


def generate_bred_floor(floor1_path: Path, seed: int) -> List[List[str]]:
    """Скопировать геометрию 1-го этажа и сдвинуть только мебель и пятна."""
    base = _load(floor1_path)
    for y, row in enumerate(base):
        for x, tile in enumerate(row):
            if tile == "@":
                row[x] = "."

    rng = random.Random(seed)
    candidate = [row[:] for row in base]
    height, width = len(candidate), len(candidate[0])

    for y in range(height):
        if y in CORRIDOR_Y:
            continue
        for x in range(width):
            tile = candidate[y][x]
            if tile in FURNITURE and rng.random() < 0.5:
                candidate[y][x] = rng.choice(FURNITURE)
            elif (
                tile == "."
                and y not in (0, height - 1)
                and x not in (0, width - 1)
                and rng.random() < 0.04
            ):
                candidate[y][x] = rng.choice(["*", "="])

    start = (46, 15)
    if candidate[start[1]][start[0]] not in (set(WALKABLE_TILES) | {"D"}):
        return base
    reachable = _flood(candidate, start)
    if _doors_ok(candidate, reachable):
        return candidate
    return base
