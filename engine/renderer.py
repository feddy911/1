"""Отрисовка игры через tcod."""
import tcod
import random
from tcod import libtcodpy
from engine.constants import LEGEND_WIDTH, SCREEN_HEIGHT, SCREEN_WIDTH, TILE_LEGEND
from typing import List, Dict
import math


# Цветовая палитра
COLOR_WALL = libtcodpy.Color(45, 50, 55)
COLOR_FLOOR = libtcodpy.Color(25, 30, 35)
COLOR_PLAYER = libtcodpy.Color(220, 220, 230)
COLOR_TEXT = libtcodpy.Color(150, 160, 170)
COLOR_SANITY = libtcodpy.Color(180, 50, 50)
COLOR_HP = libtcodpy.Color(200, 80, 80)
COLOR_DIALOGUE = libtcodpy.Color(220, 200, 150)
COLOR_UNKNOWN = libtcodpy.Color(0, 0, 0)  # Неизвестная область
COLOR_VOID_FG = libtcodpy.Color(42, 44, 50)
COLOR_VOID_BG = libtcodpy.Color(10, 11, 14)
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
        """Установить цвета по умолчанию."""
        self.tile_colors = {
            '#': {'fg': '#2d3237', 'bg': '#2d3237'},
            '.': {'fg': '#191e23', 'bg': '#191e23'},
            ' ': {'fg': '#191e23', 'bg': '#191e23'},
            'D': {'fg': '#dc8c40', 'bg': '#8c6432'},
            'd': {'fg': '#ff5050', 'bg': '#a03232'},
            'S': {'fg': '#64dcff', 'bg': '#3c8ca0'},
            's': {'fg': '#5088a0', 'bg': '#2c5a68'},
            'E': {'fg': '#64dcff', 'bg': '#3c8ca0'},
            '*': {'fg': '#fff064', 'bg': '#b4a032'},
            '!': {'fg': '#78ff78', 'bg': '#3ca03c'},
            ')': {'fg': '#78ff78', 'bg': '#3ca03c'},
            '≈': {'fg': '#ffdc64', 'bg': '#a08c32'},
            '~': {'fg': '#ffdc64', 'bg': '#a08c32'},
            '&': {'fg': '#ff7878', 'bg': '#a03c3c'},
            '@': {'fg': '#dcdce6', 'bg': '#646478'},
            'W': {'fg': '#aaccff', 'bg': '#6688aa'},
            'B': {'fg': '#6a5a4a', 'bg': '#3a322c'},
            'T': {'fg': '#8a6a40', 'bg': '#4a3828'},
            'C': {'fg': '#7a6048', 'bg': '#3a3028'},
            'H': {'fg': '#5a5048', 'bg': '#322c28'},
            'O': {'fg': '#6a5840', 'bg': '#3a3228'},
            '=': {'fg': '#1a3048', 'bg': '#0c1828'},
        }
        self.tile_colors_explored = {
            '#': {'fg': '#1e2023', 'bg': '#1e2023'},
            '.': {'fg': '#0f1214', 'bg': '#0f1214'},
            ' ': {'fg': '#0f1214', 'bg': '#0f1214'},
            'D': {'fg': '#6e5028', 'bg': '#463219'},
            'd': {'fg': '#822828', 'bg': '#501919'},
            'S': {'fg': '#326e82', 'bg': '#1e4650'},
            's': {'fg': '#284858', 'bg': '#142830'},
            'E': {'fg': '#326e82', 'bg': '#1e4650'},
            '*': {'fg': '#827832', 'bg': '#5a5019'},
            '!': {'fg': '#3c823c', 'bg': '#1e501e'},
            ')': {'fg': '#3c823c', 'bg': '#1e501e'},
            '≈': {'fg': '#826e32', 'bg': '#504619'},
            '~': {'fg': '#826e32', 'bg': '#504619'},
            '&': {'fg': '#823c3c', 'bg': '#501e1e'},
            '@': {'fg': '#646478', 'bg': '#32323c'},
            'W': {'fg': '#445566', 'bg': '#223344'},
            'B': {'fg': '#3a322c', 'bg': '#1e1a16'},
            'T': {'fg': '#4a3828', 'bg': '#241c14'},
            'C': {'fg': '#3a3028', 'bg': '#1e1814'},
            'H': {'fg': '#322c28', 'bg': '#1a1614'},
            'O': {'fg': '#3a3228', 'bg': '#1e1a14'},
            '=': {'fg': '#0c1828', 'bg': '#060c14'},
        }
    
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
    
    def clear(self):
        self.console.clear()
    
    def set_camera_position(self, player_x: int, player_y: int, map_width: int, map_height: int):
        """Обновить позицию камеры."""
        self.camera.move_to(player_x, player_y, map_width, map_height)
    
    def draw_map(self, tiles):
        """Отрисовка карты с эффектами безумия."""
        map_height = len(tiles)
        map_width = len(tiles[0]) if map_height > 0 else 0
        
               
        # Получаем эффекты безумия
        sanity_effects = {'visual': 'normal'}
        if self.game_engine and self.game_engine.san_system:
            sanity_effects = self.game_engine.san_system.get_sanity_effects()
        
        # Определяем интенсивность искажений
        distortion_level = 0
        if sanity_effects['visual'] == 'flicker':
            distortion_level = 0.1
        elif sanity_effects['visual'] == 'distortion':
            distortion_level = 0.3
        elif sanity_effects['visual'] == 'heavy_distortion':
            distortion_level = 0.6
        elif sanity_effects['visual'] == 'chaos':
            distortion_level = 0.9
        
        # Мерцание экрана
        if sanity_effects['visual'] == 'flicker' and random.random() < 0.2:
            for y in range(SCREEN_HEIGHT):
                for x in range(SCREEN_WIDTH):
                    self.console.bg[x, y] = libtcodpy.Color(20, 20, 20)

        # Край карты (57 клеток vs окно 60) и туман войны — не чёрный «пол».
        for sy in range(self.map_height):
            for sx in range(self.map_width):
                self.console.print(
                    sx, sy, ':', fg=COLOR_VOID_FG, bg=COLOR_VOID_BG
                )
        
        # Искажение карты
        for y in range(map_height):
            for x in range(map_width):
                # Проверяем, видна ли клетка
                if not self.camera.is_visible(x, y):
                    continue
                
                screen_x, screen_y = self.camera.world_to_screen(x, y)
                
                if not (0 <= screen_x < self.map_width and 0 <= screen_y < self.map_height):
                    continue
                
                char = tiles[y][x]
                
                # Определяем уровень видимости
                is_visible = self.fov_system and self.fov_system.is_visible(x, y)
                is_explored = self.fov_system and self.fov_system.is_explored(x, y)
                if not is_visible and not is_explored:
                    continue
                
                # Применяем искажения
                if distortion_level > 0:
                    if random.random() < distortion_level:
                        # Искажаем символ
                        char = random.choice(['.', '#', ' ', '≈', '≈'])
                
                # Цвет берём из БД
                fg, bg = self._get_tile_color(char, is_visible, is_explored)

                # Применяем освещённость с затуханием
                if is_visible and self.fov_system:
                    illumination = self.fov_system.get_illumination(x, y)
                    
                    if illumination > 0.01:  # Клетка освещена
                        # ← НОВОЕ: Boost пропорционален освещённости
                        # illumination = 1.0 → boost = 100 (максимум)
                        # illumination = 0.5 → boost = 50
                        # illumination = 0.1 → boost = 10
                        boost = illumination * 100
                        
                        # Ограничиваем максимум
                        boost = min(100, boost)
                        
                        # Применяем boost к fg и bg
                        fg = libtcodpy.Color(
                            min(255, fg.r + int(boost)),
                            min(255, fg.g + int(boost)),
                            min(255, fg.b + int(boost))
                        )
                        bg = libtcodpy.Color(
                            min(255, bg.r + int(boost)),
                            min(255, bg.g + int(boost)),
                            min(255, bg.b + int(boost))
                        )
                    
                self.console.print(screen_x, screen_y, char, fg=fg, bg=bg)
        
        # Добавляем галлюцинации
        if sanity_effects['hallucinations']:
            for hallucination in sanity_effects['hallucinations']:
                x, y = hallucination['x'], hallucination['y']
                if self.camera.is_visible(x, y):
                    screen_x, screen_y = self.camera.world_to_screen(x, y)
                    if 0 <= screen_x < self.map_width and 0 <= screen_y < self.map_height:
                        # Рисуем галлюцинацию
                        char = random.choice(['≈', '±', '§', '¶'])
                        self.console.print(screen_x, screen_y, char, fg=libtcodpy.Color(255, 0, 255))
                        
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
            symbol = self._safe_glyph(getattr(entity, 'symbol', '?'))
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
                player.symbol,
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
            
    def draw_dialogue(self, text: str, speaker_name: str = '', choices=None):
        """Окно диалога, при необходимости — с вариантами ответа."""
        if not text and not choices:
            return

        choices = choices or []
        box_width = self.screen_width - 4
        extra = max(0, len(choices))
        box_height = 5 + extra
        box_y = max(2, self.map_height - box_height - 1)

        self.console.print(2, box_y, '┌' + '─' * (box_width - 2) + '┐', fg=COLOR_DIALOGUE)
        for i in range(1, box_height - 1):
            self.console.print(2, box_y + i, '│' + ' ' * (box_width - 2) + '│', fg=COLOR_DIALOGUE)
        self.console.print(2, box_y + box_height - 1, '└' + '─' * (box_width - 2) + '┘', fg=COLOR_DIALOGUE)

        if speaker_name:
            self.console.print(4, box_y, f"[ {speaker_name} ]", fg=COLOR_DIALOGUE)

        wrapped = self._wrap_text(text or '', box_width - 4)
        for i, line in enumerate(wrapped[:2]):
            self.console.print(4, box_y + 1 + i, line, fg=COLOR_DIALOGUE)

        if choices:
            for i, choice in enumerate(choices):
                label = f"{i + 1}. {choice}"
                if len(label) > box_width - 6:
                    label = label[: box_width - 9] + "..."
                self.console.print(4, box_y + 3 + i, label, fg=COLOR_DIALOGUE)
            hint = f"[1-{len(choices)} — ответ]"
        else:
            hint = "[Space — далее]"
        self.console.print(self.screen_width - len(hint) - 4, box_y + box_height - 1,
            hint, fg=COLOR_TEXT)

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
        """Вывод кадра на экран."""
        context.present(self.console)
        
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
            
            symbol = light.get('symbol', '*')
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
            self.console.print(x0 + 2, y, symbol, fg=fg)
            label = short
            if len(label) > width - 6:
                label = label[: width - 6]
            self.console.print(x0 + 4, y, label, fg=COLOR_TEXT)
            y += 1

        self.console.print(x0 + 2, self.map_height - 2, '? справка', fg=muted)

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
            'a — атака | e — взаимодействие',
            'r — читать записку | i — инвентарь',
            'F5 — записать ночь | F9 — вернуться',
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
            self.console.print(box_x + 4, box_y + y_offset, symbol, fg=fg)
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