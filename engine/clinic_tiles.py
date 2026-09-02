"""Спрайты на глифы легенды: маска 16×24.

Белая маска + альфа. tcod красит клетку чернилами палитры, как букву.
Карты .txt не трогаем. F4 возвращает буквы DejaVu.
"""
from typing import Dict, List

import numpy as np

from engine.constants import TILE_LEGEND

TILE_WIDTH = 16
TILE_HEIGHT = 24
PROTO_CHARS = "".join(symbol for symbol, _short, _long in TILE_LEGEND)
SPRITE_ALIASES = {"~": "≈", ")": "!"}


def sprite_chars() -> str:
    return PROTO_CHARS + "".join(SPRITE_ALIASES)


def _blank() -> np.ndarray:
    return np.zeros((TILE_HEIGHT, TILE_WIDTH, 4), dtype=np.uint8)


def _stamp(tile: np.ndarray, x: int, y: int, alpha: int) -> None:
    if 0 <= x < TILE_WIDTH and 0 <= y < TILE_HEIGHT and alpha > 0:
        tile[y, x] = (255, 255, 255, int(alpha))


def _from_rows(rows: List[str], ink: Dict[str, int]) -> np.ndarray:
    if len(rows) != TILE_HEIGHT:
        raise ValueError(f"нужно {TILE_HEIGHT} строк, пришло {len(rows)}")
    tile = _blank()
    for y, row in enumerate(rows):
        if len(row) != TILE_WIDTH:
            raise ValueError(f"строка {y} длины {len(row)}, нужно {TILE_WIDTH}: {row!r}")
        for x, ch in enumerate(row):
            _stamp(tile, x, y, ink.get(ch, 0))
    return tile


def _art(ink: Dict[str, int], *rows: str) -> np.ndarray:
    lines = []
    for row in rows:
        if len(row) > TILE_WIDTH:
            raise ValueError(f"строка длиннее {TILE_WIDTH}: {row!r}")
        lines.append(row.ljust(TILE_WIDTH))
    if len(lines) > TILE_HEIGHT:
        raise ValueError(f"нужно {TILE_HEIGHT} строк, пришло {len(lines)}")
    while len(lines) < TILE_HEIGHT:
        lines.append(" " * TILE_WIDTH)
    return _from_rows(lines, ink)


def _wall() -> np.ndarray:
    """Штукатурка с перевязью кирпича. Плотнее пола, чтобы fg читался."""
    tile = _blank()
    brick_h, brick_w = 4, 8
    for y in range(TILE_HEIGHT):
        band = y // brick_h
        shift = (band % 2) * (brick_w // 2)
        for x in range(TILE_WIDTH):
            local = (x + shift) % brick_w
            mortar = (y % brick_h == brick_h - 1) or local == brick_w - 1
            _stamp(tile, x, y, 70 if mortar else 215)
    for x, y in ((3, 2), (12, 6), (7, 11), (1, 17), (14, 20), (9, 14)):
        _stamp(tile, x, y, 35)
    return tile


def _floor() -> np.ndarray:
    """Редкие доски: фон-смоль должен остаться темнее стены."""
    tile = _blank()
    for y in range(TILE_HEIGHT):
        if y % 8 == 7:
            for x in range(TILE_WIDTH):
                _stamp(tile, x, y, 52)
        elif y % 8 == 3:
            _stamp(tile, 5, y, 36)
            _stamp(tile, 6, y, 36)
    for x, y in ((2, 4), (11, 9), (8, 16), (13, 21), (4, 12)):
        _stamp(tile, x, y, 64)
    return tile


def _door() -> np.ndarray:
    """Филёнка и ручка. Порог снизу."""
    return _art(
        {"#": 230, ".": 90, "o": 255, "t": 160},
        "                ",
        " ############## ",
        " #............# ",
        " #..##....##..# ",
        " #..##....##..# ",
        " #............# ",
        " #............# ",
        " #..##....##..# ",
        " #..##....##..# ",
        " #............# ",
        " #..........o.# ",
        " #..........oo# ",
        " #............# ",
        " #..##....##..# ",
        " #..##....##..# ",
        " #............# ",
        " #............# ",
        " #..##....##..# ",
        " #..##....##..# ",
        " #............# ",
        " ############## ",
        " tttttttttttttt ",
        " tttttttttttttt ",
        "                ",
    )


def _locked_door() -> np.ndarray:
    """Та же филёнка, замок вместо ручки."""
    return _art(
        {"#": 230, ".": 90, "o": 255, "t": 160, "+": 200},
        "                ",
        " ############## ",
        " #............# ",
        " #..##....##..# ",
        " #..##....##..# ",
        " #............# ",
        " #............# ",
        " #..##....##..# ",
        " #..##....##..# ",
        " #............# ",
        " #....++++....# ",
        " #....+oo+....# ",
        " #....++++....# ",
        " #..##....##..# ",
        " #..##....##..# ",
        " #............# ",
        " #............# ",
        " #..##....##..# ",
        " #..##....##..# ",
        " #............# ",
        " ############## ",
        " tttttttttttttt ",
        " tttttttttttttt ",
        "                ",
    )


def _open_door() -> np.ndarray:
    """Створка у косяка, порог на всю клетку."""
    return _art(
        {"#": 230, ".": 110, "o": 200, "t": 160},
        "                ",
        " ##o            ",
        " #.#o           ",
        " #.# o          ",
        " #.#  o         ",
        " #.#   o        ",
        " #.#    o       ",
        " #.#     o      ",
        " #.#      o     ",
        " #o#       o    ",
        " #.#        o   ",
        " #.#         o  ",
        " #.#          o ",
        " #.#            ",
        " #.#            ",
        " #.#            ",
        " #.#            ",
        " #.#            ",
        " #.#            ",
        " ##o            ",
        " ############## ",
        " tttttttttttttt ",
        " tttttttttttttt ",
        "                ",
    )


def _lamp() -> np.ndarray:
    """Плафон, ножка, пламя. Мерцание по-прежнему красит fg."""
    return _art(
        {"#": 200, ".": 110, "|": 170, "*": 230, "+": 255},
        "                ",
        "     ######     ",
        "    #......#    ",
        "     ######     ",
        "       ||       ",
        "       ||       ",
        "      ****      ",
        "     ******     ",
        "    ********    ",
        "    ***++***    ",
        "     **++**     ",
        "      ****      ",
        "       **       ",
        "       ++       ",
    )


def _player() -> np.ndarray:
    """Халат в клетке 16×24. Лицо — прорези, не портрет."""
    return _art(
        {"#": 235, ".": 40},
        "                ",
        "      ####      ",
        "     ######     ",
        "     ##..##     ",
        "     ######     ",
        "      ####      ",
        "       ##       ",
        "     ######     ",
        "    ########    ",
        "    ###  ###    ",
        "    ########    ",
        "    ########    ",
        "    ###  ###    ",
        "    ########    ",
        "     ######     ",
        "     ######     ",
        "      #  #      ",
        "      #  #      ",
        "      #  #      ",
        "     ##  ##     ",
        "     #    #     ",
        "     #    #     ",
    )


def _person() -> np.ndarray:
    """Пальто и поля шляпы. Не халат @."""
    return _art(
        {"#": 235, ".": 50, "o": 180},
        "                ",
        "    ########    ",
        "      ####      ",
        "     ######     ",
        "     #....#     ",
        "     ######     ",
        "      ####      ",
        "    o######o    ",
        "   ##########   ",
        "   ##########   ",
        "   ####  ####   ",
        "   ##########   ",
        "   ##########   ",
        "    ########    ",
        "    ########    ",
        "    ########    ",
        "     ######     ",
        "     ##  ##     ",
        "     ##  ##     ",
        "     ##  ##     ",
        "     #    #     ",
        "     #    #     ",
    )


def _bed() -> np.ndarray:
    """Изголовье, подушка, матрас, ножки."""
    return _art(
        {"#": 220, ".": 100, "o": 240, "+": 160},
        "                ",
        " ############## ",
        " #++++++++++++# ",
        " #oooooooooooo# ",
        " #oooooooooooo# ",
        " ############## ",
        " #............# ",
        " #............# ",
        " #............# ",
        " #............# ",
        " #............# ",
        " #............# ",
        " #............# ",
        " #............# ",
        " #............# ",
        " #............# ",
        " #............# ",
        " ############## ",
        " ##          ## ",
        " ##          ## ",
        " ##          ## ",
        " ++          ++ ",
    )


def _table() -> np.ndarray:
    """Столешница и четыре ноги."""
    return _art(
        {"#": 220, ".": 90, "+": 170},
        "                ",
        "                ",
        " ############## ",
        " #............# ",
        " ############## ",
        "  #          #  ",
        "  #          #  ",
        "  #          #  ",
        "  #          #  ",
        "  #          #  ",
        "  #          #  ",
        "  #          #  ",
        " ++          ++ ",
        "                ",
        "                ",
        "                ",
        "                ",
        "                ",
        "                ",
        "                ",
        "                ",
        "                ",
        "                ",
        "                ",
    )


def _chair() -> np.ndarray:
    """Спинка, сиденье, ноги. Уже стола."""
    return _art(
        {"#": 220, ".": 90, "+": 170},
        "                ",
        "    ########    ",
        "    #......#    ",
        "    #.####.#    ",
        "    #......#    ",
        "    #.####.#    ",
        "    #......#    ",
        "    ########    ",
        "   ##########   ",
        "   #........#   ",
        "   ##########   ",
        "    #      #    ",
        "    #      #    ",
        "    #      #    ",
        "   ++      ++   ",
    )


def _cabinet() -> np.ndarray:
    """Двустворчатый шкаф на всю клетку."""
    return _art(
        {"#": 220, ".": 85, "o": 240, "+": 160},
        " ############## ",
        " #............# ",
        " #....##......# ",
        " #....##......# ",
        " #....##......# ",
        " #....##......# ",
        " #....##....o.# ",
        " #............# ",
        " ############## ",
        " #............# ",
        " #....##......# ",
        " #....##......# ",
        " #....##......# ",
        " #....##....o.# ",
        " #............# ",
        " ############## ",
        " #++++++++++++# ",
        " ############## ",
        " ##          ## ",
        " ++          ++ ",
    )


def _desk() -> np.ndarray:
    """Бюро: столешница, бумаги, чернильница, ящики."""
    return _art(
        {"#": 220, ".": 90, "o": 230, "*": 255, "+": 160},
        "                ",
        " ############## ",
        " #oooo.....*..# ",
        " #oooo........# ",
        " ############## ",
        " #....##......# ",
        " #....##....o.# ",
        " #............# ",
        " ############## ",
        " #....##......# ",
        " #....##....o.# ",
        " #............# ",
        " ############## ",
        "  #          #  ",
        "  #          #  ",
        " ++          ++ ",
    )


def _window() -> np.ndarray:
    """Рама, четыре стекла, подоконник."""
    return _art(
        {"#": 230, ".": 70, "o": 40, "t": 180},
        "                ",
        "################",
        "#......##......#",
        "#.oooo.##.oooo.#",
        "#.oooo.##.oooo.#",
        "#......##......#",
        "################",
        "#......##......#",
        "#.oooo.##.oooo.#",
        "#.oooo.##.oooo.#",
        "#......##......#",
        "################",
        "  tttttttttttt  ",
        "  tttttttttttt  ",
        "                ",
        "                ",
        "                ",
        "                ",
        "                ",
        "                ",
        "                ",
        "                ",
        "                ",
        "                ",
    )


def _stairs_up() -> np.ndarray:
    """Ступени вверх-вправо."""
    return _art(
        {"#": 220, ".": 80, "+": 160},
        "                ",
        "            ####",
        "            #..#",
        "            #..#",
        "        #######+",
        "        #......#",
        "        #......#",
        "    ###########+",
        "    #..........#",
        "    #..........#",
        " ##############+",
        " #.............#",
        " #.............#",
        "################",
        "++++++++++++++++",
    )


def _stairs_down() -> np.ndarray:
    """Ступени вниз-вправо, проём сверху."""
    return _art(
        {"#": 200, ".": 70, "+": 140, "o": 40},
        "                ",
        "oooooooooooooooo",
        "################",
        "#..............#",
        "#..............#",
        "+############## ",
        " #............# ",
        " #............# ",
        " +###########   ",
        "  #........#    ",
        "  #........#    ",
        "   +#######     ",
        "    #....#      ",
        "    #....#      ",
        "     ####       ",
        "     ++++       ",
    )


def _exit() -> np.ndarray:
    """Арка выхода, свет в проёме."""
    return _art(
        {"#": 220, ".": 50, "o": 110, "t": 170},
        "                ",
        "   ##########   ",
        "  ##oooooooo##  ",
        " ##oooooooooo## ",
        " #oooooooooooo# ",
        " #ooo......ooo# ",
        " #oo........oo# ",
        " #oo........oo# ",
        " #oo........oo# ",
        " #oo........oo# ",
        " #oo........oo# ",
        " #oo........oo# ",
        " #oo........oo# ",
        " #oo........oo# ",
        " #oo........oo# ",
        " #oo........oo# ",
        " ##oooooooooo## ",
        "  ############  ",
        " tttttttttttttt ",
        " tttttttttttttt ",
    )


def _item() -> np.ndarray:
    """Флакон на полу."""
    return _art(
        {"#": 220, ".": 100, "o": 240, "+": 160},
        "                ",
        "                ",
        "                ",
        "       ##       ",
        "      #oo#      ",
        "      ####      ",
        "     #....#     ",
        "     #.oo.#     ",
        "     #.oo.#     ",
        "     #....#     ",
        "     ######     ",
        "      ++++      ",
    )


def _note() -> np.ndarray:
    """Сложенный лист, строки чернил."""
    return _art(
        {"#": 220, ".": 90, "o": 200, "+": 140},
        "                ",
        "                ",
        "                ",
        "   ##########   ",
        "  #..........#  ",
        "  #.oooooo...#  ",
        "  #..........#  ",
        "  #.oooooo...#  ",
        "  #..........#  ",
        "  #.oooo.....#  ",
        "  #..........#+ ",
        "   ########## + ",
        "            ++  ",
    )


def _canal() -> np.ndarray:
    """Рябь, не штукатурка. Реже стены, чтобы вода читалась как проём."""
    tile = _blank()
    for y in range(TILE_HEIGHT):
        phase = y % 5
        if phase == 1:
            for x in range(TILE_WIDTH):
                _stamp(tile, x, y, 88 if (x + y // 5) % 4 else 54)
        elif phase == 3:
            for x in range(1, TILE_WIDTH - 1):
                _stamp(tile, x, y, 40 if x % 3 else 62)
    for x, y in ((3, 8), (10, 13), (6, 18), (13, 4)):
        _stamp(tile, x, y, 96)
    return tile


_PAINTERS = {
    "#": _wall,
    ".": _floor,
    "D": _door,
    "d": _locked_door,
    "'": _open_door,
    "*": _lamp,
    "@": _player,
    "&": _person,
    "B": _bed,
    "T": _table,
    "C": _chair,
    "H": _cabinet,
    "O": _desk,
    "W": _window,
    "S": _stairs_up,
    "s": _stairs_down,
    "E": _exit,
    "!": _item,
    "≈": _note,
    "=": _canal,
}


def paint_proto_tile(char: str) -> np.ndarray:
    src = SPRITE_ALIASES.get(char, char)
    painter = _PAINTERS.get(src)
    if painter is None:
        return _blank()
    return painter()


def stamp_proto_tiles(tileset) -> None:
    """Положить маски в те же codepoint. Остальной шрифт не трогаем."""
    if tileset.tile_width != TILE_WIDTH or tileset.tile_height != TILE_HEIGHT:
        return
    for char in sprite_chars():
        tileset[ord(char)] = paint_proto_tile(char)


def tile_alpha_sum(tile: np.ndarray) -> int:
    if tile is None or tile.size == 0:
        return 0
    return int(tile[:, :, 3].sum())
