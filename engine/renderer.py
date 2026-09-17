"""Отрисовка игры через tcod."""
import math
import random
import time
from typing import Dict, List

import tcod
from tcod import libtcodpy

from engine.constants import (
    LEGEND_WIDTH,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TILE_LEGEND,
    UNARMED_DAMAGE_DIE,
)
from engine.equipment import EQUIP_LAYOUT, EQUIP_SLOTS, empty_fill, slot_fill_name, worn_phrase
from engine.shop import buy_price, counter_item_value, kopeck_phrase, sell_price
from engine.clinic_tiles import TILE_HEIGHT, TILE_WIDTH, map_glyph, wall_glyph, wall_neighbor_mask
from engine.palette import INKS, explored_color_dicts, hex_to_rgb, visible_color_dicts
from engine.portraits import PORTRAIT_COLS, PORTRAIT_ROWS, load_pixels
from engine.paintings import (
    ITEM_LOOK_COLS,
    ITEM_LOOK_ROWS,
    LOCATION_OIL_COLS,
    LOCATION_OIL_ROWS,
    load_pixels as load_painting_pixels,
)


def load_oil_pixels(oil_id: str, item_type: str = ""):
    pixels = load_pixels(oil_id)
    if pixels is not None:
        return pixels
    return load_painting_pixels(oil_id, item_type)


def _fit_portrait_dest(box_x, box_y, box_w, box_h, src_w, src_h):
    """Вписать масло в клетку, не растягивая 3:4 в 16×24."""
    if src_w <= 0 or src_h <= 0 or box_w <= 0 or box_h <= 0:
        return (box_x, box_y, box_w, box_h)
    src_aspect = src_w / src_h
    box_aspect = box_w / box_h
    if src_aspect > box_aspect:
        draw_w = box_w
        draw_h = box_w / src_aspect
    else:
        draw_h = box_h
        draw_w = box_h * src_aspect
    return (
        box_x + (box_w - draw_w) / 2,
        box_y + (box_h - draw_h) / 2,
        draw_w,
        draw_h,
    )


def _ink(name: str):
    return libtcodpy.Color(*hex_to_rgb(INKS[name]))


COLOR_WALL = _ink("graphite")
COLOR_FLOOR = _ink("soot")
COLOR_PLAYER = _ink("linen")
COLOR_TEXT = _ink("ash")
COLOR_SANITY = _ink("blood")
COLOR_HP = _ink("rust")
COLOR_DIALOGUE = _ink("paper")
COLOR_UNKNOWN = libtcodpy.Color(0, 0, 0)
COLOR_VOID_FG = _ink("graphite")
COLOR_VOID_BG = _ink("void")
COLOR_CHART_BG = _ink("soot")
COLOR_MUTED = _ink("slate")
COLOR_LAMP = _ink("lamp")
_BLOOD_RGB = hex_to_rgb(INKS["blood"])
# Глифы вне ASCII, которые шрифт tcod всё же рисует.
_ALLOWED_UNICODE_GLYPHS = frozenset('≈±§¶')


class Camera:
    """Камера, следящая за игроком."""
    
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.x = 0
        self.y = 0
    
    def move_to(self, target_x: int, target_y: int, map_width: int, map_height: int):
        """Центрировать камеру на цели."""
        # Центрируем на игроке
        self.x = target_x - self.width // 2
        self.y = target_y - self.height // 2
        
        # Ограничиваем границами карты
        self.x = max(0, min(self.x, map_width - self.width))
        self.y = max(0, min(self.y, map_height - self.height))
    
    def world_to_screen(self, world_x: int, world_y: int) -> tuple:
        """Преобразовать мировые координаты в экранные."""
        return world_x - self.x, world_y - self.y
    
    def is_visible(self, world_x: int, world_y: int) -> bool:
        """Проверить, виден ли объект на экране."""
        screen_x, screen_y = self.world_to_screen(world_x, world_y)
        return 0 <= screen_x < self.width and 0 <= screen_y < self.height


class Renderer:
    """Отрисовщик игрового состояния."""
    
    def __init__(self, screen_width: int, screen_height: int, fov_system=None):
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.console = tcod.console.Console(screen_width, screen_height, order="F")
        
        # HUD занимает 8 строк снизу; легенда символов — справа.
        self.map_width = screen_width - LEGEND_WIDTH
        self.map_height = screen_height - 8
        self.legend_width = LEGEND_WIDTH
        
        # Камера
        self.camera = Camera(self.map_width, self.map_height)
        
        # Система видимости
        self.fov_system = fov_system    
        
        # Словари цветов (загружаются из БД через game_engine)
        self.tile_colors = {}
        self.tile_colors_explored = {}        

        # Ссылка на game_engine
        self.game_engine = None

        # Всполохи SAN: пауза / вспышка, не каждый кадр по всей карте.
        self._san_wait = 50
        self._san_hold = 0
        self._san_rim_marks = []
        self._console_render = None
        self._portrait_textures = {}
        self._pending_portraits = [] 
    def load_tile_colors_from_db(self, db_loader):
        """Загрузить цвета тайлов из БД."""
        try:
            self.tile_colors = db_loader.get_tile_colors()
            self.tile_colors_explored = db_loader.get_tile_colors_explored()
        except Exception as e:
            print(f"[WARNING] Не удалось загрузить цвета из БД: {e}")
            # Используем дефолтные цвета если таблица не существует
            self._set_default_tile_colors()
    
    def _set_default_tile_colors(self):
        """Фолбэк, если таблица цветов не загрузилась — те же 18 чернил."""
        self.tile_colors = visible_color_dicts()
        self.tile_colors_explored = explored_color_dicts()
    
    def _parse_hex_color(self, hex_str: str) -> libtcodpy.Color:
        """Преобразовать hex-строку '#RRGGBB' в Color."""
        if not hex_str or not hex_str.startswith('#'):
            return libtcodpy.Color(100, 100, 100)
        try:
            r = int(hex_str[1:3], 16)
            g = int(hex_str[3:5], 16)
            b = int(hex_str[5:7], 16)
            return libtcodpy.Color(r, g, b)
        except (ValueError, IndexError):
            return libtcodpy.Color(100, 100, 100)

    def _tile_glyph(self, char: str, x: int = None, y: int = None, tiles=None) -> str:
        """Картинка только на карте. Точка в речи остаётся точкой."""
        engine = self.game_engine
        if not engine or not getattr(engine, "use_sprites", True):
            return char
        tileset = getattr(engine, "clinic_tileset", None)
        if not getattr(tileset, "_clinic_sprites_ready", False):
            return char
        if char == "#" and tiles is not None and x is not None and y is not None:
            return wall_glyph(wall_neighbor_mask(tiles, x, y))
        return map_glyph(char, True)
    
    def _get_tile_color(self, char: str, is_visible: bool, is_explored: bool):
        """Получить цвет для символа тайла из БД."""
        # Неисследованная клетка — чёрная
        if not is_visible and not is_explored:
            return libtcodpy.Color(0, 0, 0), libtcodpy.Color(0, 0, 0)
        
        # Выбираем словарь: видимый или исследованный
        colors_dict = self.tile_colors if is_visible else self.tile_colors_explored
        
        # Ищем цвет по символу
        if char in colors_dict:
            fg = self._parse_hex_color(colors_dict[char]['fg'])
            bg = self._parse_hex_color(colors_dict[char]['bg'])
            return fg, bg
        
        # Фолбэк: если символа нет в таблице
        return libtcodpy.Color(100, 100, 100), libtcodpy.Color(50, 50, 50)

    def _shade_color(self, color, shade: float):
        shade = max(0.0, min(1.0, shade))
        return libtcodpy.Color(
            int(color.r * shade),
            int(color.g * shade),
            int(color.b * shade),
        )

    def _mix_color(self, color, other, amount: float):
        t = max(0.0, min(1.0, amount))
        return libtcodpy.Color(
            int(color.r * (1.0 - t) + other.r * t),
            int(color.g * (1.0 - t) + other.g * t),
            int(color.b * (1.0 - t) + other.b * t),
        )

    def _flame_flicker_at(self, x: int, y: int, now: float) -> float:
        """Тот же синус, что у глифа лампы: 0.72–1.0, в такт источнику."""
        flames = getattr(self.fov_system, 'flames', None) or ()
        total = 0.0
        mixed = 0.0
        for sx, sy, radius, intensity in flames:
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
    def clear(self):
        self.console.clear()
    
    def set_camera_position(self, player_x: int, player_y: int, map_width: int, map_height: int):
        """Обновить позицию камеры."""
        self.camera.move_to(player_x, player_y, map_width, map_height)
    
    def draw_map(self, tiles):
        """Отрисовка карты. Низкий SAN — край зрения, не скрембл клеток."""
        map_height = len(tiles)
        map_width = len(tiles[0]) if map_height > 0 else 0

        # Край карты (57 клеток vs окно 60) и туман войны — не чёрный «пол».
        for sy in range(self.map_height):
            for sx in range(self.map_width):
                self.console.print(
                    sx, sy, ':', fg=COLOR_VOID_FG, bg=COLOR_VOID_BG
                )

        now = time.perf_counter()

        for y in range(map_height):
            for x in range(map_width):
                if not self.camera.is_visible(x, y):
                    continue

                screen_x, screen_y = self.camera.world_to_screen(x, y)

                if not (0 <= screen_x < self.map_width and 0 <= screen_y < self.map_height):
                    continue

                char = tiles[y][x]

                is_visible = self.fov_system and self.fov_system.is_visible(x, y)
                is_explored = self.fov_system and self.fov_system.is_explored(x, y)
                if not is_visible and not is_explored:
                    continue

                fg, bg = self._get_tile_color(char, is_visible, is_explored)

                if is_visible and self.fov_system:
                    light = self.fov_system.get_illumination(x, y)
                    flame = self.fov_system.get_flame_illumination(x, y)
                    moon = self.fov_system.get_window_illumination(x, y)
                    shade = 0.22 + 0.78 * min(1.0, light / 1.15)
                    if flame > 0.02:
                        share = min(1.0, flame / max(light, 0.02))
                        flicker = self._flame_flicker_at(x, y, now)
                        shade *= 1.0 - share * (1.0 - flicker)
                    fg = self._shade_color(fg, shade)
                    bg = self._shade_color(bg, shade)
                    if moon > 0.02:
                        frost_share = min(1.0, moon / max(light, 0.02))
                        if flame > 0.02:
                            frost_share *= max(
                                0.0,
                                1.0 - min(1.0, flame / max(light, 0.02)),
                            )
                        if frost_share > 0.03:
                            fg = self._mix_color(fg, _ink("frost"), 0.55 * frost_share)
                            bg = self._mix_color(bg, _ink("ice"), 0.40 * frost_share)

                self.console.print(
                    screen_x, screen_y, self._tile_glyph(char, x, y, tiles), fg=fg, bg=bg
                )

        self._draw_sanity_periphery(tiles, map_width, map_height)

    def _sanity_level(self) -> int:
        if not self.game_engine or not self.game_engine.san_system:
            return 0
        return int(self.game_engine.san_system.hallucination_level)

    def _player_xy(self):
        player = getattr(self.game_engine, 'player', None) if self.game_engine else None
        if player is None:
            return None
        return player.x, player.y

    def _cell_rgb(self, sx: int, sy: int):
        bg = self.console.bg[sx, sy]
        return int(bg[0]), int(bg[1]), int(bg[2])

    def _paint_rim_bg(self, sx: int, sy: int, heat: float) -> None:
        r, g, b = self._cell_rgb(sx, sy)
        self.console.bg[sx, sy] = (
            min(255, int(r * (1 - heat) + _BLOOD_RGB[0] * heat)),
            min(255, int(g * (1 - heat) + _BLOOD_RGB[1] * heat)),
            min(255, int(b * (1 - heat) + _BLOOD_RGB[2] * heat)),
        )

    def _collect_vision_rim(self, tiles, map_width: int, map_height: int) -> list:
        """Край FOV и край панели карты. Центр зрения не трогаем."""
        origin = self._player_xy()
        rim = []
        for y in range(map_height):
            for x in range(map_width):
                if not self.camera.is_visible(x, y):
                    continue
                if not (self.fov_system and self.fov_system.is_visible(x, y)):
                    continue
                sx, sy = self.camera.world_to_screen(x, y)
                if not (0 <= sx < self.map_width and 0 <= sy < self.map_height):
                    continue
                if origin is not None:
                    if max(abs(x - origin[0]), abs(y - origin[1])) <= 3:
                        continue
                at_fov_edge = False
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < map_width and 0 <= ny < map_height):
                        at_fov_edge = True
                        break
                    if not self.fov_system.is_visible(nx, ny):
                        at_fov_edge = True
                        break
                at_panel_edge = (
                    sx <= 1
                    or sy <= 1
                    or sx >= self.map_width - 2
                    or sy >= self.map_height - 2
                )
                if at_fov_edge or at_panel_edge:
                    rim.append((sx, sy))
        return rim

    def _pick_rim_marks(self, rim: list, level: int) -> list:
        if not rim:
            return []
        want = {1: 6, 2: 11, 3: 16, 4: 22}.get(level, 6)
        want = min(len(rim), want)
        chosen = random.sample(rim, want)
        marks = []
        for i, (sx, sy) in enumerate(chosen):
            kind = 'flash'
            if level >= 2 and i % 4 == 0:
                kind = 'glyph'
            if level >= 4 and i == 0:
                kind = 'figure'
            marks.append((sx, sy, kind))
        return marks

    def _paint_san_marks(self, level: int) -> None:
        heat = {1: 0.28, 2: 0.38, 3: 0.48, 4: 0.58}.get(level, 0.3)
        for sx, sy, kind in self._san_rim_marks:
            if not (0 <= sx < self.map_width and 0 <= sy < self.map_height):
                continue
            self._paint_rim_bg(sx, sy, heat)
            if kind == 'glyph':
                self.console.print(
                    sx, sy, self._tile_glyph('≈'), fg=libtcodpy.Color(160, 70, 65)
                )
            elif kind == 'figure':
                self.console.print(
                    sx, sy, self._tile_glyph('&'), fg=libtcodpy.Color(95, 70, 72)
                )

    def _draw_sanity_vignette(self, level: int) -> None:
        """Тихая кайма панели: не мигает, не закрывает центр."""
        if level <= 0:
            return
        origin = self._player_xy()
        player_screen = (
            self.camera.world_to_screen(*origin) if origin is not None else None
        )
        width = 1 if level < 3 else 2
        heat = 0.12 + 0.04 * level
        for sy in range(self.map_height):
            for sx in range(self.map_width):
                if (
                    sx >= width
                    and sy >= width
                    and sx < self.map_width - width
                    and sy < self.map_height - width
                ):
                    continue
                if player_screen is not None:
                    if max(abs(sx - player_screen[0]), abs(sy - player_screen[1])) <= 3:
                        continue
                self._paint_rim_bg(sx, sy, heat)

    def _draw_sanity_periphery(self, tiles, map_width: int, map_height: int) -> None:
        level = self._sanity_level()
        if level <= 0:
            self._san_wait = 50
            self._san_hold = 0
            self._san_rim_marks = []
            return

        self._draw_sanity_vignette(level)

        gap = {1: 110, 2: 78, 3: 52, 4: 36}.get(level, 80)
        hold = {1: 9, 2: 11, 3: 13, 4: 15}.get(level, 10)

        if self._san_hold > 0:
            self._paint_san_marks(level)
            self._san_hold -= 1
            if self._san_hold == 0:
                self._san_wait = gap
                self._san_rim_marks = []
            return

        if self._san_wait > 0:
            self._san_wait -= 1
            return

        rim = self._collect_vision_rim(tiles, map_width, map_height)
        self._san_rim_marks = self._pick_rim_marks(rim, level)
        self._san_hold = hold
        self._paint_san_marks(level)

    def draw_entities(self, entities):
        """Отрисовка сущностей (NPC, предметов)."""
        # Сначала рисуем предметы (записки)
        for entity in entities:
            if hasattr(entity, 'type') and entity.type == 'note':
                self._draw_entity(entity)
        
        # Потом рисуем NPC (они поверх предметов)
        for entity in entities:
            if not (hasattr(entity, 'type') and entity.type == 'note'):
                self._draw_entity(entity)
    
    def _safe_glyph(self, symbol) -> str:
        """Символ, который шрифт терминала точно нарисует."""
        if not symbol:
            return '&'
        ch = str(symbol)[0]
        code = ord(ch)
        if 33 <= code <= 126 or ch in _ALLOWED_UNICODE_GLYPHS:
            return ch
        return '&'

    def _draw_entity(self, entity):
        """Отрисовать одну сущность."""
        in_fov = self.fov_system and self.fov_system.is_visible(entity.x, entity.y)
        adjacent = False
        player = getattr(self.game_engine, 'player', None) if self.game_engine else None
        if player is not None:
            adjacent = abs(entity.x - player.x) + abs(entity.y - player.y) <= 1
        if not in_fov and not adjacent:
            return
        
        if not self.camera.is_visible(entity.x, entity.y):
            return
        
        screen_x, screen_y = self.camera.world_to_screen(entity.x, entity.y)
        
        if 0 <= screen_x < self.map_width and 0 <= screen_y < self.map_height:
            symbol = self._tile_glyph(self._safe_glyph(getattr(entity, 'symbol', '?')))
            color = getattr(entity, 'color', libtcodpy.Color(255, 255, 255))
            
            self.console.print(
                screen_x, screen_y,
                symbol,
                fg=color
            )
                
    def draw_player(self, player):
        """Отрисовка игрока."""
        if not self.camera.is_visible(player.x, player.y):
            return
        
        screen_x, screen_y = self.camera.world_to_screen(player.x, player.y)
        
        if 0 <= screen_x < self.map_width and 0 <= screen_y < self.map_height:
            self.console.print(
                screen_x, screen_y,
                self._tile_glyph(player.symbol),
                fg=COLOR_PLAYER
            )
    
  
    def draw_messages(self, messages: List[str]):
        """Лог живёт в карте больного (draw_hud). Вызов оставлен."""
        return

    def draw_hud(self, player):
        """Нижняя карта больного: плоть, воля, долг, показания."""
        hud_y = self.map_height
        hud_h = self.screen_height - hud_y
        if hud_h < 4 or not player:
            return
        inner = max(8, self.screen_width - 4)
        engine = self.game_engine
        state = getattr(engine, "state", None)
        in_fight = state in ("combat", "ability_menu")
        occupation = getattr(player, "class_name", None) or "без занятия"
        title = f"ДЕЛО · {occupation}"
        self._draw_box(
            0, hud_y, self.screen_width, hud_h, title=title, bg=COLOR_CHART_BG
        )

        flesh = (
            f"плоть {self._hp_bar(player.hp, player.max_hp, 10)} "
            f"{player.hp}/{player.max_hp}"
        )
        will = f"воля {self._hp_bar(player.san, player.max_san, 10)} {player.san}"
        self.console.print(2, hud_y + 1, flesh[:inner], fg=COLOR_HP)
        will_w = max(8, self.screen_width - 42)
        self.console.print(40, hud_y + 1, will[:will_w], fg=COLOR_SANITY)

        quest_line = ""
        if in_fight:
            quest_line = "Срыв. Ряды в кадре."
        elif engine and getattr(engine, "quest_system", None):
            flags = getattr(engine, "flags", None) or set()
            desc = engine.quest_system.get_active_quest_descriptions(flags)
            if desc:
                quest_line = desc[0]
        marks = player.chart_marks() if hasattr(player, "chart_marks") else ""
        chart_note = quest_line
        if marks:
            chart_note = f"{quest_line} · {marks}" if quest_line else marks

        y = hud_y + 2
        bottom = self.screen_height - 2
        if chart_note:
            for line in self._wrap_text(chart_note, inner)[:2]:
                if y > bottom:
                    break
                self.console.print(2, y, line[:inner], fg=COLOR_DIALOGUE)
                y += 1

        if y <= bottom:
            self.console.print(1, y, "─" * (self.screen_width - 2), fg=COLOR_MUTED)
            y += 1

        messages = list(getattr(engine, "messages", None) or [])[-3:]
        if in_fight:
            messages = []
        log_lines = []
        for msg in messages:
            log_lines.extend(self._wrap_text(msg, inner) or [""])
        room = max(0, bottom - y + 1)
        for line in log_lines[-room:] if room else []:
            self.console.print(2, y, line[:inner], fg=COLOR_TEXT)
            y += 1

        if in_fight:
            hint = "1 удар · 2 глагол · 3 бежать"
        else:
            hand = "кулак"
            eq = getattr(player, "equipped_weapon_id", None)
            if eq:
                for item in getattr(player, "inventory", None) or []:
                    if getattr(item, "id", None) == eq:
                        hand = getattr(item, "name", "нож") or "нож"
                        break
            hint = f"в руке {hand} · ход · e стол · i карман · t тетрадь · c на себе · ? поля"
        self.console.print(2, self.screen_height - 1, hint[:inner], fg=COLOR_MUTED)

    def draw_quests(self, quest_descriptions: List[str]):
        """Долг живёт в карте больного. На карту не пишем."""
        return

    def draw_dialogue(self, text: str, speaker_name: str = '', choices=None,
                      portrait_id: str = '', check_line: str = ''):
        """Окно диалога, при необходимости — бюст слева и варианты ответа."""
        if not text and not choices:
            return

        choices = choices or []
        show_face = bool(portrait_id) and getattr(
            self.game_engine, "use_sprites", True
        )
        if show_face and load_pixels(portrait_id) is None:
            show_face = False

        box_width = self.screen_width - 4
        text_x = 4
        wrap_width = box_width - 4
        if show_face:
            text_x = 4 + PORTRAIT_COLS + 1
            wrap_width = box_width - PORTRAIT_COLS - 3
        wrap_width = max(12, wrap_width)

        wrapped = self._wrap_text(text or '', wrap_width)
        banner_lines = self._wrap_text(check_line, wrap_width) if check_line else []
        choice_blocks = [
            self._wrap_choice(choice, i, wrap_width) for i, choice in enumerate(choices)
        ]
        interior = len(wrapped) + len(banner_lines) + sum(len(block) for block in choice_blocks)
        if interior < 1:
            interior = 1
        box_height = interior + 2
        if show_face:
            box_height = max(box_height, PORTRAIT_ROWS + 2)
        max_h = max(5, self.screen_height - 3)
        box_height = min(box_height, max_h)
        box_y = max(1, self.map_height - box_height - 1)
        if box_y + box_height >= self.screen_height:
            box_y = max(1, self.screen_height - box_height - 1)

        self._draw_box(2, box_y, box_width, box_height, title=speaker_name)

        y = box_y + 1
        bottom = box_y + box_height - 2
        for line in wrapped:
            if y > bottom:
                break
            self.console.print(text_x, y, line[:wrap_width], fg=COLOR_DIALOGUE)
            y += 1
        for line in banner_lines:
            if y > bottom:
                break
            self.console.print(text_x, y, line[:wrap_width], fg=COLOR_LAMP)
            y += 1
        for i, block in enumerate(choice_blocks):
            stripped = (choices[i] or "").lstrip()
            tagged = stripped.startswith("[") or stripped.startswith("(")
            fg = COLOR_LAMP if tagged else COLOR_DIALOGUE
            for line in block:
                if y > bottom:
                    break
                self.console.print(text_x, y, line[:wrap_width], fg=fg)
                y += 1

        if choices:
            hint = f"[1-{len(choices)} — ответ]"
        else:
            hint = "[Space — далее]"
        self.console.print(self.screen_width - len(hint) - 4, box_y + box_height - 1,
            hint, fg=COLOR_TEXT)

        if show_face:
            self._pending_portraits.append(
                (portrait_id, (3, box_y + 1, PORTRAIT_COLS, PORTRAIT_ROWS))
            )

    def _choice_tokens(self, text: str) -> List[str]:
        """Слова и метки [...] / (...) не рвать посередине."""
        tokens = []
        i = 0
        n = len(text or "")
        while i < n:
            if text[i].isspace():
                i += 1
                continue
            if text[i] in "[(":
                close = "]" if text[i] == "[" else ")"
                end = text.find(close, i + 1)
                if end < 0:
                    tokens.append(text[i:])
                    break
                tokens.append(text[i : end + 1])
                i = end + 1
                continue
            j = i + 1
            while j < n and (not text[j].isspace()) and text[j] not in "[(":
                j += 1
            tokens.append(text[i:j])
            i = j
        return tokens

    def _wrap_tokens(self, tokens: List[str], width: int) -> List[str]:
        width = max(1, width)
        lines = []
        current = []
        current_len = 0
        for token in tokens:
            if len(token) > width:
                if current:
                    lines.append(" ".join(current))
                    current = []
                    current_len = 0
                for start in range(0, len(token), width):
                    chunk = token[start : start + width]
                    if len(chunk) == width:
                        lines.append(chunk)
                    else:
                        current = [chunk]
                        current_len = len(chunk)
                continue
            add = len(token) if not current else len(token) + 1
            if current and current_len + add > width:
                lines.append(" ".join(current))
                current = [token]
                current_len = len(token)
            else:
                current.append(token)
                current_len += add
        if current:
            lines.append(" ".join(current))
        return lines

    def _wrap_choice(self, choice: str, index: int, width: int) -> List[str]:
        """Полный ответ с переносом. Метки не режем троеточием."""
        head = f"{index + 1}. "
        body_width = max(8, width - len(head))
        wrapped = self._wrap_tokens(self._choice_tokens(choice), body_width)
        if not wrapped:
            wrapped = [""]
        pad = " " * len(head)
        return [head + wrapped[0]] + [pad + line for line in wrapped[1:]]

    def _hp_bar(self, current: int, maximum: int, width: int = 12) -> str:
        maximum = max(1, int(maximum or 1))
        filled = max(0, min(width, int(round(width * max(0, current) / maximum))))
        return "#" * filled + "-" * (width - filled)

    def _fill_rect(self, x: int, y: int, w: int, h: int, bg):
        for yy in range(y, y + h):
            if yy < 0 or yy >= self.screen_height:
                continue
            for xx in range(x, x + w):
                if 0 <= xx < self.screen_width:
                    self.console.bg[xx, yy] = bg

    def _draw_box(self, x: int, y: int, w: int, h: int, title: str = "", fg=None, bg=None):
        """Бумажная рамка дела. Без новых чернил."""
        fg = fg or COLOR_DIALOGUE
        if bg is not None:
            self._fill_rect(x, y, w, h, bg)
        inner = max(0, w - 2)
        label = f" {title} " if title else ""
        if label and len(label) <= inner:
            top = "┌" + label + "─" * (inner - len(label)) + "┐"
        else:
            top = "┌" + "─" * inner + "┐"
        self.console.print(x, y, top[:w], fg=fg)
        for i in range(1, h - 1):
            self.console.print(x, y + i, "│" + " " * inner + "│", fg=fg)
        self.console.print(x, y + h - 1, "└" + "─" * inner + "┘", fg=fg)

    def _draw_silhouette(self, x: int, y: int, w: int, h: int):
        """Тень без лица: халат, не gore."""
        for row in range(h):
            if row < 2:
                pad = max(1, w // 3)
            elif row < 4:
                pad = max(1, w // 5)
            else:
                pad = 1
            span = max(1, w - 2 * pad)
            start = x + (w - span) // 2
            glyph = "@" if row < 3 else "#"
            for cx in range(start, start + span):
                if 0 <= cx < self.screen_width and 0 <= y + row < self.screen_height:
                    self.console.print(
                        cx, y + row, glyph, fg=COLOR_SANITY, bg=COLOR_VOID_BG
                    )

    def _queue_face(self, portrait_id: str, box):
        if not portrait_id or not getattr(self.game_engine, "use_sprites", True):
            return False
        if load_pixels(portrait_id) is None:
            return False
        self._pending_portraits.append((portrait_id, box))
        return True

    def _queue_oil(self, oil_id: str, box, item_type: str = ""):
        if not oil_id or not getattr(self.game_engine, "use_sprites", True):
            return False
        if load_oil_pixels(oil_id, item_type) is None:
            return False
        self._pending_portraits.append((oil_id, box))
        return True

    def draw_fight_scene(self, player, enemy, messages=None):
        """Коридор гаснет. Две фигуры, кость, SAN. То же окно tcod."""
        stage_w = self.screen_width - 2
        stage_h = max(16, self.map_height - 1)
        for y in range(stage_h):
            for x in range(self.screen_width):
                self.console.print(x, y, " ", fg=COLOR_VOID_FG, bg=COLOR_VOID_BG)

        self.console.print(1, 1, "┌" + "─" * (stage_w - 2) + "┐", fg=COLOR_DIALOGUE)
        for i in range(2, stage_h - 1):
            self.console.print(1, i, "│" + " " * (stage_w - 2) + "│", fg=COLOR_DIALOGUE)
        self.console.print(
            1, stage_h - 1, "└" + "─" * (stage_w - 2) + "┘", fg=COLOR_DIALOGUE
        )
        title = "[ СРЫВ ]"
        self.console.print(
            1 + (stage_w - len(title)) // 2, 1, title, fg=COLOR_SANITY
        )

        left = (3, 3, PORTRAIT_COLS, PORTRAIT_ROWS)
        right = (
            stage_w - PORTRAIT_COLS - 1,
            3,
            PORTRAIT_COLS,
            PORTRAIT_ROWS,
        )
        player_id = getattr(player, "id", "") if player else ""
        enemy_id = getattr(enemy, "id", "") if enemy else ""
        if not self._queue_face(player_id, left):
            self._draw_silhouette(*left)
        if enemy_id and not self._queue_face(enemy_id, right):
            self._draw_silhouette(*right)
        elif not enemy_id:
            self._draw_silhouette(*right)

        you = getattr(player, "class_name", None) or getattr(player, "name", "Вы")
        foe = getattr(enemy, "name", "Тень") if enemy else "—"
        self.console.print(3, 3 + PORTRAIT_ROWS + 1, you[:PORTRAIT_COLS], fg=COLOR_PLAYER)
        self.console.print(
            right[0], 3 + PORTRAIT_ROWS + 1, foe[:PORTRAIT_COLS], fg=COLOR_SANITY
        )

        mid_x = 3 + PORTRAIT_COLS + 2
        mid_w = max(12, right[0] - mid_x - 1)
        you_hp = getattr(player, "hp", 0) if player else 0
        you_max = getattr(player, "max_hp", 1) if player else 1
        foe_hp = getattr(enemy, "hp", 0) if enemy else 0
        foe_max = getattr(enemy, "max_hp", 1) if enemy else 1
        self.console.print(mid_x, 4, f"Вы {self._hp_bar(you_hp, you_max)} {you_hp}/{you_max}", fg=COLOR_HP)
        self.console.print(
            mid_x, 6, f"{foe[:10]} {self._hp_bar(foe_hp, foe_max)} {foe_hp}/{foe_max}",
            fg=COLOR_SANITY,
        )
        san = getattr(player, "san", None)
        if san is not None:
            self.console.print(mid_x, 8, f"SAN {san}", fg=COLOR_SANITY)
        engine = self.game_engine
        penalty = 0
        if engine and getattr(engine, "san_system", None):
            penalty = engine.san_system.get_combat_penalty()
        if penalty:
            self.console.print(mid_x, 9, f"штраф кости {penalty}", fg=COLOR_TEXT)

        log = list(messages or [])[-3:]
        y = 11
        for msg in log:
            for line in self._wrap_text(msg, mid_w)[:2]:
                if y >= stage_h - 6:
                    break
                self.console.print(mid_x, y, line[:mid_w], fg=COLOR_DIALOGUE)
                y += 1

        verb = "—"
        if player and getattr(player, "class_ability", None):
            verb = (player.class_ability.get("name") or "Глагол")[:28]
        ranks = (
            "1  Удар · d20",
            f"2  {verb}",
            "3  Бежать",
        )
        rank_y = stage_h - 1 - len(ranks)
        for i, line in enumerate(ranks):
            self.console.print(3, rank_y + i, line[: stage_w - 4], fg=COLOR_TEXT)

    def draw_ability_menu(self, player, selected_index: int = 0):
        """Окно меню способностей в бою."""
        if not player or not player.class_ability:
            return
        
        ability = player.class_ability
        box_width = 60
        box_height = 12
        box_x = (self.screen_width - box_width) // 2
        box_y = (self.screen_height - box_height) // 2
        
        # Рисуем рамку
        self.console.print(box_x, box_y, '┌' + '─' * (box_width - 2) + '┐', fg=COLOR_DIALOGUE)
        for i in range(1, box_height - 1):
            self.console.print(box_x, box_y + i, '│' + ' ' * (box_width - 2) + '│', fg=COLOR_DIALOGUE)
        self.console.print(box_x, box_y + box_height - 1, '└' + '─' * (box_width - 2) + '┘', fg=COLOR_DIALOGUE)
        
        # Заголовок
        title = "[ СПОСОБНОСТИ КЛАССА ]"
        self.console.print(box_x + (box_width - len(title)) // 2, box_y, title, fg=COLOR_DIALOGUE)
        
        # Название способности
        ability_name = ability.get('name', 'Неизвестная способность')
        self.console.print(box_x + 2, box_y + 2, f"Название: {ability_name}", fg=COLOR_LAMP)
        
        # Описание
        description = ability.get('description', 'Нет описания')
        wrapped_desc = self._wrap_text(description, box_width - 6)
        for i, line in enumerate(wrapped_desc[:4]):
            self.console.print(box_x + 4, box_y + 4 + i, line, fg=COLOR_TEXT)
        
        # Стоимость SAN
        san_cost = ability.get('san_cost', 0)
        if san_cost > 0:
            self.console.print(box_x + 4, box_y + 9, f"Стоимость: {san_cost} SAN", fg=COLOR_SANITY)
        else:
            self.console.print(box_x + 4, box_y + 9, "Стоимость: бесплатно", fg=COLOR_MUTED)
        
        # Эффект
        effect_type = ability.get('type', '')
        effect_map = {
            'combat_buff': f"+{ability.get('damage_bonus', 0)} к урону на {ability.get('duration', 1)} ход(а)",
            'critical_strike': "Следующий удар будет критическим",
            'sanity_restore': f"+{ability.get('san_restore', 0)} SAN, иммунитет к безумию" if ability.get('madness_immunity') else f"+{ability.get('san_restore', 0)} SAN",
        }
        effect_text = effect_map.get(effect_type, "Неизвестный эффект")
        self.console.print(box_x + 4, box_y + 10, f"Эффект: {effect_text}", fg=COLOR_TEXT)
        
        # Подсказки
        hints = "[Space — использовать] [Esc — отмена]"
        self.console.print(box_x + (box_width - len(hints)) // 2, box_y + box_height - 1, hints, fg=COLOR_DIALOGUE)
        
        # Текущий SAN игрока
        san_info = f"Ваш SAN: {player.san}/{player.max_san}"
        self.console.print(box_x + 4, box_y + box_height - 2, san_info, fg=COLOR_SANITY)


    def draw_ending(self, title: str, body: str):
        """Финальный экран новеллы."""
        for y in range(self.screen_height):
            for x in range(self.screen_width):
                self.console.bg[x, y] = COLOR_VOID_BG
        self.console.print(
            self.screen_width // 2 - len(title) // 2,
            self.screen_height // 2 - 4,
            title,
            fg=COLOR_DIALOGUE,
        )
        wrapped = self._wrap_text(body, self.screen_width - 16)
        body_y = self.screen_height // 2 - 2
        for i, line in enumerate(wrapped[:9]):
            self.console.print(
                self.screen_width // 2 - len(line) // 2,
                body_y + i,
                line,
                fg=COLOR_TEXT,
            )
        hint = "[Enter / Esc — выход]"
        self.console.print(
            self.screen_width // 2 - len(hint) // 2,
            body_y + 11,
            hint,
            fg=COLOR_MUTED,
        )
    
    def _wrap_text(self, text: str, width: int):
        """Перенос по ширине. Длинное слово режется, строка рамку не ест."""
        words = (text or "").split()
        if not words:
            return []
        return self._wrap_tokens(words, width)
    
    def draw_class_selection(self, classes, selected_index: int, has_save: bool = False):
        """Экран выбора класса."""
        self.console.clear()
        self._fill_rect(0, 0, self.screen_width, self.screen_height, COLOR_VOID_BG)
        self._draw_box(6, 3, self.screen_width - 12, 6, title="ДЕЛО")
        title = "ПЕТЕРБУРГ. КЛИНИКА. БРЕД."
        subtitle = "Кем вы были до пробуждения."
        self.console.print(
            self.screen_width // 2 - len(title) // 2, 5, title, fg=COLOR_LAMP
        )
        self.console.print(
            self.screen_width // 2 - len(subtitle) // 2, 7, subtitle, fg=COLOR_TEXT
        )
        
        for i, cls in enumerate(classes):
            y = 12 + i * 8
            marker = '▶ ' if i == selected_index else '  '
            color = COLOR_DIALOGUE if i == selected_index else COLOR_TEXT
            
            self.console.print(10, y, f"{marker}{cls['name']}", fg=color)
            self.console.print(12, y + 1, cls['description'], fg=COLOR_TEXT)
            
            # Характеристики
            stats = cls['base_stats']
            stats_str = ' '.join([f"{k}:{v}" for k, v in stats.items()])
            self.console.print(12, y + 2, stats_str, fg=COLOR_TEXT)
        
        hint = "↑/↓ — выбор | Enter — новая ночь"
        if has_save:
            hint += " | C — продолжить"
        self.console.print(10, self.screen_height - 3, hint, fg=COLOR_MUTED)

    def present(self, context):
        """Вывод кадра. keep_aspect держит шаг буквы; масло — поверх консоли."""
        renderer = getattr(context, "sdl_renderer", None)
        atlas = getattr(context, "sdl_atlas", None)
        pending = list(self._pending_portraits)
        self._pending_portraits = []
        if renderer is None or atlas is None:
            context.present(
                self.console,
                keep_aspect=True,
                integer_scaling=False,
            )
            return
        try:
            self._present_with_oil(context, renderer, atlas, pending)
        except Exception:
            context.present(
                self.console,
                keep_aspect=True,
                integer_scaling=False,
            )

    def _present_with_oil(self, context, renderer, atlas, pending):
        import tcod.render

        if self._console_render is None:
            self._console_render = tcod.render.SDLConsoleRender(atlas)
        renderer.draw_color = (0, 0, 0, 255)
        renderer.clear()
        console_tex = self._console_render.render(self.console)
        window = context.sdl_window
        ww, wh = window.size
        scale = min(
            ww / (self.screen_width * TILE_WIDTH),
            wh / (self.screen_height * TILE_HEIGHT),
        )
        draw_w = self.screen_width * TILE_WIDTH * scale
        draw_h = self.screen_height * TILE_HEIGHT * scale
        ox = (ww - draw_w) / 2
        oy = (wh - draw_h) / 2
        renderer.copy(console_tex, dest=(ox, oy, draw_w, draw_h))
        for item in pending or ():
            if not item:
                continue
            portrait_id, (tx, ty, tw, th) = item
            cached = self._portrait_textures.get(portrait_id)
            texture = src_w = src_h = None
            if isinstance(cached, tuple) and len(cached) == 3:
                texture, src_w, src_h = cached
            if texture is None:
                pixels = load_oil_pixels(portrait_id)
                if pixels is not None:
                    src_h, src_w = int(pixels.shape[0]), int(pixels.shape[1])
                    texture = renderer.upload_texture(pixels)
                    self._portrait_textures[portrait_id] = (texture, src_w, src_h)
            if texture is not None and src_w and src_h:
                box_x = ox + tx * TILE_WIDTH * scale
                box_y = oy + ty * TILE_HEIGHT * scale
                box_w = tw * TILE_WIDTH * scale
                box_h = th * TILE_HEIGHT * scale
                dest = _fit_portrait_dest(box_x, box_y, box_w, box_h, src_w, src_h)
                renderer.copy(texture, dest=dest)
        renderer.present()

    def is_light_source_visible(self, light_x: int, light_y: int, 
                                  light_radius: int, player_x: int, player_y: int,
                                  player_fov_radius: int) -> bool:
        """
        Проверить, виден ли источник света.
        Условие: расстояние между игроком и источником < сумма радиусов FOV и освещения.
        """
        # Рассчитываем расстояние
        dx = abs(light_x - player_x)
        dy = abs(light_y - player_y)
        distance = math.sqrt(dx * dx + dy * dy)
        
        # Источник виден, если расстояние меньше суммы радиусов
        return distance < (player_fov_radius + light_radius)
        
    def draw_light_sources(self, light_sources: List[Dict], 
                            player_x: int, player_y: int, 
                            player_fov_radius: int = 7):
        """Отрисовать видимые источники света."""
        for light in light_sources:
            light_x = light['x']
            light_y = light['y']
            light_radius = light.get('radius', 5)
            intensity = light.get('intensity', 1.0)
            flicker = light.get('flicker', False)
            
            # Проверяем видимость источника
            if not self.is_light_source_visible(
                light_x, light_y, light_radius, 
                player_x, player_y, player_fov_radius
            ):
                continue
            
            if not self.fov_system or not self.fov_system.is_visible(light_x, light_y):
                continue
            
            if not self.camera.is_visible(light_x, light_y):
                continue
            
            screen_x, screen_y = self.camera.world_to_screen(light_x, light_y)
            if not (0 <= screen_x < self.map_width and 0 <= screen_y < self.map_height):
                continue
            
            # Парсинг цвета
            color_str = light.get('color', '#ffaa00')
            r = int(color_str[1:3], 16)
            g = int(color_str[3:5], 16)
            b = int(color_str[5:7], 16)
            
            # ← НОВОЕ: Применяем интенсивность
            r = int(r * intensity)
            g = int(g * intensity)
            b = int(b * intensity)
            
            # Мерцание
            if flicker:
                flicker_factor = random.uniform(0.85, 1.0)
                r = int(r * flicker_factor)
                g = int(g * flicker_factor)
                b = int(b * flicker_factor)
            
            symbol = self._tile_glyph(light.get('symbol', '*'))
            self.console.print(
                screen_x, screen_y,
                symbol,
                fg=libtcodpy.Color(r, g, b)
            )
            
    def draw_legend(self):
        """Поля карты: расшифровка справа, чернила из палитры."""
        x0 = self.map_width
        width = self.legend_width
        self._fill_rect(x0, 0, width, self.map_height, COLOR_VOID_BG)
        for y in range(self.map_height):
            self.console.print(x0, y, "│", fg=COLOR_MUTED)

        self.console.print(x0 + 2, 1, "на полях", fg=COLOR_DIALOGUE)
        self.console.print(x0 + 1, 2, "─" * (width - 2), fg=COLOR_MUTED)

        y = 4
        for symbol, short, _long in TILE_LEGEND:
            if y >= self.map_height - 3:
                break
            fg, _bg = self._get_tile_color(symbol, True, True)
            if symbol == "@":
                fg = COLOR_PLAYER
            self.console.print(x0 + 2, y, self._tile_glyph(symbol), fg=fg)
            label = short
            if len(label) > width - 6:
                label = label[: width - 6]
            self.console.print(x0 + 4, y, label, fg=COLOR_TEXT)
            y += 1

        mode = "буквы" if getattr(self.game_engine, "use_sprites", True) else "тайлы"
        self.console.print(x0 + 2, self.map_height - 2, f"? · F4 {mode}", fg=COLOR_MUTED)

    def draw_help(self):
        """Поля карты и ход ночи."""
        self._fill_rect(0, 0, self.screen_width, self.screen_height, COLOR_VOID_BG)
        controls = [
            "ход — стрелки / hjkl",
            "1–9 — ответ в разговоре",
            "e — стол, дверь, речь",
            "a — удар рядом · в срыве: 1 2 3",
            "r — бумага · i — карман халата",
            "t — тетрадь талантов (бой и мир)",
            "c — на себе: халат, рука, слоты",
            "b — лавка, рядом с Лукиным",
            "при переходе — вид места · в кармане — осмотр и рука",
            "F5 — записать ночь · F9 — вернуться",
            "F4 — буквы / картинки · M — музыка",
            "? / F1 — эти поля · q — выход",
        ]
        box_width = 52
        box_height = 8 + len(TILE_LEGEND) + len(controls)
        box_height = min(box_height, self.screen_height - 2)
        box_x = (self.screen_width - box_width) // 2
        box_y = max(0, (self.screen_height - box_height) // 2)
        self._draw_box(
            box_x, box_y, box_width, box_height, title="ПОЛЯ КАРТЫ", bg=COLOR_CHART_BG
        )

        y_offset = 2
        max_y = box_y + box_height - 8
        for symbol, _short, long_name in TILE_LEGEND:
            if box_y + y_offset > max_y:
                break
            fg, _bg = self._get_tile_color(symbol, True, True)
            if symbol == "@":
                fg = COLOR_PLAYER
            self.console.print(box_x + 4, box_y + y_offset, self._tile_glyph(symbol), fg=fg)
            self.console.print(box_x + 8, box_y + y_offset, f"— {long_name}", fg=COLOR_TEXT)
            y_offset += 1

        y_offset += 1
        self.console.print(box_x + 2, box_y + y_offset, "─" * (box_width - 4), fg=COLOR_MUTED)
        y_offset += 1
        for control in controls:
            if box_y + y_offset >= box_y + box_height - 2:
                break
            self.console.print(box_x + 4, box_y + y_offset, control, fg=COLOR_TEXT)
            y_offset += 1

        close = "[ ? / F1 / Esc — закрыть ]"
        self.console.print(
            box_x + (box_width - len(close)) // 2,
            box_y + box_height - 1,
            close,
            fg=COLOR_MUTED,
        )

    def draw_inventory(self, player, selected_index: int):
        """Карман халата — бумаги, ключи, рука. Не сумка MMORPG."""
        from engine.paintings import oil_id_for_item

        items = list(getattr(player, "inventory", None) or [])
        selected = None
        if items and 0 <= selected_index < len(items):
            selected = items[selected_index]
        list_rows = max(1, len(items) + 1)
        box_width = 72
        box_height = min(
            self.screen_height - 2,
            max(PORTRAIT_ROWS + 4, list_rows + 6),
        )
        box_x = (self.screen_width - box_width) // 2
        box_y = (self.screen_height - box_height) // 2
        self._draw_box(
            box_x, box_y, box_width, box_height,
            title="КАРМАН ХАЛАТА", bg=COLOR_CHART_BG,
        )
        text_width = box_width - PORTRAIT_COLS - 8
        if not items:
            self.console.print(
                box_x + 4, box_y + 3, "Ни бумаги, ни ключа.", fg=COLOR_MUTED
            )
            list_bottom = box_y + 4
        else:
            list_bottom = box_y + 3
            for i, item in enumerate(items):
                y = box_y + 3 + i
                if y >= box_y + box_height - 4:
                    break
                if i == selected_index:
                    marker, color = "· ", COLOR_DIALOGUE
                else:
                    marker, color = "  ", COLOR_TEXT
                name = getattr(item, "name", "без имени")
                where = worn_phrase(player, getattr(item, "id", "") or "")
                if where:
                    name = f"{name} — {where}"
                self.console.print(
                    box_x + 4, y, f"{marker}{name}"[:text_width], fg=color
                )
                list_bottom = y + 1

        if selected_index == len(items):
            close, close_color = "· закрыть", COLOR_SANITY
        else:
            close, close_color = "  закрыть", COLOR_MUTED
        self.console.print(
            box_x + 4, list_bottom, close[:text_width], fg=close_color
        )

        footer_y = box_y + box_height - 1
        if selected is not None:
            desc = getattr(selected, "description", "") or ""
            if getattr(selected, "type", "") == "weapon":
                die = getattr(selected, "damage_die", "") or UNARMED_DAMAGE_DIE
                desc = f"{desc} Удар {die}.".strip()
            wrap = self._wrap_text(desc, text_width)
            shown = wrap[-2:] if wrap else []
            for i, line in enumerate(shown):
                self.console.print(
                    box_x + 4,
                    footer_y - 1 - len(shown) + i,
                    line[:text_width],
                    fg=COLOR_TEXT,
                )
            oil_x = box_x + box_width - PORTRAIT_COLS - 2
            oil_y = box_y + (box_height - PORTRAIT_ROWS) // 2
            self._queue_oil(
                oil_id_for_item(getattr(selected, "id", "") or ""),
                (oil_x, oil_y, PORTRAIT_COLS, PORTRAIT_ROWS),
                getattr(selected, "type", "") or "",
            )

        hint = "↑/↓ · e надеть / снять / читать · i закрыть"
        self.console.print(
            box_x + 4,
            footer_y,
            hint[:text_width],
            fg=COLOR_MUTED,
        )

    def draw_character(self, player, selected_index: int = 0):
        """Кукла слотов. Халат — вещь, не кожа."""
        occupation = getattr(player, "class_name", None) or "без занятия"
        box_width = 72
        box_height = 28
        box_x = (self.screen_width - box_width) // 2
        box_y = max(1, (self.screen_height - box_height) // 2)
        self._draw_box(
            box_x, box_y, box_width, box_height,
            title=f"НА СЕБЕ · {occupation}",
            bg=COLOR_CHART_BG,
        )
        self._pending_portraits.append(
            (
                getattr(player, "id", "") or "",
                (box_x + 3, box_y + 2, PORTRAIT_COLS, PORTRAIT_ROWS),
            )
        )
        stats = getattr(player, "stats", None) or {}
        names = (
            ("STR", "сила"),
            ("DEX", "ловкость"),
            ("CON", "тело"),
            ("INT", "ум"),
            ("CHA", "речь"),
            ("WILL", "воля"),
        )
        stat_y = box_y + 2 + PORTRAIT_ROWS + 1
        for i, (key, rus) in enumerate(names):
            value = int(stats.get(key, 10) or 10)
            self.console.print(
                box_x + 3,
                stat_y + i,
                f"{rus} {value}",
                fg=COLOR_TEXT,
            )
        die = getattr(player, "damage_die", None) or UNARMED_DAMAGE_DIE
        ac = getattr(player, "armor_class", 10)
        self.console.print(
            box_x + 3, stat_y + 6, f"удар {die} · броня {ac}", fg=COLOR_DIALOGUE
        )

        fills = []
        for slot_id, slot_name in EQUIP_SLOTS:
            fills.append((slot_id, slot_name, slot_fill_name(player, slot_id)))
        origin_x = box_x + 24
        origin_y = box_y + 2
        selected = min(max(0, selected_index), len(fills) - 1)
        for i, (slot_id, slot_name, fill) in enumerate(fills):
            ox, oy = EQUIP_LAYOUT.get(slot_id, (14, i * 3))
            self._draw_equip_slot(
                origin_x + ox, origin_y + oy, 16, slot_name, fill, selected=i == selected
            )

        slot_id, slot_name, fill = fills[selected]
        vacant = empty_fill(slot_id)
        if fill != vacant:
            note = f"{slot_name}: {fill}. e — снять."
        elif slot_id == "main_hand":
            note = "правая рука: кулак 1d3. e — взять из кармана, если есть."
        else:
            note = f"{slot_name}: пусто. e — надеть из кармана, если есть."
        wrap = self._wrap_text(note, box_width - 6)
        foot = box_y + box_height - 3
        for i, line in enumerate(wrap[:2]):
            self.console.print(box_x + 3, foot + i, line[: box_width - 6], fg=COLOR_TEXT)
        self.console.print(
            box_x + 3,
            box_y + box_height - 1,
            "↑/↓ слот · e надеть / снять · c закрыть",
            fg=COLOR_MUTED,
        )

    def _draw_equip_slot(self, x, y, width, title, fill, selected=False):
        inner = max(6, width - 2)
        label = f" {title} "
        if len(label) > inner:
            label = label[:inner]
        color = COLOR_LAMP if selected else COLOR_DIALOGUE
        muted = COLOR_LAMP if selected else COLOR_MUTED
        top = "┌" + label + "─" * (inner - len(label)) + "┐"
        body = "│ " + (fill or "пусто")[: inner - 1].ljust(inner - 1) + "│"
        bot = "└" + "─" * inner + "┘"
        self.console.print(x, y, top, fg=color)
        self.console.print(x, y + 1, body, fg=muted if fill == "пусто" else color)
        self.console.print(x, y + 2, bot, fg=color)

    def draw_shop(self, player, merchant_name="", tab="sell", rows=None, selected_index=0, standing=0):
        """Покупка и продажа. Сумма на строке, не формула."""
        from engine.paintings import oil_id_for_item

        rows = list(rows or [])
        selected = None
        if rows and 0 <= selected_index < len(rows):
            selected = rows[selected_index]
        buying = tab == "buy"
        purse = int(getattr(player, "kopecks", 0) or 0)
        title = f"ЛАВКА · {merchant_name or 'Лукин'}"
        box_width = 72
        list_rows = max(1, len(rows) + 1)
        box_height = min(
            self.screen_height - 2,
            max(PORTRAIT_ROWS + 6, list_rows + 8),
        )
        box_x = (self.screen_width - box_width) // 2
        box_y = (self.screen_height - box_height) // 2
        self._draw_box(
            box_x, box_y, box_width, box_height,
            title=title[: box_width - 4],
            bg=COLOR_CHART_BG,
        )
        text_width = box_width - PORTRAIT_COLS - 8
        sell_mark = "[продажа]" if not buying else " продажа "
        buy_mark = "[покупка]" if buying else " покупка "
        self.console.print(
            box_x + 4,
            box_y + 2,
            f"{sell_mark}  {buy_mark}",
            fg=COLOR_DIALOGUE,
        )
        self.console.print(
            box_x + 4,
            box_y + 3,
            f"в кармане {kopeck_phrase(purse)}",
            fg=COLOR_MUTED,
        )
        if not rows:
            empty = "Нечего продать." if not buying else "Пока нечего купить."
            self.console.print(box_x + 4, box_y + 5, empty, fg=COLOR_MUTED)
            list_bottom = box_y + 6
        else:
            list_bottom = box_y + 5
            for i, item in enumerate(rows):
                y = box_y + 5 + i
                if y >= box_y + box_height - 4:
                    break
                if i == selected_index:
                    marker, color = "· ", COLOR_DIALOGUE
                else:
                    marker, color = "  ", COLOR_TEXT
                name = getattr(item, "name", "без имени")
                if buying:
                    price = buy_price(int(getattr(item, "value", 0) or 0), standing)
                else:
                    price = sell_price(counter_item_value(item), standing)
                line = f"{marker}{name}  {kopeck_phrase(price)}"
                self.console.print(box_x + 4, y, line[:text_width], fg=color)
                list_bottom = y + 1

        footer_y = box_y + box_height - 1
        if selected is not None:
            desc = getattr(selected, "description", "") or ""
            wrap = self._wrap_text(desc, text_width)
            shown = wrap[-2:] if wrap else []
            for i, line in enumerate(shown):
                self.console.print(
                    box_x + 4,
                    footer_y - 1 - len(shown) + i,
                    line[:text_width],
                    fg=COLOR_TEXT,
                )
            oil_x = box_x + box_width - PORTRAIT_COLS - 2
            oil_y = box_y + (box_height - PORTRAIT_ROWS) // 2
            self._queue_oil(
                oil_id_for_item(getattr(selected, "id", "") or ""),
                (oil_x, oil_y, PORTRAIT_COLS, PORTRAIT_ROWS),
                getattr(selected, "type", "") or "",
            )
        verb = "купить" if buying else "продать"
        hint = f"Tab раздел · e {verb} · b закрыть"
        self.console.print(
            box_x + 4,
            footer_y,
            hint[:text_width],
            fg=COLOR_MUTED,
        )

    def draw_oil_overlay(self, overlay):
        """Вид места при входе или вещи при осмотре. Карта .txt под холстом."""
        kind = (overlay or {}).get("kind") or "place"
        title = (overlay or {}).get("title") or ""
        body = (overlay or {}).get("body") or ""
        oil_id = (overlay or {}).get("oil_id") or ""
        item_type = (overlay or {}).get("item_type") or ""
        is_place = kind == "place"
        cols = LOCATION_OIL_COLS if is_place else ITEM_LOOK_COLS
        rows = LOCATION_OIL_ROWS if is_place else ITEM_LOOK_ROWS
        box_width = min(self.screen_width - 4, max(cols + 4, 56))
        box_height = min(self.map_height, rows + 8)
        box_x = (self.screen_width - box_width) // 2
        box_y = max(0, (self.map_height - box_height) // 2)
        self._draw_box(
            box_x, box_y, box_width, box_height,
            title=title[: box_width - 4],
            bg=COLOR_CHART_BG,
        )
        oil_x = box_x + (box_width - cols) // 2
        oil_y = box_y + 2
        queued = self._queue_oil(
            oil_id, (oil_x, oil_y, cols, rows), item_type
        )
        text_y = oil_y + (rows if queued else 1)
        wrap = self._wrap_text(body, box_width - 4)
        max_lines = max(1, box_y + box_height - 3 - text_y)
        for i, line in enumerate(wrap[:max_lines]):
            self.console.print(
                box_x + 2, text_y + i, line[: box_width - 4], fg=COLOR_TEXT
            )
        self.console.print(
            box_x + 2,
            box_y + box_height - 1,
            "e / пробел — дальше",
            fg=COLOR_MUTED,
        )

    def draw_talents(self, player, selected_index: int = 0, flags=None):
        """Тетрадь: боевые и мирные ветки восьми глаголов."""
        from engine.talent_system import (
            SAN_FLOOR,
            deed_ready,
            has_talent,
            san_cost_for,
            take_block_reason,
            visible_talents,
        )

        nodes = visible_talents(player)
        desc_lines = 4
        box_width = 72
        box_height = min(28, max(16, len(nodes) + 6 + desc_lines))
        box_x = (self.screen_width - box_width) // 2
        box_y = max(1, (self.screen_height - box_height) // 2)
        occupation = getattr(player, "class_name", None) or "без занятия"
        self._draw_box(
            box_x, box_y, box_width, box_height,
            title=f"ТЕТРАДЬ · {occupation}",
            bg=COLOR_CHART_BG,
        )
        san = int(getattr(player, "san", 0) or 0)
        head = f"воля {san} · после пометки не ниже {SAN_FLOOR}"
        self.console.print(box_x + 2, box_y + 2, head[: box_width - 4], fg=COLOR_SANITY)
        class_id = getattr(player, "id", "")
        list_bottom = box_y + box_height - 2 - desc_lines
        if not nodes:
            self.console.print(
                box_x + 4, box_y + 4, "Тетрадь пуста. Странно.", fg=COLOR_MUTED
            )
        for i, node in enumerate(nodes):
            y = box_y + 4 + i
            if y >= list_bottom:
                break
            taken = has_talent(player, node.id)
            cost = san_cost_for(node, class_id)
            branch = "бой" if node.branch == "combat" else "мир"
            if taken:
                mark, color = "×", COLOR_DIALOGUE
                tail = "взято"
            else:
                why = take_block_reason(player, node, flags)
                mark, color = "·" if i == selected_index else " ", COLOR_TEXT
                if why:
                    color = COLOR_MUTED
                    if node.require_deed == "truth" and not deed_ready(node, flags):
                        tail = "нужны имя или долг"
                    elif node.require_deed == "spoke" and not deed_ready(node, flags):
                        tail = "нужен поступок"
                    else:
                        tail = f"{cost} воли"
                else:
                    tail = f"{cost} воли"
                if i == selected_index:
                    color = COLOR_LAMP
            line = f"{mark} [{branch}] {node.name} — {tail}"
            self.console.print(box_x + 2, y, line[: box_width - 4], fg=color)
        if nodes and 0 <= selected_index < len(nodes):
            wrapped = self._wrap_text(
                nodes[selected_index].description, box_width - 4
            )
            start_y = box_y + box_height - 1 - desc_lines
            for j, text in enumerate(wrapped[:desc_lines]):
                self.console.print(
                    box_x + 2, start_y + j, text[: box_width - 4], fg=COLOR_TEXT
                )
        self.console.print(
            box_x + 2,
            box_y + box_height - 1,
            "↑/↓ · e взять · t закрыть",
            fg=COLOR_MUTED,
        )