"""Сборка авторских карт 2 этажа, подвала и улицы."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data" / "maps"


def new_grid(width: int, height: int, fill: str = ".") -> list:
    grid = [[fill for _ in range(width)] for _ in range(height)]
    for x in range(width):
        grid[0][x] = "#"
        grid[height - 1][x] = "#"
    for y in range(height):
        grid[y][0] = "#"
        grid[y][width - 1] = "#"
    return grid


def stamp(grid, x, y, ch):
    grid[y][x] = ch


def hwall(grid, y, x1, x2):
    for x in range(x1, x2 + 1):
        grid[y][x] = "#"


def vwall(grid, x, y1, y2):
    for y in range(y1, y2 + 1):
        grid[y][x] = "#"


def windows_top_bottom(grid, width, positions):
    for x in positions:
        if 0 < x < width - 1:
            grid[0][x] = "W"
            grid[len(grid) - 1][x] = "W"


def write(name, grid):
    width = len(grid[0])
    for y, row in enumerate(grid):
        if len(row) != width:
            raise ValueError(f"{name} row {y} width {len(row)} != {width}")
    text = "\n".join("".join(row) for row in grid) + "\n"
    path = ROOT / name
    path.write_text(text, encoding="utf-8")
    print(f"{name}: {width}x{len(grid)}")


def build_floor_2():
    w, h = 57, 20
    g = new_grid(w, h)
    # Карниз окон, как на 1 этаже
    for x in range(w):
        if g[0][x] == "#":
            pass
    line0 = list("###WWW#####WWW#####WWW#####WWW#####WWW#####WWW#####WWW###")
    g[0] = line0
    g[h - 1] = list("###WWW#####WWW#####WWW#####WWW#####WWW#####WWW#####WWW###")

    # Три архивных комнаты сверху
    vwall(g, 8, 1, 6)
    vwall(g, 16, 1, 6)
    vwall(g, 24, 1, 6)
    vwall(g, 40, 1, 6)
    hwall(g, 7, 0, 56)
    stamp(g, 4, 7, "D")
    stamp(g, 12, 7, "D")
    stamp(g, 20, 7, "D")
    stamp(g, 48, 7, "D")

    for y in range(1, 6):
        stamp(g, 2, y, "H")
        stamp(g, 6, y, "H")
    stamp(g, 11, 2, "T")
    stamp(g, 19, 2, "T")
    stamp(g, 19, 3, "T")
    stamp(g, 44, 2, "O")
    stamp(g, 48, 2, "C")
    stamp(g, 46, 4, "T")
    stamp(g, 47, 4, "T")
    stamp(g, 48, 4, "T")

    # Коридор
    stamp(g, 0, 9, "W")
    stamp(g, 0, 10, "W")
    stamp(g, 56, 9, "W")
    stamp(g, 56, 10, "W")
    stamp(g, 12, 9, "*")
    stamp(g, 36, 9, "*")

    hwall(g, 12, 0, 56)
    stamp(g, 8, 12, "d")  # личный кабинет главврача
    stamp(g, 28, 12, "D")
    stamp(g, 48, 12, "D")

    # Кабинет слева
    vwall(g, 16, 13, 18)
    stamp(g, 1, 13, "H")
    stamp(g, 1, 14, "H")
    stamp(g, 1, 15, "H")
    stamp(g, 1, 16, "H")
    stamp(g, 1, 17, "H")
    stamp(g, 1, 18, "H")
    stamp(g, 15, 13, "O")
    stamp(g, 15, 14, "O")
    stamp(g, 15, 15, "O")
    stamp(g, 10, 15, "*")
    stamp(g, 5, 17, "C")

    # Лестница вниз — те же клетки, что в связях БД
    vwall(g, 48, 13, 18)
    for y in range(14, 19):
        for x in range(49, 56):
            g[y][x] = "s"
    stamp(g, 56, 16, "W")
    stamp(g, 56, 17, "W")
    return g


def build_basement():
    w, h = 60, 20
    g = new_grid(w, h)
    # Узкий коридор от лестницы вглубь
    for y in range(1, 19):
        for x in range(1, 59):
            g[y][x] = "#"

    # Главный коридор
    for y in range(8, 13):
        for x in range(21, 51):
            g[y][x] = "."
    stamp(g, 28, 9, "*")
    stamp(g, 42, 11, "*")

    # Камеры слева-сверху
    for y in range(1, 7):
        for x in range(1, 20):
            g[y][x] = "."
    vwall(g, 7, 1, 6)
    vwall(g, 13, 1, 6)
    hwall(g, 6, 1, 20)
    stamp(g, 4, 6, "D")
    stamp(g, 10, 6, "D")
    stamp(g, 17, 6, "D")
    stamp(g, 3, 2, "B")
    stamp(g, 9, 2, "B")
    stamp(g, 16, 2, "B")

    # Лаборатория (заперта)
    for y in range(7, 19):
        for x in range(1, 20):
            g[y][x] = "."
    vwall(g, 20, 7, 18)
    hwall(g, 7, 1, 20)
    stamp(g, 20, 10, "d")
    stamp(g, 4, 9, "T")
    stamp(g, 5, 9, "T")
    stamp(g, 4, 10, "T")
    stamp(g, 12, 14, "O")
    stamp(g, 8, 12, "*")
    stamp(g, 3, 16, "H")
    stamp(g, 3, 17, "H")

    # Лестница вверх и выход из клети в коридор
    for y in range(14, 19):
        for x in range(52, 59):
            g[y][x] = "S"
    for y in range(9, 13):
        for x in range(51, 59):
            if g[y][x] == "#":
                g[y][x] = "."
    vwall(g, 51, 13, 18)
    for x in range(52, 59):
        g[13][x] = "."
    stamp(g, 51, 13, "D")
    return g


def build_street():
    w, h = 60, 20
    g = new_grid(w, h, fill=".")
    # Фасад клиники слева
    for y in range(h):
        g[y][0] = "#"
    stamp(g, 0, 9, "E")
    stamp(g, 0, 10, "E")
    for y in (7, 8, 11, 12):
        stamp(g, 1, y, "#")
    stamp(g, 1, 6, "W")
    stamp(g, 1, 13, "W")

    # Газовые фонари
    stamp(g, 8, 5, "*")
    stamp(g, 22, 4, "*")
    stamp(g, 38, 5, "*")
    stamp(g, 50, 8, "*")

    stamp(g, 14, 12, "C")
    stamp(g, 15, 12, "C")

    # Канал внизу
    for x in range(1, 59):
        g[17][x] = "="
        g[18][x] = "="
    # Набережная
    for x in range(1, 59):
        g[16][x] = "."
    return g


if __name__ == "__main__":
    # Карты авторские. Скрипт только проверяет якоря и не переписывает геометрию.
    f2 = (ROOT / "floor_2.txt").read_text(encoding="utf-8").splitlines()
    b = (ROOT / "basement.txt").read_text(encoding="utf-8").splitlines()
    s = (ROOT / "street.txt").read_text(encoding="utf-8").splitlines()
    f1 = (ROOT / "floor_1.txt").read_text(encoding="utf-8").splitlines()
    assert len(f1) == 20 and all(len(row) == 57 for row in f1)
    assert len(f2) == 20 and all(len(row) == 57 for row in f2)
    assert len(b) == 20 and all(len(row) == 60 for row in b)
    assert f1[12][8] == "d" and f1[9][56] == "E"
    assert f2[15][55] == "s", f2[15][55]
    assert f2[12][8] == "d"
    assert b[16][55] == "S", b[16][55]
    assert b[10][20] == "d"
    assert b[10][10] == "."
    assert b[7][3] == "." and b[6][3] == "D", "дверь камеры должна открываться в коридор"
    assert s[9][0] == "E"
    assert s[9][1] == "."
    assert s[6][26] == "E" and s[7][26] == "."
    t = (ROOT / "traktir.txt").read_text(encoding="utf-8").splitlines()
    assert len(t) == 14 and all(len(row) == 36 for row in t)
    assert t[7][0] == "E"
    print("anchors OK (maps not overwritten)")
