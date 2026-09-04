"""Отрисовка игры через tcod."""
import math
import random
import time
from typing import Dict, List

import tcod
from tcod import libtcodpy

from engine.constants import LEGEND_WIDTH, SCREEN_HEIGHT, SCREEN_WIDTH, TILE_LEGEND
from engine.clinic_tiles import TILE_HEIGHT, TILE_WIDTH, map_glyph
from engine.palette import INKS, explored_color_dicts, hex_to_rgb, visible_color_dicts
from engine.portraits import PORTRAIT_COLS, PORTRAIT_ROWS, load_pixels


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
        self._pending_portrait = None 
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

    def _tile_glyph(self, char: str) -> str:
        """Картинка только на карте. Точка в речи остаётся точкой."""
        engine = self.game_engine
        if not engine or not getattr(engine, "use_sprites", True):
            return char
        tileset = getattr(engine, "clinic_tileset", None)
        if not getattr(tileset, "_clinic_sprites_ready", False):
            return char
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

                self.console.print(screen_x, screen_y, self._tile_glyph(char), fg=fg, bg=bg)

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
        """Отрисовка сообщений (лог)."""
        msg_y = self.map_height + 3
        
        # Показываем последние 3 сообщения
        recent_messages = messages[-3:] if len(messages) > 3 else messages
        
        for i, msg in enumerate(recent_messages):
            y = msg_y + i
            if y < self.screen_height:
                # Обрезаем слишком длинные сообщения
                if len(msg) > self.screen_width - 2:
                    msg = msg[:self.screen_width - 2]
                self.console.print(1, y, msg, fg=COLOR_TEXT)
            
    def draw_dialogue(self, text: str, speaker_name: str = '', choices=None,
                      portrait_id: str = ''):
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
        extra = max(0, len(choices))
        box_height = 5 + extra
        text_x = 4
        wrap_width = box_width - 4
        if show_face:
            box_height = max(box_height, PORTRAIT_ROWS + 2)
            text_x = 4 + PORTRAIT_COLS + 1
            wrap_width = box_width - PORTRAIT_COLS - 3
        box_y = max(2, self.map_height - box_height - 1)

        self.console.print(2, box_y, '┌' + '─' * (box_width - 2) + '┐', fg=COLOR_DIALOGUE)
        for i in range(1, box_height - 1):
            self.console.print(2, box_y + i, '│' + ' ' * (box_width - 2) + '│', fg=COLOR_DIALOGUE)
        self.console.print(2, box_y + box_height - 1, '└' + '─' * (box_width - 2) + '┘', fg=COLOR_DIALOGUE)

        if speaker_name:
            self.console.print(text_x, box_y, f"[ {speaker_name} ]", fg=COLOR_DIALOGUE)

        wrapped = self._wrap_text(text or '', wrap_width)
        text_lines = max(2, box_height - 3 - extra) if show_face else 2
        for i, line in enumerate(wrapped[:text_lines]):
            self.console.print(text_x, box_y + 1 + i, line, fg=COLOR_DIALOGUE)

        if choices:
            for i, choice in enumerate(choices):
                label = f"{i + 1}. {choice}"
                if len(label) > wrap_width - 2:
                    label = label[: wrap_width - 5] + "..."
                self.console.print(text_x, box_y + box_height - 2 - extra + i, label, fg=COLOR_DIALOGUE)
            hint = f"[1-{len(choices)} — ответ]"
        else:
            hint = "[Space — далее]"
        self.console.print(self.screen_width - len(hint) - 4, box_y + box_height - 1,
            hint, fg=COLOR_TEXT)

        if show_face:
            self._pending_portrait = (
                portrait_id,
                (3, box_y + 1, PORTRAIT_COLS, PORTRAIT_ROWS),
            )

    def draw_ending(self, title: str, body: str):
        """Финальный экран новеллы."""
        for y in range(self.screen_height):
            for x in range(self.screen_width):
                self.console.bg[x, y] = libtcodpy.Color(8, 6, 8)
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
            fg=libtcodpy.Color(120, 120, 120),
        )
    
    def _wrap_text(self, text: str, width: int):
        """Перенос текста по ширине."""
        words = text.split()
        lines = []
        current_line = []
        current_len = 0
        
        for word in words:
            if current_len + len(word) + 1 > width:
                lines.append(' '.join(current_line))
                current_line = [word]
                current_len = len(word)
            else:
                current_line.append(word)
                current_len += len(word) + 1
        
        if current_line:
            lines.append(' '.join(current_line))
        
        return lines
    
    def draw_class_selection(self, classes, selected_index: int, has_save: bool = False):
        """Экран выбора класса."""
        self.console.clear()
        
        title = "ПЕТЕРБУРГ. КЛИНИКА. БРЕД."
        subtitle = "Выберите, кем вы были до пробуждения..."
        
        self.console.print(self.screen_width // 2 - len(title) // 2, 5, title, fg=COLOR_DIALOGUE)
        self.console.print(self.screen_width // 2 - len(subtitle) // 2, 7, subtitle, fg=COLOR_TEXT)
        
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
        self.console.print(10, self.screen_height - 3, hint, fg=COLOR_TEXT)
        
    def draw_hud(self, player):
        """Панель состояния."""
        hud_y = self.map_height
        
        # Разделитель
        self.console.print(0, hud_y, '─' * self.screen_width, fg=COLOR_TEXT)
        
        # Статистика
        self.console.print(1, hud_y + 1,
            f"HP:{player.hp}/{player.max_hp} SAN:{player.san}/{player.max_san} {player.class_name}",
            fg=COLOR_TEXT
        )
        
        # Управление
        in_combat = getattr(self.game_engine, 'state', None) == 'combat'
        if in_combat:
            self.console.print(
                1, hud_y + 2,
                "БОЙ: пробел — удар | Esc — бежать",
                fg=COLOR_HP,
            )
        else:
            self.console.print(1, hud_y + 2,
                "стрелки/hjkl | a e r i | F5/F9 | ? справка | q выход",
                fg=COLOR_TEXT
            )
        
    def draw_quests(self, quest_descriptions: List[str]):
        """Отрисовка активных квестов."""
        if not quest_descriptions:
            return
        
        # Показываем квесты в логе сообщений (над HUD)
        quest_y = self.map_height - 2
        
        for i, desc in enumerate(quest_descriptions[:2]):
            y = quest_y - i
            if y > 0:
                if len(desc) > self.map_width - 2:
                    desc = desc[:self.map_width - 2]
                self.console.print(1, y, desc, fg=libtcodpy.Color(200, 180, 100))
            
    def present(self, context):
        """Вывод кадра. keep_aspect держит шаг буквы; масло — поверх консоли."""
        renderer = getattr(context, "sdl_renderer", None)
        atlas = getattr(context, "sdl_atlas", None)
        pending = self._pending_portrait
        self._pending_portrait = None
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
        if pending:
            portrait_id, (tx, ty, tw, th) = pending
            cached = self._portrait_textures.get(portrait_id)
            texture = src_w = src_h = None
            if isinstance(cached, tuple) and len(cached) == 3:
                texture, src_w, src_h = cached
            if texture is None:
                pixels = load_pixels(portrait_id)
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
        """Постоянная расшифровка ASCII справа от карты."""
        x0 = self.map_width
        width = self.legend_width
        muted = libtcodpy.Color(110, 115, 120)
        title_fg = libtcodpy.Color(220, 200, 150)
        panel = libtcodpy.Color(18, 16, 18)

        for y in range(self.map_height):
            for x in range(x0, x0 + width):
                self.console.bg[x, y] = panel
            self.console.print(x0, y, '│', fg=muted)

        self.console.print(x0 + 2, 1, 'легенда', fg=title_fg)
        self.console.print(x0 + 1, 2, '─' * (width - 2), fg=muted)

        y = 4
        for symbol, short, _long in TILE_LEGEND:
            if y >= self.map_height - 3:
                break
            fg, _bg = self._get_tile_color(symbol, True, True)
            if symbol == '@':
                fg = COLOR_PLAYER
            self.console.print(x0 + 2, y, self._tile_glyph(symbol), fg=fg)
            label = short
            if len(label) > width - 6:
                label = label[: width - 6]
            self.console.print(x0 + 4, y, label, fg=COLOR_TEXT)
            y += 1

        mode = 'буквы' if getattr(self.game_engine, 'use_sprites', True) else 'тайлы'
        self.console.print(x0 + 2, self.map_height - 2, f'? · F4 {mode}', fg=muted)

    def draw_help(self):
        """Окно помощи с расшифровкой условных обозначений."""
        for y in range(self.screen_height):
            for x in range(self.screen_width):
                bg = self.console.bg[x, y]
                r = int(bg[0]) if hasattr(bg, '__getitem__') else bg.r
                g = int(bg[1]) if hasattr(bg, '__getitem__') else bg.g
                b = int(bg[2]) if hasattr(bg, '__getitem__') else bg.b
                self.console.bg[x, y] = libtcodpy.Color(
                    max(0, r - 40),
                    max(0, g - 40),
                    max(0, b - 40)
                )

        controls = [
            'hjkl / Стрелки — движение',
            '1–9 — ответ в диалоге',
            'a — атака | e — разговор, дверь, обыск',
            'r — читать записку | i — инвентарь',
            'F5 — записать ночь | F9 — вернуться',
            'F4 — буквы / картинки',
            'M — музыка',
            '? / F1 — это окно помощи',
            'q / Esc — выход: ночь запишется',
        ]
        box_width = 52
        box_height = 8 + len(TILE_LEGEND) + len(controls)
        box_height = min(box_height, self.screen_height - 2)
        box_x = (self.screen_width - box_width) // 2
        box_y = max(0, (self.screen_height - box_height) // 2)

        self.console.print(box_x, box_y, '┌' + '─' * (box_width - 2) + '┐', fg=COLOR_DIALOGUE)
        for i in range(1, box_height - 1):
            self.console.print(box_x, box_y + i, '│' + ' ' * (box_width - 2) + '│', fg=COLOR_DIALOGUE)
        self.console.print(box_x, box_y + box_height - 1, '└' + '─' * (box_width - 2) + '┘', fg=COLOR_DIALOGUE)

        title = "УСЛОВНЫЕ ОБОЗНАЧЕНИЯ"
        self.console.print(
            box_x + (box_width - len(title)) // 2,
            box_y + 1,
            title,
            fg=libtcodpy.Color(255, 220, 100)
        )
        self.console.print(box_x + 2, box_y + 2, '─' * (box_width - 4), fg=COLOR_TEXT)

        y_offset = 4
        max_y = box_y + box_height - 8
        for symbol, _short, long_name in TILE_LEGEND:
            if box_y + y_offset > max_y:
                break
            fg, _bg = self._get_tile_color(symbol, True, True)
            if symbol == '@':
                fg = COLOR_PLAYER
            self.console.print(box_x + 4, box_y + y_offset, self._tile_glyph(symbol), fg=fg)
            self.console.print(box_x + 8, box_y + y_offset, f'— {long_name}', fg=COLOR_TEXT)
            y_offset += 1

        y_offset += 1
        self.console.print(box_x + 2, box_y + y_offset, '─' * (box_width - 4), fg=COLOR_TEXT)
        y_offset += 1
        for control in controls:
            if box_y + y_offset >= box_y + box_height - 2:
                break
            self.console.print(box_x + 4, box_y + y_offset, control, fg=COLOR_TEXT)
            y_offset += 1

        self.console.print(
            box_x + (box_width - 30) // 2,
            box_y + box_height - 2,
            '[ ? / F1 / Esc — закрыть ]',
            fg=libtcodpy.Color(150, 150, 150)
        )
        
    def draw_inventory(self, player, selected_index: int):
        """Окно инвентаря."""
        # Размеры окна
        box_width = 50
        box_height = min(20, len(player.inventory) + 6)
        box_x = (self.screen_width - box_width) // 2
        box_y = (self.screen_height - box_height) // 2
        
        # Затемняем только область окна (с отступом 2 клетки)
        padding = 2
        for y in range(max(0, box_y - padding), min(self.screen_height, box_y + box_height + padding)):
            for x in range(max(0, box_x - padding), min(self.screen_width, box_x + box_width + padding)):
                bg = self.console.bg[x, y]
                r = int(bg[0]) if hasattr(bg, '__getitem__') else bg.r
                g = int(bg[1]) if hasattr(bg, '__getitem__') else bg.g
                b = int(bg[2]) if hasattr(bg, '__getitem__') else bg.b
                self.console.bg[x, y] = libtcodpy.Color(
                    max(0, r - 60),
                    max(0, g - 60),
                    max(0, b - 60)
                )
        
        # Рамка
        self.console.print(box_x, box_y, '┌' + '─' * (box_width - 2) + '', fg=COLOR_DIALOGUE)
        for i in range(1, box_height - 1):
            self.console.print(box_x, box_y + i, '│' + ' ' * (box_width - 2) + '│', fg=COLOR_DIALOGUE)
        self.console.print(box_x, box_y + box_height - 1, '└' + '─' * (box_width - 2) + '', fg=COLOR_DIALOGUE)
        
        # Заголовок
        title = "ИНВЕНТАРЬ"
        self.console.print(
            box_x + (box_width - len(title)) // 2,
            box_y + 1,
            title,
            fg=libtcodpy.Color(255, 220, 100)
        )
        
        # Разделитель
        self.console.print(box_x + 2, box_y + 2, '─' * (box_width - 4), fg=COLOR_TEXT)
        
        # Список предметов — читаем из player.inventory каждый раз
        if not player.inventory:
            self.console.print(box_x + 4, box_y + 4, "Пусто", fg=COLOR_TEXT)
        else:
            for i, item in enumerate(player.inventory):
                y = box_y + 4 + i
                if y >= box_y + box_height - 3:
                    break
                # Маркер выбранного предмета
                if i == selected_index:
                    marker = "▶ "
                    color = libtcodpy.Color(255, 255, 100)
                else:
                    marker = "  "
                    color = COLOR_TEXT
                # Имя предмета
                item_name = getattr(item, 'name', 'Неизвестный предмет')
                self.console.print(box_x + 4, y, f"{marker}{item_name}", fg=color)
        
        # Пункт "Выход"
        exit_y = box_y + box_height - 3
        if selected_index == len(player.inventory):
            self.console.print(box_x + 4, exit_y, "▶ Выход", fg=libtcodpy.Color(255, 100, 100))
        else:
            self.console.print(box_x + 4, exit_y, "  Выход", fg=COLOR_TEXT)
        
        # Подсказки
        hints_y = box_y + box_height - 1
        self.console.print(
            box_x + 4, hints_y,
            "↑/↓ — выбор | e — использовать | i/Esc — выход",
            fg=libtcodpy.Color(150, 150, 150)
        )