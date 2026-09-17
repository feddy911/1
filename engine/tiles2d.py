"""Пиксель вида 2D: Streets of Rogue / Wizard of Legend, не HD-2D.

Сверху, лёгкая изометрия: крышка и южная грань, тень на юго-восток.
Квадрат 32×32, масштаб ×2. Человек — чиби с обводкой. Свет ровный,
градиент от лампы и окна. Только palette.INKS. Не analog, не миникарта.
"""
import math
from typing import Iterable, Optional, Tuple

import numpy as np

from engine.palette import INKS, hex_to_rgb

TILE2D = 32
SCALE = 2
CELL = TILE2D * SCALE

INK = {name: hex_to_rgb(hex_v) for name, hex_v in INKS.items()}
VOID_RGB = np.asarray(INK["void"], dtype=np.uint8)
VOID_F = np.asarray(INK["void"], dtype=np.float32)


def _blank(fill: str = "soot") -> np.ndarray:
    tile = np.empty((TILE2D, TILE2D, 3), dtype=np.uint8)
    tile[:] = INK[fill]
    return tile


def _put(tile: np.ndarray, x: int, y: int, name: str) -> None:
    if 0 <= x < TILE2D and 0 <= y < TILE2D:
        tile[y, x] = INK[name]


def _mix_px(tile: np.ndarray, x: int, y: int, name: str, t: float) -> None:
    if not (0 <= x < TILE2D and 0 <= y < TILE2D):
        return
    t = max(0.0, min(1.0, t))
    src = tile[y, x].astype(np.float32)
    tile[y, x] = np.clip(src * (1.0 - t) + np.asarray(INK[name], dtype=np.float32) * t, 0, 255).astype(
        np.uint8
    )


def _rect(tile: np.ndarray, x0: int, y0: int, x1: int, y1: int, name: str) -> None:
    x0, x1 = max(0, x0), min(TILE2D, x1)
    y0, y1 = max(0, y0), min(TILE2D, y1)
    if x1 <= x0 or y1 <= y0:
        return
    tile[y0:y1, x0:x1] = INK[name]


def _oval(tile: np.ndarray, cx: int, cy: int, rx: int, ry: int, name: str) -> None:
    for y in range(cy - ry, cy + ry + 1):
        for x in range(cx - rx, cx + rx + 1):
            if rx <= 0 or ry <= 0:
                continue
            if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0:
                _put(tile, x, y, name)


def dim_tile(rgb: np.ndarray, visible: bool) -> np.ndarray:
    if visible:
        return rgb
    src = rgb.astype(np.float32)
    return (src * 0.32 + VOID_F * 0.68).astype(np.uint8)


def flame_flicker(x: int, y: int, now: float, flames: Optional[Iterable] = None) -> float:
    total = 0.0
    mixed = 0.0
    for item in flames or ():
        if len(item) < 4:
            continue
        sx, sy, radius, intensity = item[:4]
        if radius <= 0:
            continue
        dist = math.hypot(x - sx, y - sy)
        if dist > radius:
            continue
        weight = intensity * (1.0 - dist / radius)
        if weight <= 0:
            continue
        wave = 0.5 + 0.5 * math.sin(now * 3.6 + sx * 0.4)
        mixed += weight * (0.72 + 0.28 * wave)
        total += weight
    if total <= 0:
        return 1.0
    return mixed / total


def light_tint(
    light: float,
    flame: float,
    moon: float,
    visible,
    flicker: float = 1.0,
) -> Tuple[int, int, int]:
    """Множитель RGB 0–255: ровная палата, тёплый градиент лампы, холод окна.
    visible — доля взгляда 0…1, не ступенька клетки."""
    vis = max(0.0, min(1.0, float(visible)))
    mem = (46, 50, 60)
    if vis <= 0.0:
        return mem
    t = min(1.0, max(0.0, light) / 1.15)
    amb = 0.55 + 0.28 * t + 0.16 * min(1.0, max(0.0, flame))
    r = g = b = amb
    flame = max(0.0, flame) * max(0.55, min(1.0, flicker))
    f = min(1.0, flame)
    r += 0.48 * f
    g += 0.22 * f
    b -= 0.20 * f
    m = min(1.0, max(0.0, moon)) * (1.0 - 0.75 * f)
    r -= 0.04 * m
    g += 0.05 * m
    b += 0.26 * m
    lit = (
        int(max(0, min(255, round(r * 255)))),
        int(max(0, min(255, round(g * 255)))),
        int(max(0, min(255, round(b * 255)))),
    )
    if vis >= 1.0:
        return lit
    return (
        int(round(mem[0] + (lit[0] - mem[0]) * vis)),
        int(round(mem[1] + (lit[1] - mem[1]) * vis)),
        int(round(mem[2] + (lit[2] - mem[2]) * vis)),
    )


def apply_light(
    rgb: np.ndarray,
    light: float,
    flame: float,
    moon: float,
    visible: bool,
    flicker: float = 1.0,
) -> np.ndarray:
    """Тот же свет, что карта градиента: ровная база, лампа теплее, окно холоднее."""
    tint = np.asarray(light_tint(light, flame, moon, visible, flicker), dtype=np.float32)
    out = rgb.astype(np.float32) * (tint / 255.0)
    if not visible:
        out = out * 0.55 + VOID_F * 0.45
    return np.clip(out, 0, 255).astype(np.uint8)


def _darken_px(tile: np.ndarray, x: int, y: int, t: float = 0.42) -> None:
    if not (0 <= x < TILE2D and 0 <= y < TILE2D):
        return
    src = tile[y, x].astype(np.float32)
    tile[y, x] = np.clip(src * (1.0 - t) + VOID_F * t, 0, 255).astype(np.uint8)


def _iso_shadow(
    tile: np.ndarray,
    cx: int = 16,
    cy: int = 26,
    rx: int = 10,
    ry: int = 4,
    ox: int = 4,
    oy: int = 3,
) -> None:
    """Тень на юго-восток: пол темнеет, шов камня остаётся."""
    scx, scy = cx + ox, cy + oy
    for y in range(scy - ry - 1, scy + ry + 2):
        for x in range(scx - rx - 1, scx + rx + 2):
            if rx <= 0 or ry <= 0:
                continue
            n = ((x - scx) / rx) ** 2 + ((y - scy) / ry) ** 2
            if n <= 0.4:
                _darken_px(tile, x, y, 0.62)
            elif n <= 1.0:
                _darken_px(tile, x, y, 0.36)


def _iso_box(
    tile: np.ndarray,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    top: str,
    south: str,
    east: str = "soot",
    lip: int = 5,
) -> None:
    """Крышка и южная грань — лёгкая изометрия, не analog."""
    top_y1 = max(y0 + 1, y1 - lip)
    _rect(tile, x0, y0, x1, top_y1, top)
    _rect(tile, x0, top_y1, x1, y1, south)
    if east:
        _rect(tile, max(x0, x1 - 2), y0, x1, y1, east)
    _rect(tile, x0, y0, min(x1, x0 + 2), min(top_y1, y0 + 1), "ochre")


def paint_floor(wx: int = 0, wy: int = 0, ground: str = "clinic") -> np.ndarray:
    """Пол комнаты: плитка, брусчатка улицы или доски."""
    if ground == "street":
        tile = _blank("graphite")
        for y in range(TILE2D):
            for x in range(TILE2D):
                gx = wx * TILE2D + x
                gy = wy * TILE2D + y
                row = gy // 8
                stagger = (row % 2) * 6
                col = (gx + stagger) // 12
                lx = (gx + stagger) % 12
                ly = gy % 8
                if lx == 11 or ly == 7:
                    _put(tile, x, y, "soot")
                    continue
                n = (col * 17 + row * 13) & 7
                if n == 0:
                    _put(tile, x, y, "slate")
                else:
                    _put(tile, x, y, "graphite")
        return tile
    if ground == "wood":
        tile = _blank("wood")
        for y in range(TILE2D):
            gy = wy * TILE2D + y
            plank = gy // 6
            for x in range(TILE2D):
                gx = wx * TILE2D + x
                if gy % 6 == 5:
                    _put(tile, x, y, "soot")
                elif gy % 6 == 0:
                    _put(tile, x, y, "jamb")
                elif (gx + plank * 5) % 17 == 0:
                    _put(tile, x, y, "jamb")
                else:
                    _put(tile, x, y, "wood")
        return tile
    tile = _blank("graphite")
    step = 16
    for y in range(TILE2D):
        for x in range(TILE2D):
            gx, gy = x % step, y % step
            grout = gx == step - 1 or gy == step - 1
            if grout:
                _put(tile, x, y, "soot")
            elif gy == 0:
                _put(tile, x, y, "slate")
            elif gy == step - 2:
                _put(tile, x, y, "soot")
            elif gx == 0:
                _put(tile, x, y, "slate")
            elif ((x + wx * 5) ^ (y + wy * 3)) % 11 == 0:
                _put(tile, x, y, "slate")
            else:
                _put(tile, x, y, "graphite")
    return tile


def paint_void() -> np.ndarray:
    return _blank("void")


def paint_wall(mask: int) -> np.ndarray:
    """Крышка кирпича и кайма к полу, как комната сверху. Не analog."""
    tile = _blank("graphite")
    bits = mask & 15
    for y in range(TILE2D):
        band = y // 5
        shift = (band % 2) * 6
        for x in range(TILE2D):
            local = (x + shift) % 12
            mortar = (y % 5 == 4) or local == 11
            _put(tile, x, y, "soot" if mortar else "graphite")
    rim = 3
    if not bits & 1:
        _rect(tile, 0, 0, 32, rim, "ice")
        _rect(tile, 0, 0, 32, 1, "frost")
    if not bits & 2:
        _rect(tile, 32 - rim, 0, 32, 32, "ice")
        _rect(tile, 31, 0, 32, 32, "frost")
    if not bits & 8:
        _rect(tile, 0, 0, rim, 32, "ice")
        _rect(tile, 0, 0, 1, 32, "frost")
    if not bits & 4:
        _rect(tile, 0, 16, 32, 32, "ice")
        _rect(tile, 0, 16, 32, 18, "frost")
        _rect(tile, 0, 18, 32, 28, "slate")
        for x in range(TILE2D):
            if x % 3 == 0:
                _put(tile, x, 19, "graphite")
        _rect(tile, 0, 28, 32, 32, "soot")
        _rect(tile, 30, 16, 32, 32, "soot")
    return tile


def paint_window(mask: int) -> np.ndarray:
    tile = paint_wall(mask)
    _rect(tile, 6, 4, 26, 18, "wood")
    _rect(tile, 8, 6, 24, 16, "ice")
    _rect(tile, 9, 7, 23, 15, "frost")
    _rect(tile, 15, 6, 17, 16, "wood")
    _rect(tile, 8, 10, 24, 12, "wood")
    _put(tile, 11, 8, "linen")
    _put(tile, 20, 13, "linen")
    return tile


FACADE_TALL = 4
STREET_YARD = frozenset({".", "*", "T", "+", "'", "C"})


def _map_cell(tiles, x: int, y: int, default: str = "#") -> str:
    if not tiles:
        return default
    height = len(tiles)
    width = len(tiles[0]) if height else 0
    if not (0 <= y < height and 0 <= x < width):
        return default
    return tiles[y][x]


def transition_dir(tiles, x: int, y: int, char: str = "E") -> tuple:
    """Куда смотрит проход: в дом, к краю, вверх по лестнице. Не analog."""
    if char == "S":
        return (0, -1)
    if char == "s":
        return (0, 1)
    if not tiles:
        return (0, -1)
    height = len(tiles)
    width = len(tiles[0]) if height else 0
    if x <= 1:
        return (-1, 0)
    if x >= width - 2:
        return (1, 0)
    if y <= 0:
        return (0, -1)
    if y >= height - 1:
        return (0, 1)
    south = _map_cell(tiles, x, y + 1, "#")
    north = _map_cell(tiles, x, y - 1, "#")
    if south in STREET_YARD and north not in STREET_YARD:
        return (0, -1)
    if north in STREET_YARD and south not in STREET_YARD:
        return (0, 1)
    west = _map_cell(tiles, x - 1, y, "#")
    east = _map_cell(tiles, x + 1, y, "#")
    if west in STREET_YARD and east not in STREET_YARD:
        return (1, 0)
    if east in STREET_YARD and west not in STREET_YARD:
        return (-1, 0)
    return (0, -1)


def is_house_gate(tiles, x: int, y: int) -> bool:
    """Ворота в стене, не край тумана."""
    if _map_cell(tiles, x, y, ".") != "E":
        return False
    walls = {"#", "W", "E"}
    left = _map_cell(tiles, x - 1, y, ".")
    right = _map_cell(tiles, x + 1, y, ".")
    return left in walls and right in walls


def paint_gate(wx: int = 0, wy: int = 0) -> np.ndarray:
    """Арка ворот: косяки, проём на двор, не глухая дверь."""
    tile = paint_floor(wx, wy, "street")
    _rect(tile, 0, 0, 7, 32, "ochre")
    _rect(tile, 25, 0, 32, 32, "ochre")
    for y in range(8):
        _rect(tile, 7, y, 25, y + 1, "ochre")
    for y in range(0, 8):
        if (y % 4) == 3:
            _rect(tile, 0, y, 7, y + 1, "wood")
            _rect(tile, 25, y, 32, y + 1, "wood")
    _rect(tile, 9, 8, 23, 32, "void")
    _rect(tile, 14, 3, 18, 8, "linen")
    _rect(tile, 15, 4, 17, 7, "ash")
    return tile


def is_passage(tiles, x: int, y: int) -> bool:
    """Подворотня в линии фасада: щель между домами, не край карты."""
    ch = _map_cell(tiles, x, y, "#")
    if ch not in {".", "*", "E", "'"}:
        return False
    if is_house_gate(tiles, x, y):
        return True
    return is_south_facade(tiles, x - 1, y) or is_south_facade(tiles, x + 1, y)


def facade_cutaway(px: int, py: int, x: int, y: int, reach: int = 2) -> bool:
    """Игрок у стены или у ворот — нижний этаж не заслоняет проход."""
    return max(abs(px - x), abs(py - y)) <= reach


def can_peek(tiles, px: int, py: int, x: int, y: int, reach: int = 2) -> bool:
    """Заглянуть в окно или подворотню: двор/комната в том же простенке."""
    if not is_behind_house(tiles, x, y):
        return True
    if max(abs(px - x), abs(py - y)) > reach + 3:
        return False
    height = len(tiles)
    for fy in range(y + 1, min(height, y + 5)):
        if is_passage(tiles, x, fy) and facade_cutaway(px, py, x, fy, reach):
            return True
        char = _map_cell(tiles, x, fy)
        if char == "W" and is_south_facade(tiles, x, fy):
            return facade_cutaway(px, py, x, fy, reach)
        if is_south_facade(tiles, x, fy):
            return False
    return False


def _window_lit(wx: int, wy: int, story: int, mapped: bool) -> bool:
    """Часть окон с огнём. Клетка W на мостовой всегда светит снизу."""
    if mapped and story == FACADE_TALL - 1:
        return True
    return (wx * 19 + wy * 23 + story * 11) % 7 in (0, 3)


def is_south_facade(tiles, x: int, y: int) -> bool:
    """Лицевой дом к широкой мостовой. Двор в четыре клетки — не Невский."""
    if _map_cell(tiles, x, y) not in {"#", "W", '"'}:
        return False
    if _map_cell(tiles, x, y + 1, ".") not in STREET_YARD:
        return False
    return _yard_width(tiles, x, y + 1) >= 8


def _yard_width(tiles, x: int, y: int) -> int:
    if _map_cell(tiles, x, y, "#") not in STREET_YARD:
        return 0
    width = 1
    for dx in range(1, 16):
        if _map_cell(tiles, x + dx, y, "#") in STREET_YARD:
            width += 1
        else:
            break
    for dx in range(1, 16):
        if _map_cell(tiles, x - dx, y, "#") in STREET_YARD:
            width += 1
        else:
            break
    return width


def is_behind_house(tiles, x: int, y: int) -> bool:
    """Клетка к северу от лицевого фасада — двор или комната, не улица."""
    if not tiles:
        return False
    for fy in range(y + 1, len(tiles)):
        if (
            is_south_facade(tiles, x, fy)
            or is_house_gate(tiles, x, fy)
            or is_passage(tiles, x, fy)
        ):
            return True
        if _map_cell(tiles, x, fy) == "=":
            return False
    return False


def is_quay_wall(tiles, x: int, y: int) -> bool:
    if _map_cell(tiles, x, y) not in {"#", "W"}:
        return False
    for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        if _map_cell(tiles, x + dx, y + dy, ".") == "=":
            return True
    return False


def _fput(tile: np.ndarray, x: int, y: int, name: str) -> None:
    h, w = tile.shape[:2]
    if 0 <= x < w and 0 <= y < h:
        tile[y, x] = INK[name]


def _frect(tile: np.ndarray, x0: int, y0: int, x1: int, y1: int, name: str) -> None:
    h, w = tile.shape[:2]
    x0, x1 = max(0, x0), min(w, x1)
    y0, y1 = max(0, y0), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return
    tile[y0:y1, x0:x1] = INK[name]


def _bay_window(tile: np.ndarray, y0: int, lit: bool, open_pane: bool = False) -> None:
    """Прямоугольное окно с сандриком. Открытое стекло — дыра на комнату."""
    _frect(tile, 8, y0 + 3, 24, y0 + 5, "ash")
    _frect(tile, 7, y0 + 4, 25, y0 + 6, "linen")
    _frect(tile, 8, y0 + 6, 24, y0 + 23, "linen")
    if open_pane:
        _frect(tile, 10, y0 + 8, 22, y0 + 21, "void")
    elif lit:
        _frect(tile, 10, y0 + 8, 22, y0 + 21, "lamp")
        _frect(tile, 11, y0 + 9, 21, y0 + 20, "ochre")
        _fput(tile, 12, y0 + 11, "frost")
        _fput(tile, 18, y0 + 12, "linen")
    else:
        _frect(tile, 10, y0 + 8, 22, y0 + 21, "canal")
        _frect(tile, 11, y0 + 9, 21, y0 + 20, "soot")
    _frect(tile, 15, y0 + 8, 17, y0 + 21, "linen")
    _frect(tile, 10, y0 + 14, 22, y0 + 15, "linen")
    if open_pane and lit:
        _fput(tile, 9, y0 + 7, "lamp")
        _fput(tile, 22, y0 + 7, "lamp")


def facade_peek_y(wy: int, story: int) -> int:
    """Клетка за стеклом: нижнее окно — первая комната, выше — дальше вглубь."""
    return wy - (FACADE_TALL - story)


def facade_interior(tiles, x: int, facade_y: int, story: int):
    """Первая комната за стеклом, не кирпич простенка."""
    y = facade_peek_y(facade_y, story)
    if not tiles or y >= len(tiles):
        return None, "#"
    while y >= 0:
        ch = _map_cell(tiles, x, y, "#")
        if ch not in {"#", "W", '"'}:
            return y, ch
        y -= 1
    return None, "#"


def is_under_facade(tiles, x: int, y: int) -> bool:
    """Комната, которую закроет лицевой фасад. Выше карниза — небо."""
    if not tiles:
        return False
    height = len(tiles)
    for fy in range(y + 1, min(height, y + FACADE_TALL)):
        if (
            is_south_facade(tiles, x, fy)
            or is_house_gate(tiles, x, fy)
            or is_passage(tiles, x, fy)
        ):
            return True
    return False


def paint_facade(
    wx: int, wy: int, window: bool = False, open_stories: int = 0, arch: bool = False
) -> np.ndarray:
    """Охра, руст, карниз. Дом Иохима / Гражданская, не кирпичная крышка клетки."""
    height = TILE2D * FACADE_TALL
    tile = np.empty((height, TILE2D, 3), dtype=np.uint8)
    tile[:] = INK["ochre"]
    for story in range(FACADE_TALL):
        y0 = story * TILE2D
        y1 = y0 + TILE2D
        ground = story == FACADE_TALL - 1
        if ground:
            _frect(tile, 0, y0, TILE2D, y1, "ochre")
            for y in range(y0, y1):
                groove = (y - y0) % 4
                if groove == 3:
                    _frect(tile, 0, y, TILE2D, y + 1, "wood")
                elif groove == 0:
                    _frect(tile, 0, y, TILE2D, y + 1, "jamb")
        else:
            _frect(tile, 0, y0, TILE2D, y1, "ochre")
            for y in range(y0, y1):
                for x in range(TILE2D):
                    n = (x + wx * 3 + y + story * 11) & 15
                    if n == 0:
                        _fput(tile, x, y, "paper")
                    elif n == 8:
                        _fput(tile, x, y, "jamb")
            _frect(tile, 0, y1 - 2, TILE2D, y1 - 1, "ash")
            _frect(tile, 0, y1 - 1, TILE2D, y1, "linen")
        if wx % 4 == 0:
            _frect(tile, 0, y0, 2, y1, "paper")
            _frect(tile, 30, y0, 32, y1, "paper")
        lit = _window_lit(wx, wy, story, window)
        open_pane = bool(open_stories & (1 << story))
        if arch and ground:
            _frect(tile, 6, y0 + 4, 26, y1, "void")
        else:
            _bay_window(tile, y0, lit, open_pane)
    _frect(tile, 0, 0, TILE2D, 2, "ash")
    _frect(tile, 0, 2, TILE2D, 5, "linen")
    _frect(tile, 0, 5, TILE2D, 6, "ash")
    for x in range(1, TILE2D - 1, 3):
        _frect(tile, x, 3, x + 2, 5, "paper")
    return tile


def paint_stucco_side() -> np.ndarray:
    """Бок дома на улице: штукатурка, не крышка кирпича."""
    tile = _blank("ochre")
    for y in range(TILE2D):
        if y % 4 == 3:
            _rect(tile, 0, y, 32, y + 1, "jamb")
        _put(tile, 0, y, "paper")
        _put(tile, 31, y, "wood")
    return tile


def paint_picture(mask: int) -> np.ndarray:
    tile = paint_wall(mask)
    _rect(tile, 7, 5, 25, 22, "wood")
    _rect(tile, 9, 7, 23, 20, "paper")
    _rect(tile, 11, 9, 16, 14, "blood")
    _rect(tile, 16, 12, 21, 18, "ochre")
    _put(tile, 14, 11, "soot")
    return tile


def _on_floor(wx: int, wy: int, stamp, ground: str = "clinic") -> np.ndarray:
    tile = paint_floor(wx, wy, ground)
    stamp(tile)
    return tile


def _bed(tile: np.ndarray) -> None:
    """Почти вся клетка: рама, матрас, подушка. Как палата сверху, не куколка."""
    _iso_shadow(tile, 16, 29, 15, 4, 3, 1)
    _iso_box(tile, 1, 3, 31, 31, "wood", "soot", "soot", 5)
    _rect(tile, 3, 7, 29, 25, "linen")
    _rect(tile, 3, 8, 29, 20, "ash")
    _rect(tile, 4, 9, 18, 17, "linen")
    _rect(tile, 5, 10, 16, 15, "paper")
    _rect(tile, 1, 3, 31, 8, "wood")
    _rect(tile, 1, 3, 31, 5, "jamb")
    _rect(tile, 28, 7, 31, 31, "soot")


def _table(tile: np.ndarray) -> None:
    """Круглый стол на три четверти клетки, не блюдце."""
    _iso_shadow(tile, 17, 27, 14, 5, 4, 2)
    _oval(tile, 16, 22, 14, 7, "soot")
    _oval(tile, 16, 14, 14, 8, "wood")
    _oval(tile, 16, 13, 12, 6, "jamb")
    _oval(tile, 16, 13, 11, 5, "wood")
    _rect(tile, 12, 12, 20, 14, "paper")
    _put(tile, 11, 12, "ochre")
    _put(tile, 18, 13, "ash")
    _rect(tile, 7, 20, 10, 28, "wood")
    _rect(tile, 22, 20, 25, 28, "wood")
    _rect(tile, 7, 27, 10, 29, "soot")
    _rect(tile, 22, 27, 25, 29, "soot")


def _chair(tile: np.ndarray) -> None:
    """Стул меньше стола, но занимает клетку, не щепку."""
    _iso_shadow(tile, 16, 28, 10, 4, 4, 2)
    _iso_box(tile, 8, 16, 24, 29, "wood", "soot", "soot", 5)
    _rect(tile, 10, 17, 22, 22, "jamb")
    _rect(tile, 8, 4, 24, 17, "wood")
    _rect(tile, 10, 6, 22, 16, "jamb")
    _rect(tile, 21, 4, 24, 29, "soot")
    _rect(tile, 10, 27, 13, 31, "wood")
    _rect(tile, 19, 27, 22, 31, "wood")


def _cabinet(tile: np.ndarray) -> None:
    """Шкаф к стене: створки и карниз на всю клетку."""
    _iso_shadow(tile, 16, 29, 14, 3, 4, 1)
    _iso_box(tile, 2, 1, 30, 31, "wood", "soot", "soot", 6)
    _rect(tile, 4, 5, 14, 14, "jamb")
    _rect(tile, 16, 5, 27, 14, "jamb")
    _rect(tile, 4, 16, 14, 24, "jamb")
    _rect(tile, 16, 16, 27, 24, "jamb")
    _rect(tile, 14, 5, 16, 24, "wood")
    _put(tile, 12, 9, "brass")
    _put(tile, 25, 9, "brass")
    _put(tile, 12, 19, "brass")
    _put(tile, 25, 19, "brass")
    _rect(tile, 2, 1, 30, 4, "graphite")
    _rect(tile, 2, 1, 6, 4, "ochre")


def _desk(tile: np.ndarray) -> None:
    """Письменный стол: крышка на клетку, бумага и чернильница."""
    _iso_shadow(tile, 16, 28, 15, 4, 4, 2)
    _iso_box(tile, 1, 10, 31, 30, "wood", "soot", "soot", 6)
    _rect(tile, 3, 12, 28, 16, "jamb")
    _rect(tile, 3, 4, 18, 12, "paper")
    _rect(tile, 4, 5, 17, 7, "ash")
    _rect(tile, 6, 8, 15, 10, "graphite")
    _rect(tile, 22, 6, 29, 14, "brass")
    _put(tile, 25, 8, "lamp")
    _rect(tile, 3, 26, 7, 31, "wood")
    _rect(tile, 24, 26, 28, 31, "wood")


def _lamp(tile: np.ndarray) -> None:
    _iso_shadow(tile, 16, 26, 7, 3, 4, 3)
    _iso_box(tile, 13, 22, 19, 29, "brass", "soot", "soot", 3)
    _rect(tile, 15, 14, 17, 23, "brass")
    _oval(tile, 16, 11, 6, 6, "lamp")
    _oval(tile, 16, 11, 3, 3, "linen")
    _put(tile, 16, 6, "brass")
    for x, y in ((10, 11), (22, 11), (16, 5), (12, 7), (20, 7)):
        _put(tile, x, y, "lamp")


def _item(tile: np.ndarray) -> None:
    _iso_shadow(tile, 16, 24, 6, 3, 3, 2)
    _iso_box(tile, 12, 14, 20, 24, "ochre", "wood", "soot", 4)
    _rect(tile, 14, 16, 18, 20, "rust")
    _put(tile, 15, 15, "brass")


def _note(tile: np.ndarray) -> None:
    _iso_shadow(tile, 16, 24, 6, 3, 3, 2)
    _iso_box(tile, 10, 12, 22, 25, "paper", "wood", "soot", 3)
    _rect(tile, 12, 14, 20, 16, "graphite")
    _rect(tile, 12, 18, 18, 19, "graphite")


def _potion(tile: np.ndarray) -> None:
    _iso_shadow(tile, 16, 25, 5, 3, 3, 2)
    _iso_box(tile, 13, 18, 19, 27, "ice", "canal", "soot", 4)
    _rect(tile, 14, 20, 18, 24, "blood")
    _rect(tile, 14, 12, 18, 18, "ash")
    _put(tile, 16, 11, "linen")


def paint_door(char: str, wx: int = 0, wy: int = 0, ground: str = "clinic") -> np.ndarray:
    tile = paint_floor(wx, wy, ground)
    _iso_shadow(tile, 16, 26, 11, 4, 4, 3)
    if char == "'":
        _iso_box(tile, 2, 4, 9, 30, "jamb", "soot", "soot", 5)
        _iso_box(tile, 23, 4, 30, 30, "jamb", "soot", "soot", 5)
        _rect(tile, 3, 6, 8, 24, "wood")
        _rect(tile, 24, 6, 29, 24, "wood")
        return tile
    fill = "rust" if char == "d" else "door"
    _iso_box(tile, 6, 3, 26, 30, "jamb", "soot", "soot", 6)
    _rect(tile, 8, 5, 23, 22, fill)
    _rect(tile, 15, 5, 17, 22, "jamb")
    _put(tile, 20, 14, "brass")
    _put(tile, 11, 14, "brass")
    return tile


def paint_stairs(up: bool, wx: int = 0, wy: int = 0, ground: str = "clinic") -> np.ndarray:
    tile = paint_floor(wx, wy, ground)
    _iso_shadow(tile, 16, 27, 12, 4, 4, 2)
    for i in range(5):
        y0 = 4 + i * 5
        inset = i if up else 4 - i
        top = "ash" if i % 2 == 0 else "slate"
        _iso_box(tile, 4 + inset, y0, 28 - inset, y0 + 5, top, "graphite", "soot", 2)
    return tile


def paint_exit(wx: int = 0, wy: int = 0, ground: str = "clinic") -> np.ndarray:
    tile = paint_floor(wx, wy, ground)
    _iso_shadow(tile, 16, 26, 10, 4, 4, 3)
    _iso_box(tile, 8, 4, 24, 30, "ice", "canal", "soot", 6)
    _rect(tile, 10, 6, 21, 22, "frost")
    _rect(tile, 14, 6, 18, 22, "ice")
    return tile


def paint_fog_gate(
    wx: int = 0, wy: int = 0, ground: str = "street", density: float = 1.0
) -> np.ndarray:
    """Выход в вате. Плотность 1 — густой, меньше — редеет, пол виден."""
    tile = paint_floor(wx, wy, ground)
    d = max(0.12, min(1.0, float(density)))
    for y in range(TILE2D):
        for x in range(TILE2D):
            gx = wx * TILE2D + x
            gy = wy * TILE2D + y
            wisp = (gx * 13 + gy * 7 + gx * gy) & 255
            swirl = 0.5 + 0.5 * math.sin(gx * 0.18 + gy * 0.11)
            cover = (wisp / 255.0) * 0.55 + swirl * 0.45
            if cover < 1.0 - 0.82 * d:
                continue
            if wisp % 5 == 0:
                ink = "linen"
            elif wisp % 3 == 0:
                ink = "frost"
            else:
                ink = "ash"
            _mix_px(tile, x, y, ink, 0.28 + 0.55 * d)
    return tile


def paint_canal(wx: int = 0, wy: int = 0) -> np.ndarray:
    tile = _blank("canal")
    for y in range(TILE2D):
        for x in range(TILE2D):
            v = (x + y * 2 + wx * 3 + wy) % 8
            if v == 0:
                _put(tile, x, y, "ice")
            elif v == 4:
                _put(tile, x, y, "soot")
    return tile


_STAMPS = {
    "B": _bed,
    "T": _table,
    "C": _chair,
    "H": _cabinet,
    "O": _desk,
    "*": _lamp,
    "!": _item,
    ")": _item,
    "≈": _note,
    "~": _note,
    "+": _potion,
}


def paint_cell(
    char: str,
    mask: int = 0,
    wx: int = 0,
    wy: int = 0,
    ground: str = "clinic",
    fog: float = 0.0,
) -> np.ndarray:
    src = {"~": "≈", ")": "!"}.get(char, char)
    if src == " " or src == "":
        return paint_void()
    if src == "#":
        if ground == "street":
            return paint_stucco_side()
        return paint_wall(mask)
    if src == "W":
        return paint_window(mask)
    if src == '"':
        return paint_picture(mask)
    if src in {"D", "d", "'"}:
        return paint_door(src, wx, wy, ground)
    if src == "S":
        return paint_stairs(True, wx, wy, ground)
    if src == "s":
        return paint_stairs(False, wx, wy, ground)
    if src == "E":
        if ground == "street":
            return paint_floor(wx, wy, ground)
        return paint_exit(wx, wy, ground)
    if src == "=":
        return paint_canal(wx, wy)
    if src in _STAMPS:
        return _on_floor(wx, wy, _STAMPS[src], ground)
    return paint_floor(wx, wy, ground)


def _silhouette_outline(tile: np.ndarray, name: str = "soot") -> None:
    solid = np.any(tile != VOID_RGB, axis=2)
    if not solid.any():
        return
    ink = INK[name]
    h, w = solid.shape
    for y in range(h):
        for x in range(w):
            if solid[y, x]:
                continue
            edge = (
                (x > 0 and solid[y, x - 1])
                or (x + 1 < w and solid[y, x + 1])
                or (y > 0 and solid[y - 1, x])
                or (y + 1 < h and solid[y + 1, x])
            )
            if edge:
                tile[y, x] = ink


def overlay(base: np.ndarray, sprite: np.ndarray) -> np.ndarray:
    mask = np.any(sprite != VOID_RGB, axis=2)
    out = base.copy()
    out[mask] = sprite[mask]
    return out


def paint_shadow() -> np.ndarray:
    tile = _blank("void")
    _oval(tile, 20, 29, 10, 4, "soot")
    _oval(tile, 17, 28, 7, 3, "soot")
    return tile


# Кто есть кто на клетке. Только уже живущие в базе id.
CAST = {
    "doctor_shpilkin": {
        "hair": "ash", "coat": "linen", "shirt": "paper", "pants": "graphite",
        "glasses": True,
    },
    "patient_nastasya": {
        "hair": "ash", "coat": "linen", "shirt": "linen", "pants": "ash",
        "long_hair": True, "robe": True,
    },
    "sanitary_panteleimon": {
        "hair": "soot", "coat": "wood", "shirt": "jamb", "pants": "graphite",
        "keys": True,
    },
    "archivist_klara": {
        "hair": "soot", "coat": "paper", "shirt": "ash", "pants": "wood",
    },
    "possessed_patient": {
        "hair": "soot", "coat": "blood", "shirt": "rust", "pants": "soot",
        "wild": True,
    },
    "innkeeper_semyon": {
        "hair": "soot", "coat": "jamb", "shirt": "ochre", "pants": "wood",
        "stout": True,
    },
    "shopkeeper_lukin": {
        "hair": "ash", "coat": "wood", "shirt": "paper", "pants": "graphite",
        "apron": True,
    },
    "landlady_praskovya": {
        "hair": "ash", "coat": "wood", "shirt": "jamb", "pants": "graphite",
        "kerchief": True,
    },
    "watchman_petrov": {
        "hair": "soot", "coat": "graphite", "shirt": "slate", "pants": "soot",
        "cap": True,
    },
    "sennaya_beggar": {
        "hair": "graphite", "coat": "ochre", "shirt": "wood", "pants": "soot",
        "ragged": True,
    },
    "player_double": {
        "hair": "ash", "coat": "ash", "shirt": "linen", "pants": "slate",
    },
    "seeker": {"hair": "soot"},
    "mystic": {"hair": "ash", "long_hair": True},
    "rebel": {"hair": "soot"},
}


def _person_colors(kind: str, look: str, who: str = ""):
    if kind == "player":
        if look == "tenant":
            pal = {
                "hair": "soot",
                "skin": "ochre",
                "shirt": "wood",
                "coat": "jamb",
                "pants": "graphite",
                "shoes": "soot",
            }
        elif look == "bare":
            pal = {
                "hair": "graphite",
                "skin": "ochre",
                "shirt": "ochre",
                "coat": "ochre",
                "pants": "ochre",
                "shoes": "soot",
            }
        else:
            pal = {
                "hair": "ash",
                "skin": "ochre",
                "shirt": "linen",
                "coat": "linen",
                "pants": "linen",
                "shoes": "ash",
            }
    elif kind == "foe":
        pal = {
            "hair": "soot",
            "skin": "ochre",
            "shirt": "blood",
            "coat": "rust",
            "pants": "graphite",
            "shoes": "soot",
        }
    else:
        pal = {
            "hair": "graphite",
            "skin": "ochre",
            "shirt": "ochre",
            "coat": "wood",
            "pants": "wood",
            "shoes": "soot",
        }
    extra = dict(CAST.get(who) or {})
    for key in ("hair", "skin", "shirt", "coat", "pants", "shoes"):
        if key in extra:
            pal[key] = extra[key]
    return pal, extra


def paint_person(
    kind: str = "npc",
    look: str = "clinic",
    armed: bool = False,
    face: Tuple[int, int] = (0, 1),
    who: str = "",
) -> np.ndarray:
    """Чиби 32×32. who — id из базы. face — клеточный взгляд, не analog."""
    tile = _blank("void")
    dx, dy = face if face in ((0, 1), (0, -1), (1, 0), (-1, 0)) else (0, 1)
    pal, extra = _person_colors(kind, look, who)
    cx = 16 + dx * 2
    hx = cx
    hy = 10
    robe = (kind == "player" and look == "clinic") or bool(extra.get("robe"))
    stout = bool(extra.get("stout"))

    # волосы / затылок
    _oval(tile, hx, hy - 2, 7, 6, pal["hair"])
    if dy < 0:
        _oval(tile, hx, hy, 6, 6, pal["hair"])
        _rect(tile, hx - 5, hy - 1, hx + 6, hy + 4, pal["hair"])
    else:
        _oval(tile, hx, hy, 6, 6, pal["skin"])
        _oval(tile, hx, hy - 3, 6, 3, pal["hair"])
        _rect(tile, hx - 5, hy - 5, hx + 6, hy - 1, pal["hair"])
        if dx == 0:
            _put(tile, hx - 3, hy, "soot")
            _put(tile, hx + 2, hy, "soot")
            _put(tile, hx - 2, hy + 2, "blood")
            _put(tile, hx - 3, hy - 1, "linen")
        elif dx > 0:
            _put(tile, hx + 3, hy, "soot")
            _put(tile, hx + 1, hy + 2, "blood")
        else:
            _put(tile, hx - 4, hy, "soot")
            _put(tile, hx - 2, hy + 2, "blood")

    # шея
    _rect(tile, hx - 1, hy + 5, hx + 2, hy + 8, pal["skin"])

    # торс
    body_x0, body_x1 = 11, 21
    if dx > 0:
        body_x0, body_x1 = 12, 23
    elif dx < 0:
        body_x0, body_x1 = 9, 20
    if stout:
        body_x0 -= 1
        body_x1 += 1
    _rect(tile, body_x0, 16, body_x1, 24, pal["coat"])
    _rect(tile, body_x0 + 1, 17, body_x1 - 1, 23, pal["shirt"])
    if robe:
        _rect(tile, 10, 20, 22, 28, pal["coat"])
        _rect(tile, 15, 17, 17, 27, "ash")
    elif look == "tenant" and kind == "player":
        _rect(tile, body_x0, 16, body_x1, 20, pal["coat"])
        _rect(tile, body_x0 + 1, 20, body_x1 - 1, 24, pal["pants"])

    # руки
    if dx < 0:
        _rect(tile, 6, 17, 11, 24, pal["coat"])
        _rect(tile, 5, 22, 9, 25, pal["skin"])
        _rect(tile, 21, 17, 24, 23, pal["coat"])
        _rect(tile, 21, 22, 24, 24, pal["skin"])
    elif dx > 0:
        _rect(tile, 21, 17, 26, 24, pal["coat"])
        _rect(tile, 23, 22, 27, 25, pal["skin"])
        _rect(tile, 8, 17, 11, 23, pal["coat"])
        _rect(tile, 8, 22, 11, 24, pal["skin"])
    else:
        _rect(tile, 8, 17, 12, 24, pal["coat"])
        _rect(tile, 20, 17, 24, 24, pal["coat"])
        _rect(tile, 8, 23, 11, 25, pal["skin"])
        _rect(tile, 21, 23, 24, 25, pal["skin"])

    if armed:
        if dx < 0:
            _rect(tile, 3, 14, 6, 26, "slate")
            _put(tile, 4, 13, "ash")
        else:
            _rect(tile, 26, 14, 29, 26, "slate")
            _put(tile, 27, 13, "ash")

    # ноги
    if not robe:
        gap = 1 if dx == 0 else 0
        _rect(tile, 12 - gap, 23, 16, 29, pal["pants"])
        _rect(tile, 16 + gap, 23, 20, 29, pal["pants"])
    _rect(tile, 12, 28, 16, 31, pal["shoes"])
    _rect(tile, 16, 28, 20, 31, pal["shoes"])
    if dx != 0:
        _rect(tile, 12 + dx, 28, 16 + dx, 31, pal["shoes"])
        _rect(tile, 16 + dx, 28, 20 + dx, 31, pal["shoes"])

    if extra.get("long_hair"):
        _rect(tile, hx - 7, hy, hx - 5, hy + 10, pal["hair"])
        _rect(tile, hx + 5, hy, hx + 8, hy + 10, pal["hair"])
    if extra.get("wild"):
        _put(tile, hx - 6, hy - 6, pal["hair"])
        _put(tile, hx + 6, hy - 6, pal["hair"])
        _put(tile, hx, hy - 8, "blood")
        _rect(tile, hx - 2, hy + 1, hx + 3, hy + 3, "blood")
    if extra.get("cap"):
        _rect(tile, hx - 6, hy - 6, hx + 7, hy - 2, "graphite")
        _rect(tile, hx - 7, hy - 3, hx + 8, hy - 1, "soot")
    if extra.get("kerchief"):
        _oval(tile, hx, hy - 4, 7, 3, "ash")
        _rect(tile, hx + 5, hy - 2, hx + 8, hy + 6, "ash")
    if extra.get("glasses") and dy >= 0:
        _rect(tile, hx - 4, hy - 1, hx - 1, hy + 1, "slate")
        _rect(tile, hx + 1, hy - 1, hx + 4, hy + 1, "slate")
        _put(tile, hx, hy, "slate")
    if extra.get("apron"):
        _rect(tile, body_x0 + 2, 18, body_x1 - 2, 26, "paper")
    if extra.get("keys"):
        _put(tile, body_x1 - 2, 22, "brass")
        _put(tile, body_x1 - 1, 23, "brass")
    if extra.get("ragged"):
        _put(tile, body_x0, 24, "soot")
        _put(tile, body_x1 - 1, 25, "void")

    _silhouette_outline(tile, "soot")
    return tile
