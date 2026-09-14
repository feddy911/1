"""Проверка связности карт: двери должны быть достижимы с обеих сторон."""
from pathlib import Path

ROOT = Path(r"C:\Games\ДуркаРПГ\data\maps")
WALK = set(".SsE*+@")
DOOR = set("Dd")


def load(name):
    lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
    w = max(len(r) for r in lines)
    grid = [list(r.ljust(w)) for r in lines]
    return grid


def neighbors(x, y):
    return ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))


def flood(grid, walk_extra=()):
    h, w = len(grid), len(grid[0])
    allowed = WALK | set(walk_extra)
    starts = []
    for y, row in enumerate(grid):
        for x, ch in enumerate(row):
            if ch in ("@", "S", "s", "E") or (ch == "." and not starts):
                starts.append((x, y))
    # Prefer @ then stairs
    ordered = [p for p in starts if grid[p[1]][p[0]] == "@"]
    ordered += [p for p in starts if grid[p[1]][p[0]] in "SsE"]
    if not ordered:
        ordered = starts[:1]
    seen = set()
    stack = list(ordered[:1])
    while stack:
        x, y = stack.pop()
        if (x, y) in seen:
            continue
        if not (0 <= y < h and 0 <= x < w):
            continue
        ch = grid[y][x]
        if ch not in allowed and (x, y) not in ordered[:1]:
            continue
        seen.add((x, y))
        for nx, ny in neighbors(x, y):
            if 0 <= ny < h and 0 <= nx < w and (nx, ny) not in seen:
                nch = grid[ny][nx]
                if nch in allowed or nch in DOOR:
                    stack.append((nx, ny))
    return seen


def analyze(name):
    grid = load(name)
    h, w = len(grid), len(grid[0])
    print(f"\n=== {name} {w}x{h} ===")
    widths = {len(r) for r in grid}
    if len(widths) != 1:
        print(f"  UNEVEN WIDTHS { {len(''.join(r).rstrip()) for r in grid} }")
    reach = flood(grid, walk_extra=DOOR)
    doors = []
    for y, row in enumerate(grid):
        for x, ch in enumerate(row):
            if ch in DOOR:
                doors.append((x, y, ch))
    for x, y, ch in doors:
        sides = []
        for nx, ny in neighbors(x, y):
            if 0 <= ny < h and 0 <= nx < w:
                nch = grid[ny][nx]
                if nch in WALK:
                    sides.append((nx, ny, nch))
        reachable_door = (x, y) in reach
        walk_reach = [s for s in sides if (s[0], s[1]) in reach]
        print(
            f"  door {ch} ({x},{y}) sides={len(sides)} "
            f"reachable={reachable_door} walk_from_start={len(walk_reach)} {sides}"
        )
        if len(sides) < 2:
            print("    PROBLEM: door does not connect two walkable cells")
        if not walk_reach:
            print("    PROBLEM: cannot reach this door from start/stairs")


if __name__ == "__main__":
    for name in ("floor_1.txt", "floor_2.txt", "basement.txt", "street.txt"):
        analyze(name)
