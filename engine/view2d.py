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
from engine.look_memory import is_armed, worn_look
from engine.palette import INKS, hex_to_rgb
from engine.party import companion_ids
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
    SCALE,
    VOID_RGB,
    flame_flicker,
    light_tint,
    overlay,
    paint_cell,
    paint_person,
    paint_shadow,
)

MAP_COLS = 16
MAP_ROWS = 10
HUD_H = 200
HINT_H = 24
LINE_H = 18
WIN_W = MAP_COLS * CELL
WIN_H = MAP_ROWS * CELL + HUD_H
MAP_H = MAP_ROWS * CELL
# Масло в игре 3:4; клетка tcod 11×10 давала 176×240 и чуть плющила.
FACE_W = 180
FACE_H = 240
OVERLAY_W = 720
LIGHT_RES = 4
FIGHT_FACE_W = 90
FIGHT_FACE_H = 120

VOID = hex_to_rgb(INKS["void"])
SOOT = hex_to_rgb(INKS["soot"])
ASH = hex_to_rgb(INKS["ash"])
LINEN = hex_to_rgb(INKS["linen"])
PAPER = hex_to_rgb(INKS["paper"])
BLOOD = hex_to_rgb(INKS["blood"])
RUST = hex_to_rgb(INKS["rust"])
SLATE = hex_to_rgb(INKS["slate"])
LAMP = hex_to_rgb(INKS["lamp"])


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


def _fit_wh(src_w: int, src_h: int, max_w: int, max_h: int) -> Tuple[int, int]:
    """Вписать картинку в клетку, не растягивая 3:4."""
    if src_w <= 0 or src_h <= 0 or max_w <= 0 or max_h <= 0:
        return max(1, max_w), max(1, max_h)
    scale = min(max_w / src_w, max_h / src_h)
    return max(1, int(round(src_w * scale))), max(1, int(round(src_h * scale)))


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
            self.small = pygame.font.Font(path, 14)
        except (FileNotFoundError, OSError):
            self.font = pygame.font.SysFont("consolas", 16)
            self.small = pygame.font.SysFont("consolas", 14)
        self._tile_cache = {}
        self._letter_cache = {}
        self._oil_cache = {}
        self._base_rgb = {}
        self._face = (0, 1)
        self._last_xy = None

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
                self._draw_list(
                    "НА СЕБЕ",
                    [f"{slot}: {held or 'пусто'}" for slot, held in (getattr(engine.player, "equipped", None) or {}).items()],
                    getattr(engine, "character_selected_index", 0),
                )
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
                char = tiles[wy][wx]
                if sprites:
                    surf = self._tile_surface(char, tiles, wx, wy)
                else:
                    surf = self._letter_surface(char, visible)
                self.screen.blit(surf, dest)
        for entity in getattr(engine, "entities", None) or []:
            self._blit_actor(engine, entity, cam_x, cam_y, now)
        self._blit_actor(engine, engine.player, cam_x, cam_y, now)
        if sprites:
            glow = self._light_overlay(engine, cam_x, cam_y, now)
            self.screen.blit(glow, (0, 0), special_flags=pygame.BLEND_RGB_MULT)

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

    def _paint_base(self, char: str, tiles, x: int, y: int) -> np.ndarray:
        mask_id = wall_neighbor_mask(tiles, x, y) if char in {"#", "W", '"'} else 0
        key = (char, mask_id, x & 7, y & 7)
        cached = self._base_rgb.get(key)
        if cached is not None:
            return cached
        rgb = paint_cell(char, mask_id, x, y)
        self._base_rgb[key] = rgb
        return rgb

    def _tile_surface(self, char, tiles, x, y):
        mask_id = wall_neighbor_mask(tiles, x, y) if char in {"#", "W", '"'} else 0
        key = (char, mask_id, x & 7, y & 7)
        cached = self._tile_cache.get(key)
        if cached is not None:
            return cached
        surf = self._scale(self._paint_base(char, tiles, x, y))
        if len(self._tile_cache) > 800:
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
        occupation = getattr(player, "class_name", None) or "без занятия"
        y = top + 8
        log_stop = hint_y - 4
        y = self._text(f"ДЕЛО · {occupation}", 12, y, PAPER, stop=log_stop)
        y = self._text(
            f"плоть {player.hp}/{player.max_hp}   воля {player.san}",
            12,
            y,
            RUST,
            stop=log_stop,
        )
        quest = ""
        if getattr(engine, "quest_system", None):
            desc = engine.quest_system.get_active_quest_descriptions(getattr(engine, "flags", None) or set())
            if desc:
                quest = desc[0]
        if quest:
            y = self._text(quest, 12, y, PAPER, width=68, stop=log_stop)
        for msg in list(getattr(engine, "messages", None) or [])[-2:]:
            y = self._text(msg, 12, y, ASH, width=68, stop=log_stop)
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
        self._text(hint, 12, hint_y + 4, SLATE, width=72, stop=WIN_H)

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
        if getattr(engine, "use_sprites", True) and player:
            oil = self._oil_surface(who_p, FIGHT_FACE_W, FIGHT_FACE_H)
            if oil is not None:
                self.screen.blit(oil, (8, 16))
        if getattr(engine, "use_sprites", True) and enemy:
            oil = self._oil_surface(getattr(enemy, "id", "") or "", FIGHT_FACE_W, FIGHT_FACE_H)
            if oil is not None:
                self.screen.blit(oil, (WIN_W - FIGHT_FACE_W - 8, 16))
        pygame.draw.rect(self.screen, SOOT, (0, MAP_H, WIN_W, HUD_H))
        pygame.draw.line(self.screen, SLATE, (0, MAP_H), (WIN_W, MAP_H))
        hint_y = WIN_H - HINT_H
        pygame.draw.line(self.screen, SLATE, (0, hint_y), (WIN_W, hint_y))
        y = MAP_H + 8
        y = self._text("СРЫВ", 12, y, BLOOD, stop=hint_y)
        if player:
            y = self._text(
                f"вы {player.hp}/{player.max_hp}  воля {player.san}",
                12,
                y,
                RUST,
                stop=hint_y,
            )
        if enemy:
            name = getattr(enemy, "name", "тень")
            hp = getattr(enemy, "hp", "?")
            mx = getattr(enemy, "max_hp", hp)
            y = self._text(f"{name}  {hp}/{mx}", 12, y, ASH, stop=hint_y)
        for msg in list(getattr(engine, "messages", None) or [])[-3:]:
            y = self._text(msg, 12, y, PAPER, width=70, stop=hint_y - 4)
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
        for y, row in enumerate(tiles):
            for x, char in enumerate(row):
                if char == "*":
                    flames.append((x, y, 5, 1.0))
                    for iy in range(rows):
                        for ix in range(cols):
                            add = max(0.0, 1.0 - math.hypot(ix - x, iy - y) / 5.0)
                            flame_g[iy, ix] += add
                            illum[iy, ix] += add * 0.35
                if char == "W":
                    for iy in range(rows):
                        for ix in range(cols):
                            add = max(0.0, 1.0 - math.hypot(ix - x, iy - y) / 4.0)
                            moon_g[iy, ix] += add
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
