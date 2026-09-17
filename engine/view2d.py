"""Первый вид 2D: та же сетка .txt, пиксель как Streets of Rogue, не analog.

Шаг — клетка. Мышь карту не водит. Кость и дверь — GameEngine.
Квадрат 32×32 ×2. tcod остаётся 16×24. Свет — градиент, панели по тексту.
"""
from pathlib import Path
from typing import List, Optional, Tuple
import math
import time

import numpy as np
import pygame
import tcod

from engine.battle_stage import load_stage, stage_kind_for
from engine.clinic_font import BUNDLED_FONT
from engine.clinic_tiles import wall_neighbor_mask
from engine.constants import UNARMED_DAMAGE_DIE
from engine.equipment import EQUIP_SLOTS, empty_fill, item_in_slot, slot_fill_name
from engine.look_memory import is_armed, worn_look
from engine.paintings import oil_id_for_item
from engine.palette import INKS, hex_to_rgb
from engine.party import companion_ids
from engine.quest_system import fog_veil
from engine.renderer import load_oil_pixels
from engine.talent_system import (
    SAN_FLOOR,
    deed_ready,
    has_talent,
    san_cost_for,
    take_block_reason,
    visible_talents,
)
from engine.tiles2d import (
    CELL,
    FACADE_TALL,
    SCALE,
    TILE2D,
    VOID_RGB,
    flame_flicker,
    is_behind_house,
    is_house_gate,
    is_passage,
    is_quay_wall,
    is_south_facade,
    facade_interior,
    is_under_facade,
    light_tint,
    overlay,
    paint_cell,
    paint_facade,
    paint_gate,
    paint_person,
    paint_shadow,
    paint_wall,
    transition_dir,
)

MAP_COLS = 16
MAP_ROWS = 12
HUD_H = 80
HINT_H = 24
LINE_H = 18
WIN_W = MAP_COLS * CELL
WIN_H = MAP_ROWS * CELL + HUD_H
MAP_H = MAP_ROWS * CELL
# Масло в игре 3:4; клетка tcod 11×10 давала 176×240 и чуть плющила.
FACE_W = 180
FACE_H = 240
OVERLAY_W = 760
LIGHT_RES = 4
FIGHT_FACE_W = 90
FIGHT_FACE_H = 120
DOLL_SCALE = 4
SLOT_W = 116
SLOT_H = 76
SLOT_GAP = 8
SLOT_ICON = 28

VOID = hex_to_rgb(INKS["void"])
SOOT = hex_to_rgb(INKS["soot"])
ASH = hex_to_rgb(INKS["ash"])
LINEN = hex_to_rgb(INKS["linen"])
PAPER = hex_to_rgb(INKS["paper"])
BLOOD = hex_to_rgb(INKS["blood"])
RUST = hex_to_rgb(INKS["rust"])
SLATE = hex_to_rgb(INKS["slate"])
LAMP = hex_to_rgb(INKS["lamp"])
WOOD = hex_to_rgb(INKS["wood"])
ICE = hex_to_rgb(INKS["ice"])
OCHRE = hex_to_rgb(INKS["ochre"])
GRAPHITE = hex_to_rgb(INKS["graphite"])
FROST = hex_to_rgb(INKS["frost"])
FOG_EAST = 45
FOG_EDGE_SPAN = 16.0
FOG_EDGE_THICK = 0.94
FOG_EDGE_THIN = 0.22
FOG_BASE_THICK = 0.16
FOG_BASE_THIN = 0.07


def edge_fog(fx: float, map_w: int, veil: float) -> float:
    """Плотность ваты 0…1. К краю карты — почти глухая; после правды — дымка."""
    width = max(1.0, float(map_w))
    span = min(FOG_EAST, width * 0.35, FOG_EDGE_SPAN)
    start = width - 1.0 - span
    t = max(0.0, min(1.0, (float(fx) - start) / span))
    t = t * t * (3.0 - 2.0 * t)
    milk = FOG_BASE_THIN + (FOG_BASE_THICK - FOG_BASE_THIN) * float(veil)
    wall = FOG_EDGE_THIN + (FOG_EDGE_THICK - FOG_EDGE_THIN) * float(veil)
    return min(0.96, milk + t * (wall - milk))


class QuitEvent:
    kind = "quit"
    sym = None
    repeat = False


class KeyEvent:
    __slots__ = ("kind", "sym", "repeat")

    def __init__(self, kind: str, sym, repeat: bool = False):
        self.kind = kind
        self.sym = sym
        self.repeat = repeat


def colorize_mask(mask: np.ndarray, fg, bg) -> np.ndarray:
    """Белая маска 16×24 → RGB теми же чернилами, что буква tcod."""
    alpha = mask[:, :, 3:4].astype(np.float32) / 255.0
    fg_arr = np.asarray(fg, dtype=np.float32).reshape(1, 1, 3)
    bg_arr = np.asarray(bg, dtype=np.float32).reshape(1, 1, 3)
    return (bg_arr * (1.0 - alpha) + fg_arr * alpha).astype(np.uint8)


def _font_path() -> Path:
    if BUNDLED_FONT.exists():
        return BUNDLED_FONT
    for path in (
        Path(r"C:\Windows\Fonts\consola.ttf"),
        Path(r"C:\Windows\Fonts\cour.ttf"),
    ):
        if path.exists():
            return path
    return BUNDLED_FONT


def _wrap(text: str, width: int) -> List[str]:
    raw = (text or "").replace("\n", " ").strip()
    if width <= 0:
        return [raw] if raw else []
    words = raw.split()
    if not words:
        return []
    lines, cur = [], words[0]
    for word in words[1:]:
        trial = f"{cur} {word}"
        if len(trial) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    return lines


def _rgb(color) -> Tuple[int, int, int]:
    if color is None:
        return LINEN
    if isinstance(color, tuple) and len(color) >= 3:
        return int(color[0]), int(color[1]), int(color[2])
    r = getattr(color, "r", None)
    if r is None:
        return LINEN
    return int(r), int(getattr(color, "g", 0)), int(getattr(color, "b", 0))


def _hex_pair(colors: dict, char: str, visible: bool) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    row = colors.get(char) if colors else None
    if not row:
        return (SLATE, SOOT) if visible else (SOOT, VOID)
    fg = hex_to_rgb(row.get("fg") or "")
    bg = hex_to_rgb(row.get("bg") or "")
    if visible:
        return fg, bg
    return tuple(max(0, c * 2 // 5) for c in fg), tuple(max(0, c * 2 // 5) for c in bg)


def _face_toward(x: int, y: int, tx: int, ty: int) -> Tuple[int, int]:
    dx, dy = tx - x, ty - y
    if abs(dx) >= abs(dy):
        if dx > 0:
            return (1, 0)
        if dx < 0:
            return (-1, 0)
    if dy < 0:
        return (0, -1)
    return (0, 1)


def _bilerp(grid, fx: float, fy: float, default: float = 0.0) -> float:
    if grid is None:
        return default
    try:
        h, w = grid.shape[:2]
    except (AttributeError, ValueError):
        return default
    if w < 1 or h < 1:
        return default
    fx = min(w - 1.001, max(0.0, fx))
    fy = min(h - 1.001, max(0.0, fy))
    x0 = int(fx)
    y0 = int(fy)
    x1 = min(w - 1, x0 + 1)
    y1 = min(h - 1, y0 + 1)
    tx = fx - x0
    ty = fy - y0
    v00 = float(grid[y0, x0])
    v10 = float(grid[y0, x1])
    v01 = float(grid[y1, x0])
    v11 = float(grid[y1, x1])
    return (
        v00 * (1.0 - tx) * (1.0 - ty)
        + v10 * tx * (1.0 - ty)
        + v01 * (1.0 - tx) * ty
        + v11 * tx * ty
    )


def _soft_mask(grid, passes: int = 2):
    """Край зрения как лужа света: не зубцы клетки."""
    if grid is None:
        return None
    vis = np.asarray(grid, dtype=np.float32)
    if vis.ndim != 2 or vis.size == 0:
        return vis
    for _ in range(max(1, passes)):
        pad = np.pad(vis, 1, mode="edge")
        vis = (
            pad[0:-2, 0:-2]
            + pad[0:-2, 1:-1]
            + pad[0:-2, 2:]
            + pad[1:-1, 0:-2]
            + pad[1:-1, 1:-1] * 4.0
            + pad[1:-1, 2:]
            + pad[2:, 0:-2]
            + pad[2:, 1:-1]
            + pad[2:, 2:]
        ) / 12.0
    return np.clip(vis, 0.0, 1.0)


def _near_seen(fov, x: int, y: int) -> bool:
    if fov is None:
        return True
    if fov.is_explored(x, y) or fov.is_visible(x, y):
        return True
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        if fov.is_explored(x + dx, y + dy) or fov.is_visible(x + dx, y + dy):
            return True
    return False


def _ground_of(engine) -> str:
    mid = getattr(engine, "current_map_id", "") or ""
    if "traktir" in mid or "tenement" in mid:
        return "wood"
    if "street" in mid:
        return "street"
    return "clinic"


def _fit_wh(src_w: int, src_h: int, max_w: int, max_h: int) -> Tuple[int, int]:
    """Вписать картинку в клетку, не растягивая 3:4."""
    if src_w <= 0 or src_h <= 0 or max_w <= 0 or max_h <= 0:
        return max(1, max_w), max(1, max_h)
    scale = min(max_w / src_w, max_h / src_h)
    return max(1, int(round(src_w * scale))), max(1, int(round(src_h * scale)))


def doll_slot_rects(core: pygame.Rect) -> dict:
    """Рамки слотов вокруг фигуры. Не пересекаются."""
    col_h = SLOT_H * 3 + SLOT_GAP * 2
    col_y = core.centery - col_h // 2
    cx = core.centerx - SLOT_W // 2
    left = core.x - SLOT_W - SLOT_GAP
    right = core.right + SLOT_GAP
    step = SLOT_H + SLOT_GAP
    return {
        "head": pygame.Rect(cx, core.y - SLOT_H - SLOT_GAP, SLOT_W, SLOT_H),
        "cloak": pygame.Rect(left, col_y, SLOT_W, SLOT_H),
        "hands": pygame.Rect(right, col_y, SLOT_W, SLOT_H),
        "body": pygame.Rect(left, col_y + step, SLOT_W, SLOT_H),
        "main_hand": pygame.Rect(right, col_y + step, SLOT_W, SLOT_H),
        "belt": pygame.Rect(left, col_y + step * 2, SLOT_W, SLOT_H),
        "off_hand": pygame.Rect(right, col_y + step * 2, SLOT_W, SLOT_H),
        "legs": pygame.Rect(cx, core.bottom + SLOT_GAP, SLOT_W, SLOT_H),
        "feet": pygame.Rect(cx, core.bottom + SLOT_GAP + step, SLOT_W, SLOT_H),
    }


class View2D:
    """Окно pygame. Игрок стоит в клетке карты, не между пикселями."""

    def __init__(self):
        pygame.display.init()
        pygame.font.init()
        self.screen = pygame.display.set_mode((WIN_W, WIN_H))
        pygame.display.set_caption("Петербург. Клиника. Бред.")
        self.clock = pygame.time.Clock()
        path = str(_font_path())
        try:
            self.font = pygame.font.Font(path, 16)
            self.small = pygame.font.Font(path, 13)
            self.tiny = pygame.font.Font(path, 12)
        except (FileNotFoundError, OSError):
            self.font = pygame.font.SysFont("consolas", 16)
            self.small = pygame.font.SysFont("consolas", 13)
            self.tiny = pygame.font.SysFont("consolas", 12)
        self._tile_cache = {}
        self._letter_cache = {}
        self._oil_cache = {}
        self._base_rgb = {}
        self._face = (0, 1)
        self._last_xy = None
        self._ground = "clinic"
        self._map_id = ""
        self._fog_veil = 1.0

    def close(self):
        self._tile_cache.clear()
        self._letter_cache.clear()
        self._oil_cache.clear()
        self._base_rgb.clear()
        pygame.display.quit()

    def poll_events(self):
        """Клавиши → те же KeySym, что tcod. Мышь молчит."""
        out = []
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                out.append(QuitEvent())
                continue
            if event.type not in (pygame.KEYDOWN, pygame.KEYUP):
                continue
            try:
                sym = tcod.event.KeySym(int(event.key))
            except ValueError:
                continue
            kind = "keydown" if event.type == pygame.KEYDOWN else "keyup"
            repeat = bool(getattr(event, "repeat", False)) if kind == "keydown" else False
            out.append(KeyEvent(kind, sym, repeat))
        return out

    def draw(self, engine):
        self._ground = _ground_of(engine)
        self._map_id = getattr(engine, "current_map_id", "") or ""
        self._fog_veil = fog_veil(getattr(engine, "flags", None))
        self.screen.fill(VOID)
        state = getattr(engine, "state", "")
        if state == "class_selection":
            self._draw_class_select(engine)
        elif state in ("combat", "ability_menu"):
            self._draw_fight(engine)
        else:
            self._draw_world(engine)
            if state not in ("ending", "game_over"):
                self._draw_hud(engine)
            if state == "dialogue":
                self._draw_dialogue(engine)
            if getattr(engine, "showing_help", False):
                self._draw_help()
            if getattr(engine, "is_inventory_open", False) and engine.player:
                self._draw_list(
                    "КАРМАН",
                    [getattr(item, "name", "?") for item in engine.player.inventory],
                    getattr(engine, "inventory_selected_index", 0),
                )
            if getattr(engine, "is_talents_open", False) and engine.player:
                self._draw_talents(engine)
            if getattr(engine, "is_character_open", False) and engine.player:
                self._draw_character(engine)
            if getattr(engine, "is_shop_open", False) and engine.player:
                self._draw_shop(engine)
            if getattr(engine, "oil_overlay", None):
                self._draw_oil(engine.oil_overlay)
            if state == "ending":
                self._draw_center("КОНЕЦ", getattr(engine, "ending_id", "") or "")
            elif state == "game_over":
                self._draw_center("КОНЕЦ. Тени победили.", "")
        pygame.display.flip()
        self.clock.tick(30)

    def _update_face(self, player):
        if player is None:
            return
        xy = (int(player.x), int(player.y))
        if self._last_xy is not None:
            dx = xy[0] - self._last_xy[0]
            dy = xy[1] - self._last_xy[1]
            if (dx, dy) in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                self._face = (dx, dy)
        self._last_xy = xy

    def _cam(self, engine, map_w: int, map_h: int) -> Tuple[int, int]:
        player = engine.player
        cx = (player.x if player else 0) - MAP_COLS // 2
        cy = (player.y if player else 0) - MAP_ROWS // 2
        cx = max(0, min(cx, max(0, map_w - MAP_COLS)))
        cy = max(0, min(cy, max(0, map_h - MAP_ROWS)))
        return cx, cy

    def _draw_world(self, engine):
        tiles = getattr(engine, "current_map", None) or []
        if not tiles or not engine.player:
            return
        self._update_face(engine.player)
        map_h = len(tiles)
        map_w = len(tiles[0]) if map_h else 0
        cam_x, cam_y = self._cam(engine, map_w, map_h)
        fov = getattr(engine, "fov_system", None)
        sprites = bool(getattr(engine, "use_sprites", True))
        now = time.perf_counter()
        px = int(engine.player.x)
        py = int(engine.player.y)
        outside = self._ground == "street" and not is_behind_house(tiles, px, py)
        facades = []
        for sy in range(MAP_ROWS):
            for sx in range(MAP_COLS):
                wx, wy = cam_x + sx, cam_y + sy
                dest = (sx * CELL, sy * CELL)
                if not (0 <= wy < map_h and 0 <= wx < map_w):
                    self.screen.fill(VOID, (*dest, CELL, CELL))
                    continue
                visible = fov.is_visible(wx, wy) if fov else True
                if not _near_seen(fov, wx, wy):
                    self.screen.fill(VOID, (*dest, CELL, CELL))
                    continue
                if (
                    outside
                    and is_behind_house(tiles, wx, wy)
                    and not is_under_facade(tiles, wx, wy)
                ):
                    self.screen.fill(VOID, (*dest, CELL, CELL))
                    continue
                char = tiles[wy][wx]
                seen = fov.is_visible(wx, wy) if fov else True
                if sprites and outside and is_passage(tiles, wx, wy):
                    if seen:
                        iy, ich = facade_interior(tiles, wx, wy, FACADE_TALL - 1)
                        if iy is not None:
                            surf = self._tile_surface(ich, tiles, wx, iy)
                            self.screen.blit(surf, dest)
                    surf = self._gate_surface(wx, wy)
                    self.screen.blit(surf, dest)
                    continue
                if sprites and outside and is_south_facade(tiles, wx, wy):
                    arch = is_passage(tiles, wx - 1, wy) or is_passage(
                        tiles, wx + 1, wy
                    )
                    open_stories = 0
                    if seen:
                        for story in range(FACADE_TALL):
                            iy, _ich = facade_interior(tiles, wx, wy, story)
                            if iy is not None:
                                open_stories |= 1 << story
                    if arch and seen:
                        iy, ich = facade_interior(tiles, wx, wy, FACADE_TALL - 1)
                        if iy is not None:
                            surf = self._tile_surface(ich, tiles, wx, iy)
                            self.screen.blit(surf, dest)
                        else:
                            self.screen.fill(VOID, (*dest, CELL, CELL))
                    else:
                        self.screen.fill(VOID, (*dest, CELL, CELL))
                    facades.append(
                        (sx, sy, wx, wy, char == "W", open_stories, arch and seen)
                    )
                    continue
                if sprites:
                    surf = self._tile_surface(char, tiles, wx, wy)
                else:
                    surf = self._letter_surface(char, visible)
                self.screen.blit(surf, dest)
        if sprites:
            for entity in getattr(engine, "entities", None) or []:
                ex = getattr(entity, "x", None)
                ey = getattr(entity, "y", None)
                if (
                    outside
                    and ex is not None
                    and ey is not None
                    and is_behind_house(tiles, int(ex), int(ey))
                ):
                    self._blit_actor(engine, entity, cam_x, cam_y, now)
            for sx, sy, wx, wy, lit, open_stories, arch in facades:
                if open_stories:
                    for story in range(FACADE_TALL):
                        if not (open_stories & (1 << story)):
                            continue
                        iy, ich = facade_interior(tiles, wx, wy, story)
                        if iy is None:
                            continue
                        story_dest = (
                            sx * CELL,
                            (sy - (FACADE_TALL - 1) + story) * CELL,
                        )
                        self.screen.blit(
                            self._tile_surface(ich, tiles, wx, iy), story_dest
                        )
                surf = self._facade_surface(wx, wy, lit, open_stories, arch)
                dest = (sx * CELL, (sy - (FACADE_TALL - 1)) * CELL)
                self.screen.blit(surf, dest)
        for entity in getattr(engine, "entities", None) or []:
            ex = getattr(entity, "x", None)
            ey = getattr(entity, "y", None)
            if (
                outside
                and ex is not None
                and ey is not None
                and is_behind_house(tiles, int(ex), int(ey))
            ):
                continue
            self._blit_actor(engine, entity, cam_x, cam_y, now)
        self._blit_actor(engine, engine.player, cam_x, cam_y, now)
        if sprites:
            glow = self._light_overlay(engine, cam_x, cam_y, now)
            self.screen.blit(glow, (0, 0), special_flags=pygame.BLEND_RGB_MULT)
            if self._ground == "street":
                self.screen.blit(
                    self._street_mist(engine, cam_x, cam_y, now, map_w), (0, 0)
                )
            self._draw_transition_marks(engine, tiles, cam_x, cam_y, now, map_h, map_w)
        if getattr(engine, "state", "") not in ("ending", "game_over"):
            self._draw_meters(engine.player, 12, 10)

    def _transition_cells(self, engine, tiles):
        cells = []
        seen = set()
        db = getattr(engine, "db", None)
        mid = getattr(engine, "current_map_id", "") or ""
        if db is not None:
            for conn in db.get_map_connections(mid) or ():
                x = int(conn.get("source_x", -1))
                y = int(conn.get("source_y", -1))
                if (x, y) in seen:
                    continue
                seen.add((x, y))
                cells.append((x, y))
        return cells

    def _arrow_pts(self, dx: int, dy: int, cx: int, cy: int):
        tip = [(0, -13), (-8, 5), (8, 5)]
        out = []
        for x, y in tip:
            if dx == 0 and dy < 0:
                px, py = x, y
            elif dx == 0 and dy > 0:
                px, py = -x, -y
            elif dx > 0:
                px, py = -y, x
            else:
                px, py = y, -x
            out.append((cx + px, cy + py))
        return out

    def _transition_mark(self, dx: int, dy: int) -> pygame.Surface:
        key = ("tmark", int(dx), int(dy))
        cached = self._tile_cache.get(key)
        if cached is not None:
            return cached
        surf = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
        cx, cy = CELL // 2, CELL // 2
        for radius in range(26, 6, -2):
            alpha = int(22 * (1.0 - radius / 26.0))
            pygame.draw.circle(
                surf, (FROST[0], FROST[1], FROST[2], alpha), (cx, cy), radius
            )
        pts = self._arrow_pts(dx, dy, cx, cy)
        pygame.draw.polygon(
            surf, (FROST[0], FROST[1], FROST[2], 96), pts
        )
        pygame.draw.polygon(
            surf, (LINEN[0], LINEN[1], LINEN[2], 64), pts, 1
        )
        if len(self._tile_cache) > 4000:
            self._tile_cache.clear()
        self._tile_cache[key] = surf
        return surf

    def _draw_transition_marks(self, engine, tiles, cam_x, cam_y, now, map_h, map_w):
        """Ореол и стрелка на клетке перехода. Вата, не неон."""
        fov = getattr(engine, "fov_system", None)
        pulse = 0.62 + 0.28 * math.sin(now * 1.35)
        alpha = max(40, min(180, int(160 * pulse)))
        for x, y in self._transition_cells(engine, tiles):
            if not (0 <= y < map_h and 0 <= x < map_w):
                continue
            if not _near_seen(fov, x, y):
                continue
            sx, sy = x - cam_x, y - cam_y
            if not (0 <= sx < MAP_COLS and 0 <= sy < MAP_ROWS):
                continue
            char = tiles[y][x] if tiles else "E"
            dx, dy = transition_dir(tiles, x, y, char)
            mark = self._transition_mark(dx, dy).copy()
            mark.set_alpha(alpha)
            self.screen.blit(mark, (sx * CELL, sy * CELL))

    def _light_overlay(self, engine, cam_x: int, cam_y: int, now: float) -> pygame.Surface:
        """Свет и взгляд — один гладкий градиент, не зубцы клетки."""
        fov = getattr(engine, "fov_system", None)
        lw, lh = MAP_COLS * LIGHT_RES, MAP_ROWS * LIGHT_RES
        buf = np.zeros((lh, lw, 3), dtype=np.uint8)
        illum = getattr(fov, "illumination", None) if fov is not None else None
        flame_g = getattr(fov, "flame_illumination", None) if fov is not None else None
        moon_g = getattr(fov, "window_illumination", None) if fov is not None else None
        flames = getattr(fov, "flames", None) if fov is not None else None
        sight_m = _soft_mask(getattr(fov, "current_fov", None)) if fov is not None else None
        known_m = _soft_mask(getattr(fov, "explored", None)) if fov is not None else None
        for ly in range(lh):
            for lx in range(lw):
                fx = cam_x + (lx + 0.5) / LIGHT_RES
                fy = cam_y + (ly + 0.5) / LIGHT_RES
                ix, iy = int(fx), int(fy)
                if fov is None:
                    buf[ly, lx] = light_tint(1.0, 0.0, 0.0, 1.0, 1.0)
                    continue
                known = _bilerp(known_m, fx, fy)
                sight = _bilerp(sight_m, fx, fy)
                if known < 0.02 and sight < 0.02:
                    continue
                light = _bilerp(illum, fx, fy)
                flame = _bilerp(flame_g, fx, fy)
                moon = _bilerp(moon_g, fx, fy)
                flicker = flame_flicker(ix, iy, now, flames)
                tint = light_tint(light, flame, moon, sight, flicker)
                fade = max(known, sight)
                buf[ly, lx] = (
                    int(tint[0] * fade),
                    int(tint[1] * fade),
                    int(tint[2] * fade),
                )
        surf = pygame.surfarray.make_surface(np.transpose(buf, (1, 0, 2)))
        return pygame.transform.smoothscale(surf, (MAP_COLS * CELL, MAP_ROWS * CELL))

    def _scale(self, rgb: np.ndarray):
        surf = pygame.surfarray.make_surface(np.transpose(rgb, (1, 0, 2)))
        if SCALE != 1:
            surf = pygame.transform.scale(surf, (CELL, CELL))
        return surf

    def _facade_surface(
        self, wx: int, wy: int, window: bool, open_stories: int = 0, arch: bool = False
    ):
        key = ("facade", wx, wy, bool(window), int(open_stories), bool(arch))
        cached = self._tile_cache.get(key)
        if cached is not None:
            return cached
        surf = self._scale_n(paint_facade(wx, wy, window, open_stories, arch), SCALE)
        surf.set_colorkey(tuple(int(c) for c in VOID_RGB))
        if len(self._tile_cache) > 4000:
            self._tile_cache.clear()
        self._tile_cache[key] = surf
        return surf

    def _gate_surface(self, wx: int, wy: int):
        key = ("gate", wx, wy)
        cached = self._tile_cache.get(key)
        if cached is not None:
            return cached
        surf = self._scale(paint_gate(wx, wy))
        surf.set_colorkey(tuple(int(c) for c in VOID_RGB))
        if len(self._tile_cache) > 4000:
            self._tile_cache.clear()
        self._tile_cache[key] = surf
        return surf

    def _fog_at(self, char: str, x: int) -> float:
        return 0.0

    def _street_mist(
        self, engine, cam_x: int, cam_y: int, now: float, map_w: int
    ) -> pygame.Surface:
        """Вата к востоку. Фонарь в тумане — ореол, не конус."""
        veil = float(getattr(self, "_fog_veil", 1.0))
        lamps = []
        for src in getattr(engine, "light_sources", None) or ():
            if src.get("symbol") == "W":
                continue
            lamps.append(
                (
                    float(src.get("x", 0)) + 0.5,
                    float(src.get("y", 0)) + 0.5,
                    max(0.8, float(src.get("radius") or 1)),
                )
            )
        res = 8
        lw, lh = MAP_COLS * res, MAP_ROWS * res
        rgba = np.zeros((lh, lw, 4), dtype=np.uint8)
        for ly in range(lh):
            for lx in range(lw):
                fx = cam_x + (lx + 0.5) / res
                fy = cam_y + (ly + 0.5) / res
                n = 0.5 + 0.5 * math.sin(fx * 0.51 + now * 0.35) * math.sin(
                    fy * 0.67 + fx * 0.18
                )
                wisp = 0.5 + 0.5 * math.sin(fx * 1.15 - now * 0.22 + fy * 0.4)
                density = edge_fog(fx, map_w, veil)
                alpha = density * (0.72 + 0.28 * n) * (0.55 + 0.45 * wisp)
                glow = 0.0
                for lx0, ly0, rad in lamps:
                    d2 = (fx - lx0) ** 2 + (fy - ly0) ** 2
                    sigma = 0.55 + 0.35 * rad
                    glow = max(glow, math.exp(-d2 / (2.0 * sigma * sigma)))
                alpha *= 1.0 - 0.62 * glow
                alpha = min(0.96, max(0.0, alpha))
                rgba[ly, lx, 0] = ASH[0]
                rgba[ly, lx, 1] = ASH[1]
                rgba[ly, lx, 2] = FROST[2]
                rgba[ly, lx, 3] = int(alpha * 255)
        src = pygame.image.frombuffer(rgba.tobytes(), (lw, lh), "RGBA")
        return pygame.transform.smoothscale(
            src.convert_alpha(), (MAP_COLS * CELL, MAP_ROWS * CELL)
        )

    def _cell_ground(self, tiles, x: int, y: int) -> str:
        ground = getattr(self, "_ground", "clinic")
        if ground == "street" and tiles and is_behind_house(tiles, x, y):
            mid = getattr(self, "_map_id", "") or ""
            if "canal" in mid:
                return "wood"
            return "clinic"
        return ground

    def _paint_base(self, char: str, tiles, x: int, y: int) -> np.ndarray:
        mask_id = wall_neighbor_mask(tiles, x, y) if char in {"#", "W", '"'} else 0
        ground = self._cell_ground(tiles, x, y)
        fog = self._fog_at(char, x)
        quay = ground == "street" and is_quay_wall(tiles, x, y)
        gate = ground == "street" and is_passage(tiles, x, y)
        key = (char, mask_id, x, y, ground, round(fog, 1), quay, gate)
        cached = self._base_rgb.get(key)
        if cached is not None:
            return cached
        if gate:
            rgb = paint_gate(x, y)
        elif quay and char in {"#", "W"}:
            rgb = paint_wall(mask_id) if char == "#" else paint_cell(char, mask_id, x, y, ground, fog)
        else:
            rgb = paint_cell(char, mask_id, x, y, ground, fog)
        if len(self._base_rgb) > 4000:
            self._base_rgb.clear()
        self._base_rgb[key] = rgb
        return rgb

    def _tile_surface(self, char, tiles, x, y):
        mask_id = wall_neighbor_mask(tiles, x, y) if char in {"#", "W", '"'} else 0
        ground = self._cell_ground(tiles, x, y)
        fog = self._fog_at(char, x)
        key = (char, mask_id, x, y, ground, round(fog, 1))
        cached = self._tile_cache.get(key)
        if cached is not None:
            return cached
        surf = self._scale(self._paint_base(char, tiles, x, y))
        if len(self._tile_cache) > 4000:
            self._tile_cache.clear()
        self._tile_cache[key] = surf
        return surf

    def _letter_surface(self, char: str, visible: bool):
        ch = (char or " ")[0]
        key = ("letter", ch, visible)
        cached = self._letter_cache.get(key)
        if cached is not None:
            return cached
        bg = SOOT if visible else VOID
        fg = ASH if visible else SLATE
        surf = pygame.Surface((CELL, CELL))
        surf.fill(bg)
        glyph = self.small.render(ch, True, fg)
        rect = glyph.get_rect(center=(CELL // 2, CELL // 2))
        surf.blit(glyph, rect)
        self._letter_cache[key] = surf
        return surf

    def _blit_actor(self, engine, entity, cam_x: int, cam_y: int, now: float = 0.0):
        if entity is None:
            return
        x, y = getattr(entity, "x", None), getattr(entity, "y", None)
        if x is None or y is None:
            return
        fov = getattr(engine, "fov_system", None)
        player = engine.player
        adjacent = False
        if player is not None:
            adjacent = abs(x - player.x) + abs(y - player.y) <= 1
        if fov and not fov.is_visible(x, y) and not adjacent:
            return
        sx, sy = x - cam_x, y - cam_y
        if not (0 <= sx < MAP_COLS and 0 <= sy < MAP_ROWS):
            return
        dest = (sx * CELL, sy * CELL)
        tiles = engine.current_map
        visible = True if not fov else fov.is_visible(x, y) or adjacent
        if not getattr(engine, "use_sprites", True):
            symbol = str(getattr(entity, "symbol", "@") or "@")[0]
            self.screen.blit(self._letter_surface(symbol, visible), dest)
            return
        if getattr(entity, "type", "") in {"note", "item", "key", "consumable"}:
            extra = {"note": "≈", "consumable": "+", "item": "!", "key": "!"}.get(
                getattr(entity, "type", ""), "!"
            )
            self.screen.blit(self._scale(self._paint_base(extra, tiles, x, y)), dest)
            return
        if entity is not player and not hasattr(entity, "hp"):
            return
        kind = "npc"
        look = "clinic"
        armed = False
        face = (0, 1)
        who = getattr(entity, "id", "") or ""
        if entity is player:
            kind = "player"
            look = worn_look(player)
            armed = is_armed(player)
            face = self._face
        elif getattr(entity, "type", "") == "enemy" or getattr(entity, "ai_behavior", "") == "aggressive":
            kind = "foe"
            if player is not None:
                face = _face_toward(x, y, player.x, player.y)
        elif player is not None:
            face = _face_toward(x, y, player.x, player.y)
        sprite = overlay(paint_shadow(), paint_person(kind, look, armed, face, who))
        surf = self._scale(sprite)
        surf.set_colorkey(tuple(int(c) for c in VOID_RGB))
        self.screen.blit(surf, dest)

    def _draw_hud(self, engine):
        player = engine.player
        if not player:
            return
        top = MAP_H
        hint_y = WIN_H - HINT_H
        pygame.draw.rect(self.screen, SOOT, (0, top, WIN_W, HUD_H))
        pygame.draw.line(self.screen, SLATE, (0, top), (WIN_W, top))
        pygame.draw.line(self.screen, SLATE, (0, hint_y), (WIN_W, hint_y))
        log_stop = hint_y - 2
        y = top + 4
        quest = ""
        if getattr(engine, "quest_system", None):
            desc = engine.quest_system.get_active_quest_descriptions(getattr(engine, "flags", None) or set())
            if desc:
                quest = desc[0]
        lines = []
        if quest:
            lines.extend(self._wrap_px(quest, WIN_W - 24))
        lines.extend(list(getattr(engine, "messages", None) or [])[-1:])
        for msg in lines:
            y = self._text(msg, 12, y, ASH, width=120, stop=log_stop)
            if y >= log_stop:
                break
        hand = "кулак"
        eq = getattr(player, "equipped_weapon_id", None)
        if eq:
            for item in getattr(player, "inventory", None) or []:
                if getattr(item, "id", None) == eq:
                    hand = getattr(item, "name", "нож") or "нож"
                    break
        hint = f"в руке {hand} · e стол · i карман · t тетрадь · c на себе · F4 вид"
        self._text(hint, 12, hint_y + 4, SLATE, width=78, stop=WIN_H)

    def _draw_meter(self, x: int, y: int, w: int, h: int, ratio: float, fill, label: str) -> None:
        ratio = max(0.0, min(1.0, float(ratio)))
        pygame.draw.rect(self.screen, SOOT, (x, y, w, h))
        pygame.draw.rect(self.screen, fill, (x, y, int(w * ratio), h))
        pygame.draw.rect(self.screen, PAPER, (x, y, w, h), 1)
        text = self.tiny.render(label, True, LINEN)
        self.screen.blit(text, (x + 6, y + max(0, (h - text.get_height()) // 2)))

    def _draw_meters(self, player, x: int, y: int) -> None:
        if player is None:
            return
        hp = int(getattr(player, "hp", 0) or 0)
        hp_max = max(1, int(getattr(player, "max_hp", 1) or 1))
        san = int(getattr(player, "san", 0) or 0)
        san_max = max(1, int(getattr(player, "max_san", 100) or 100))
        self._draw_meter(x, y, 176, 16, hp / hp_max, BLOOD, f"плоть {hp}/{hp_max}")
        self._draw_meter(x, y + 20, 176, 16, san / san_max, ICE, f"воля {san}")

    def _char_w(self) -> int:
        return max(1, self.font.size("М")[0])

    def _wrap_px(self, text: str, pixel_width: int) -> List[str]:
        return _wrap(text or "", max(8, pixel_width // self._char_w()))

    def _overlay_box(self, height: int, width: int = 0, bottom: bool = False) -> pygame.Rect:
        w = min(width or OVERLAY_W, WIN_W - 48)
        h = min(max(72, height), MAP_H - 16)
        x = (WIN_W - w) // 2
        y = MAP_H - h - 8 if bottom else max(8, (MAP_H - h) // 2)
        return pygame.Rect(x, y, w, h)

    def _fill_panel(self, box: pygame.Rect) -> None:
        pygame.draw.rect(self.screen, SOOT, box)
        pygame.draw.rect(self.screen, PAPER, box, 1)

    def _draw_talents(self, engine):
        player = engine.player
        nodes = visible_talents(player)
        selected = getattr(engine, "talent_selected_index", 0)
        flags = getattr(engine, "flags", None) or set()
        occupation = getattr(player, "class_name", None) or "без занятия"
        rows = max(1, len(nodes))
        box = self._overlay_box(LINE_H * (rows + 8) + 36, OVERLAY_W)
        self._fill_panel(box)
        col_w = box.width - 32
        chars = max(8, col_w // self._char_w())
        y = box.y + 10
        y = self._text(f"ТЕТРАДЬ · {occupation}", box.x + 16, y, PAPER)
        y = self._text(
            f"воля {int(getattr(player, 'san', 0) or 0)} · после пометки не ниже {SAN_FLOOR}",
            box.x + 16,
            y,
            BLOOD,
            width=chars,
        )
        desc_h = LINE_H * 4
        list_stop = box.bottom - 28 - desc_h
        class_id = getattr(player, "id", "")
        if not nodes:
            self._text("Тетрадь пуста. Странно.", box.x + 16, y, SLATE, stop=list_stop)
        for i, node in enumerate(nodes):
            if y >= list_stop:
                break
            taken = has_talent(player, node.id)
            cost = san_cost_for(node, class_id)
            branch = "бой" if node.branch == "combat" else "мир"
            if taken:
                mark, color, tail = "×", PAPER, "взято"
            else:
                why = take_block_reason(player, node, flags)
                mark = "·" if i == selected else " "
                if why:
                    color = SLATE
                    if node.require_deed == "truth" and not deed_ready(node, flags):
                        tail = "нужны имя или долг"
                    elif node.require_deed == "spoke" and not deed_ready(node, flags):
                        tail = "нужен поступок"
                    else:
                        tail = f"{cost} воли"
                else:
                    color = LAMP if i == selected else ASH
                    tail = f"{cost} воли"
                if i == selected:
                    color = LAMP
            y = self._text(
                f"{mark} [{branch}] {node.name} — {tail}",
                box.x + 16,
                y,
                color,
                width=chars,
                stop=list_stop,
            )
        foot = box.bottom - 22
        if nodes and 0 <= selected < len(nodes):
            desc_y = list_stop + 6
            pygame.draw.line(
                self.screen, SLATE, (box.x + 12, desc_y), (box.right - 12, desc_y)
            )
            self._text(
                nodes[selected].description,
                box.x + 16,
                desc_y + 6,
                ASH,
                width=chars,
                stop=foot,
            )
        self._text("↑/↓ · e взять · t закрыть", box.x + 16, foot, SLATE, stop=WIN_H)

    def _draw_character(self, engine):
        player = engine.player
        occupation = getattr(player, "class_name", None) or "без занятия"
        fills = [
            (slot_id, slot_name, slot_fill_name(player, slot_id))
            for slot_id, slot_name in EQUIP_SLOTS
        ]
        selected = min(
            max(0, int(getattr(engine, "character_selected_index", 0) or 0)),
            len(fills) - 1,
        )
        stats = getattr(player, "stats", None) or {}
        die = getattr(player, "damage_die", None) or UNARMED_DAMAGE_DIE
        ac = getattr(player, "armor_class", 10)
        fig = TILE2D * DOLL_SCALE
        col_h = SLOT_H * 3 + SLOT_GAP * 2
        head_block = SLOT_H + SLOT_GAP
        foot_block = SLOT_H * 2 + SLOT_GAP
        body_block = max(fig, col_h)
        box = self._overlay_box(36 + head_block + body_block + foot_block + 56, OVERLAY_W)
        self._fill_panel(box)
        y = box.y + 10
        y = self._text(f"НА СЕБЕ · {occupation}", box.x + 16, y, PAPER)
        y = self._text(
            f"удар {die} · броня {ac} · "
            f"сила {int(stats.get('STR', 10) or 10)} "
            f"ловкость {int(stats.get('DEX', 10) or 10)} "
            f"тело {int(stats.get('CON', 10) or 10)} · "
            f"ум {int(stats.get('INT', 10) or 10)} "
            f"речь {int(stats.get('CHA', 10) or 10)} "
            f"воля {int(stats.get('WILL', 10) or 10)}",
            box.x + 16,
            y,
            ASH,
            width=max(8, (box.width - 32) // self._char_w()),
        )
        core = pygame.Rect(0, 0, fig, fig)
        core.centerx = box.centerx
        core.y = y + head_block + max(0, (body_block - fig) // 2)
        look = worn_look(player)
        armed = is_armed(player)
        who = getattr(player, "id", "") or ""
        shadow = self._scale_n(paint_shadow(), DOLL_SCALE)
        body = self._scale_n(paint_person("player", look, armed, (0, 1), who), DOLL_SCALE)
        shadow.set_colorkey(tuple(int(c) for c in VOID_RGB))
        body.set_colorkey(tuple(int(c) for c in VOID_RGB))
        self.screen.blit(shadow, core.topleft)
        self.screen.blit(body, core.topleft)
        pygame.draw.rect(self.screen, GRAPHITE, core.inflate(8, 8), 1)
        places = doll_slot_rects(core)
        for i, (slot_id, slot_name, fill) in enumerate(fills):
            rect = places.get(slot_id)
            if rect is None:
                continue
            self._draw_slot_card(
                rect,
                slot_name,
                fill,
                i == selected,
                item_in_slot(player, slot_id),
            )
        slot_id, slot_name, fill = fills[selected]
        vacant = empty_fill(slot_id)
        if fill != vacant:
            note = f"{slot_name}: {fill}."
        elif slot_id == "main_hand":
            note = "правая рука: кулак 1d3."
        else:
            note = f"{slot_name}: пусто."
        foot = box.bottom - 22
        chars = max(8, (box.width - 32) // self._char_w())
        self._text(note, box.x + 16, foot - LINE_H, PAPER, width=chars, stop=foot)
        self._text("↑/↓ слот · e надеть / снять · c закрыть", box.x + 16, foot, SLATE, stop=WIN_H)

    def _scale_n(self, rgb: np.ndarray, n: int) -> pygame.Surface:
        surf = pygame.surfarray.make_surface(np.transpose(rgb, (1, 0, 2)))
        if n != 1:
            surf = pygame.transform.scale(surf, (rgb.shape[1] * n, rgb.shape[0] * n))
        return surf

    def _clip_label(self, text: str, x: int, y: int, color, clip: pygame.Rect) -> None:
        prev = self.screen.get_clip()
        self.screen.set_clip(clip)
        raw = text or ""
        max_w = max(8, clip.right - x - 2)
        while raw and self.tiny.size(raw)[0] > max_w:
            raw = raw[:-1]
        if raw != (text or "") and len(raw) > 1:
            raw = raw[:-1] + "…"
        self.screen.blit(self.tiny.render(raw, True, color), (x, y))
        self.screen.set_clip(prev)

    def _item_swatch(self, item):
        kind = getattr(item, "type", "") or ""
        look = getattr(item, "look", "") or ""
        item_id = getattr(item, "id", "") or ""
        if kind == "weapon":
            return SLATE
        if look == "tenant" or item_id == "item_coat":
            return WOOD
        if kind == "clothing":
            return LINEN
        return OCHRE

    def _draw_slot_card(self, rect, title, fill, selected, item) -> None:
        border = LAMP if selected else (ASH if item else GRAPHITE)
        pygame.draw.rect(self.screen, SOOT, rect)
        pygame.draw.rect(self.screen, border, rect, 2 if selected else 1)
        inner = rect.inflate(-8, -8)
        title_h = 16
        self._clip_label(
            title,
            inner.x,
            inner.y,
            LAMP if selected else ASH,
            pygame.Rect(inner.x, inner.y, inner.width, title_h),
        )
        icon = pygame.Rect(0, 0, SLOT_ICON, SLOT_ICON)
        icon.centerx = rect.centerx
        icon.y = inner.y + title_h + 2
        pygame.draw.rect(self.screen, VOID, icon)
        pygame.draw.rect(self.screen, GRAPHITE, icon, 1)
        prev = self.screen.get_clip()
        self.screen.set_clip(icon)
        if item:
            oil = self._oil_surface(
                oil_id_for_item(getattr(item, "id", "") or ""), SLOT_ICON, SLOT_ICON
            )
            if oil is not None:
                self.screen.blit(oil, oil.get_rect(center=icon.center))
            else:
                swatch = icon.inflate(-8, -8)
                pygame.draw.rect(self.screen, self._item_swatch(item), swatch)
        self.screen.set_clip(prev)
        name = fill or "пусто"
        name_box = pygame.Rect(inner.x, icon.bottom + 2, inner.width, inner.bottom - icon.bottom - 2)
        if name_box.height > 0:
            name_surf = self.tiny.render(name, True, LINEN if item else SLATE)
            nx = inner.x + max(0, (inner.width - name_surf.get_width()) // 2)
            self._clip_label(name, nx, name_box.y, LINEN if item else SLATE, name_box)

    def _draw_class_select(self, engine):
        self._text("Петербург. Клиника. Бред.", 40, 40, PAPER)
        self._text("Вид 2D. Сверху, клетка, не analog.", 40, 68, SLATE)
        classes = getattr(engine, "available_classes", None) or []
        selected = getattr(engine, "selected_class_index", 0)
        y = 120
        for i, cls in enumerate(classes):
            mark = "·" if i == selected else " "
            color = LAMP if i == selected else ASH
            y = self._text(f"{mark} {cls.get('name', '')}", 48, y, color)
            y = self._text(cls.get("description", ""), 64, y, SLATE, width=70)
            y += 8
        self._text("Enter — начать · C — продолжить · Q — выход", 40, WIN_H - 40, SLATE)

    def _draw_fight(self, engine):
        player = engine.player
        enemy = getattr(engine, "current_enemy", None)
        tiles, spots = load_stage(stage_kind_for(engine))
        rows = len(tiles)
        cols = len(tiles[0]) if rows else 0
        stage_w = cols * CELL
        stage_h = rows * CELL
        ox = max(0, (WIN_W - stage_w) // 2)
        oy = 12
        now = time.perf_counter()
        pygame.draw.rect(self.screen, VOID, (0, 0, WIN_W, MAP_H))
        for sy in range(rows):
            for sx in range(cols):
                dest = (ox + sx * CELL, oy + sy * CELL)
                self.screen.blit(self._tile_surface(tiles[sy][sx], tiles, sx, sy), dest)
        glow = self._stage_glow(tiles, now)
        self.screen.blit(glow, (ox, oy), special_flags=pygame.BLEND_RGB_MULT)
        px, py = spots.get("@", (1, max(1, rows // 2)))
        ex, ey = spots.get("&", (max(1, cols - 2), max(1, rows // 2)))
        look = worn_look(player) if player else "clinic"
        armed = is_armed(player) if player else False
        who_p = getattr(player, "id", "") or "" if player else ""
        self._blit_chibi(
            ox + px * CELL,
            oy + py * CELL,
            "player",
            look,
            armed,
            _face_toward(px, py, ex, ey),
            who_p,
        )
        for slot, cid in zip("12", companion_ids(engine)):
            if slot not in spots:
                continue
            ax, ay = spots[slot]
            self._blit_chibi(
                ox + ax * CELL,
                oy + ay * CELL,
                "npc",
                "tenant",
                False,
                _face_toward(ax, ay, ex, ey),
                cid,
            )
        if enemy:
            self._blit_chibi(
                ox + ex * CELL,
                oy + ey * CELL,
                "foe",
                "clinic",
                False,
                _face_toward(ex, ey, px, py),
                getattr(enemy, "id", "") or "",
            )
        if player:
            if getattr(engine, "use_sprites", True):
                oil = self._oil_surface(who_p, FIGHT_FACE_W, FIGHT_FACE_H)
                if oil is not None:
                    self.screen.blit(oil, (8, 16))
            self._draw_meters(player, 8 + FIGHT_FACE_W + 12, 16)
        if enemy:
            if getattr(engine, "use_sprites", True):
                oil = self._oil_surface(getattr(enemy, "id", "") or "", FIGHT_FACE_W, FIGHT_FACE_H)
                if oil is not None:
                    self.screen.blit(oil, (WIN_W - FIGHT_FACE_W - 8, 16))
            name = getattr(enemy, "name", "тень")
            hp = int(getattr(enemy, "hp", 0) or 0)
            mx = max(1, int(getattr(enemy, "max_hp", 1) or 1))
            self._draw_meter(
                WIN_W - FIGHT_FACE_W - 196,
                16,
                176,
                16,
                hp / mx,
                RUST,
                f"{name} {hp}/{mx}",
            )
        pygame.draw.rect(self.screen, SOOT, (0, MAP_H, WIN_W, HUD_H))
        pygame.draw.line(self.screen, SLATE, (0, MAP_H), (WIN_W, MAP_H))
        hint_y = WIN_H - HINT_H
        pygame.draw.line(self.screen, SLATE, (0, hint_y), (WIN_W, hint_y))
        y = MAP_H + 4
        y = self._text("СРЫВ", 12, y, BLOOD, stop=hint_y)
        for msg in list(getattr(engine, "messages", None) or [])[-1:]:
            y = self._text(msg, 12, y, PAPER, width=78, stop=hint_y)
        self._text("1 удар · 2 умение · 3 бежать", 12, hint_y + 4, SLATE, stop=WIN_H)

    def _blit_chibi(self, x, y, kind, look, armed, face, who):
        sprite = overlay(paint_shadow(), paint_person(kind, look, armed, face, who))
        surf = self._scale(sprite)
        surf.set_colorkey(tuple(int(c) for c in VOID_RGB))
        self.screen.blit(surf, (x, y))

    def _stage_glow(self, tiles, now: float) -> pygame.Surface:
        rows = len(tiles)
        cols = len(tiles[0]) if rows else 0
        illum = np.full((rows, cols), 0.85, dtype=np.float32)
        flame_g = np.zeros((rows, cols), dtype=np.float32)
        moon_g = np.zeros((rows, cols), dtype=np.float32)
        flames = []

        def _pool(grid, cx, cy, radius, amount):
            if radius <= 0:
                return
            height = 1.0
            for iy in range(rows):
                for ix in range(cols):
                    dist = math.hypot(ix - cx, iy - cy)
                    if dist > radius:
                        continue
                    d2 = dist * dist + height * height
                    edge = max(0.0, 1.0 - (dist / radius) ** 2)
                    grid[iy, ix] += amount * height / (d2 ** 1.5) * edge

        for y, row in enumerate(tiles):
            for x, char in enumerate(row):
                if char == "*":
                    flames.append((x, y, 2, 1.0))
                    _pool(flame_g, x, y, 2.2, 1.0)
                    _pool(illum, x, y, 2.2, 0.35)
                elif char in "BTOC":
                    flames.append((x, y, 2, 0.4))
                    _pool(flame_g, x, y, 1.8, 0.45)
                    _pool(illum, x, y, 1.8, 0.18)
                elif char == "." and (x * 13 + y * 29) % 14 == 0:
                    flames.append((x, y, 1, 0.28))
                    _pool(flame_g, x, y, 1.2, 0.35)
                    _pool(illum, x, y, 1.2, 0.12)
                if char == "W":
                    _pool(moon_g, x, y, 2.4, 1.0)
        lw, lh = cols * LIGHT_RES, rows * LIGHT_RES
        buf = np.zeros((lh, lw, 3), dtype=np.uint8)
        for ly in range(lh):
            for lx in range(lw):
                fx = (lx + 0.5) / LIGHT_RES
                fy = (ly + 0.5) / LIGHT_RES
                ix, iy = int(fx), int(fy)
                flicker = flame_flicker(ix, iy, now, flames)
                buf[ly, lx] = light_tint(
                    _bilerp(illum, fx, fy, 0.85),
                    _bilerp(flame_g, fx, fy),
                    _bilerp(moon_g, fx, fy),
                    True,
                    flicker,
                )
        surf = pygame.surfarray.make_surface(np.transpose(buf, (1, 0, 2)))
        return pygame.transform.smoothscale(surf, (cols * CELL, rows * CELL))

    def _draw_dialogue(self, engine):
        speaker = getattr(engine, "current_dialogue_speaker", "") or ""
        portrait = getattr(engine, "current_dialogue_portrait", "") or ""
        body = getattr(engine, "current_dialogue_text", "") or ""
        banner = getattr(engine, "current_check_banner", "") or ""
        choices = getattr(engine, "current_dialogue_choices", None) or []
        oil = None
        if portrait and getattr(engine, "use_sprites", True):
            oil = self._oil_surface(portrait, FACE_W, FACE_H)
        face_w = oil.get_width() if oil is not None else 0
        face_h = oil.get_height() if oil is not None else 0
        pad = 16
        gap = 14 if oil is not None else 0
        text_w = min(420, WIN_W - 80 - face_w - gap)
        lines = []
        if banner:
            lines.extend(self._wrap_px(banner, text_w))
        lines.extend(self._wrap_px(body, text_w)[:10])
        choice_lines = []
        for i, choice in enumerate(choices[:9]):
            choice_lines.extend(self._wrap_px(f"{i + 1}. {choice}", text_w))
        text_h = LINE_H * (len(lines) + len(choice_lines) + (1 if choice_lines else 0))
        title_h = LINE_H + 6 if speaker else 8
        inner = max(face_h, text_h)
        box_w = pad + face_w + gap + text_w + pad
        box_h = title_h + inner + pad + 18
        box = self._overlay_box(box_h, box_w, bottom=True)
        self._fill_panel(box)
        y = box.y + 8
        if speaker:
            y = self._text(speaker, box.x + pad, y, LAMP)
        face_y = y
        text_x = box.x + pad
        if oil is not None:
            self.screen.blit(oil, (box.x + pad, face_y))
            text_x = box.x + pad + face_w + gap
        ty = face_y
        chars = max(8, text_w // self._char_w())
        if banner:
            ty = self._text(banner, text_x, ty, RUST, width=chars, stop=box.bottom - 20)
        ty = self._text(body, text_x, ty, PAPER, width=chars, stop=box.bottom - 20)
        if choices:
            ty += 6
            for i, choice in enumerate(choices[:9]):
                raw = (choice or "").lstrip()
                tagged = raw.startswith("[") or raw.startswith("(")
                ty = self._text(
                    f"{i + 1}. {choice}",
                    text_x,
                    ty,
                    LAMP if tagged else ASH,
                    width=chars,
                    stop=box.bottom - 8,
                )

    def _draw_shop(self, engine):
        tab = getattr(engine, "shop_tab", "sell")
        name = getattr(engine, "shop_merchant_name", "") or "лавка"
        title = f"ЛАВКА · {name} · {'продажа' if tab == 'sell' else 'покупка'}"
        rows = []
        if hasattr(engine, "_shop_rows"):
            for item in engine._shop_rows() or []:
                rows.append(getattr(item, "name", None) or getattr(item, "id", "?"))
        self._draw_list(title, rows or ["пусто"], getattr(engine, "shop_selected_index", 0))

    def _draw_oil(self, overlay):
        title = (overlay or {}).get("title") or ""
        body = (overlay or {}).get("body") or ""
        oil = self._oil_surface((overlay or {}).get("oil_id") or "", FACE_W, FACE_H)
        face_w = oil.get_width() if oil is not None else 0
        face_h = oil.get_height() if oil is not None else 0
        pad = 18
        gap = 16 if oil is not None else 0
        text_w = min(380, WIN_W - 80 - face_w - gap)
        lines = self._wrap_px(title, text_w) + self._wrap_px(body, text_w)[:12]
        text_h = LINE_H * max(1, len(lines))
        box = self._overlay_box(
            pad + LINE_H + max(face_h, text_h) + pad,
            pad + face_w + gap + text_w + pad,
        )
        self._fill_panel(box)
        y = box.y + 12
        y = self._text(title, box.x + pad, y, LAMP)
        if oil is not None:
            self.screen.blit(oil, (box.x + pad, y))
        chars = max(8, text_w // self._char_w())
        self._text(
            body,
            box.x + pad + face_w + gap,
            y,
            PAPER,
            width=chars,
            stop=box.bottom - 12,
        )

    def _draw_list(self, title: str, rows: List[str], selected: int):
        shown = list(rows or [])[:16]
        box = self._overlay_box(LINE_H * (len(shown) + 3) + 24, OVERLAY_W)
        self._fill_panel(box)
        pygame.draw.rect(self.screen, SLATE, box, 1)
        chars = max(8, (box.width - 32) // self._char_w())
        y = box.y + 12
        y = self._text(title, box.x + 16, y, PAPER)
        if not shown:
            self._text("пусто", box.x + 16, y, SLATE)
            return
        for i, row in enumerate(shown):
            color = LAMP if i == selected else ASH
            mark = "·" if i == selected else " "
            y = self._text(
                f"{mark} {row}",
                box.x + 16,
                y,
                color,
                width=chars,
                stop=box.bottom - 8,
            )

    def _draw_help(self):
        self._draw_list(
            "ПОЛЯ",
            [
                "стрелки — шаг по клетке",
                "e — дверь, стол, речь",
                "F4 — картинки или буквы",
                "мышь карту не водит",
            ],
            0,
        )

    def _draw_center(self, title: str, body: str):
        self._text(title, 40, WIN_H // 2 - 20, BLOOD)
        if body:
            self._text(body, 40, WIN_H // 2 + 12, ASH)

    def _oil_surface(self, oil_id: str, w: int, h: int) -> Optional[pygame.Surface]:
        if not oil_id:
            return None
        key = (oil_id, w, h)
        cached = self._oil_cache.get(key)
        if cached is not None:
            return cached
        pixels = load_oil_pixels(oil_id)
        if pixels is None:
            return None
        rgb = np.asarray(pixels)
        if rgb.ndim == 3 and rgb.shape[2] >= 3:
            rgb = rgb[:, :, :3]
        src = pygame.surfarray.make_surface(np.transpose(rgb, (1, 0, 2)))
        fw, fh = _fit_wh(src.get_width(), src.get_height(), w, h)
        surf = pygame.transform.smoothscale(src, (fw, fh))
        self._oil_cache[key] = surf
        return surf

    def _text(self, text: str, x: int, y: int, color, width: int = 90, stop: int = 0) -> int:
        limit = stop if stop else WIN_H
        lines = _wrap(text, width) or [""]
        for line in lines:
            if y + LINE_H > limit:
                break
            self.screen.blit(self.font.render(line, True, color), (x, y))
            y += LINE_H
        return y
