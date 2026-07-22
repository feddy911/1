"""Главный игровой движок."""
import tcod
from tcod import libtcodpy
import random
import os
from typing import List, Optional
from engine.db_loader import DBLoader
from engine.map_builder import BlockMapGenerator
from engine.entity_factory import EntityFactory, Player, Character, Item
from engine.trigger_system import TriggerSystem
from engine.dialogue_engine import DialogueEngine
from engine.renderer import Renderer
from engine.fov_system import FOVSystem
from engine.combat_system import perform_attack
from engine.sanity_system import SanSystem
from engine.constants import SCREEN_WIDTH, SCREEN_HEIGHT
from engine.quest_system import QuestSystem


class GameState:
    """Состояние игры."""
    CLASS_SELECTION = 'class_selection'
    PLAYING = 'playing'
    COMBAT = 'combat'
    DIALOGUE = 'dialogue'
    GAME_OVER = 'game_over'


class GameEngine:
    """Главный движок игры."""

    def __init__(self, context):
        self.context = context
        self.db = DBLoader()
        self.map_builder = BlockMapGenerator(self.db)
        self.entity_factory = EntityFactory(self.db)
        self.trigger_system = TriggerSystem(self.db)
        self.dialogue_engine = DialogueEngine(self.db)
        self.renderer = Renderer(SCREEN_WIDTH, SCREEN_HEIGHT)
        self.renderer.game_engine = self
        
        # Загружаем цвета тайлов из БД
        self.renderer.load_tile_colors_from_db(self.db)
        
        self.player: Optional[Player] = None
        self.current_map: List[List[str]] = []
        self.entities: List = []
        self.messages: List[str] = []
        self.state = GameState.CLASS_SELECTION

        # Для выбора класса
        self.available_classes = self.db.get_all_player_classes()
        self.selected_class_index = 0

        # Для диалога
        self.current_dialogue_text = ''
        self.current_dialogue_speaker = ''

        # Система видимости
        self.fov_system = None
        self.light_radius = 5

        # Для боя
        self.current_enemy = None

        # Система безумия
        self.san_system = None

        # Система квестов
        self.quest_system = None
        self.current_note_text = ''
        self.reading_note = False

        # Для уведомлений о квестах
        self.notified_quests = []
        
        self.showing_help = False

    def add_message(self, text: str):
        """Добавить сообщение в лог."""
        self.messages.append(text)
        if len(self.messages) > 20:
            self.messages.pop(0)

    def run(self):
        """Главный цикл."""
        running = True
        while running:
            running = self.handle_events()
            # Обновляем систему безумия
            if self.san_system:
                san_events = self.san_system.update()
                for event in san_events:
                    self.add_message(event)
            self.render()
        self.db.close()

    def start_game_with_class(self, class_id: str):
        """Начать игру с выбранным классом."""
        class_data = self.db.get_player_class(class_id)
        if not class_data:
            return False
        
        self.player = Player(class_data)
        
        # ← НОВОЕ: Загружаем стартовую карту из БД
        starting_map = self.db.get_starting_map()
        if not starting_map:
            self.add_message("Стартовая карта не найдена в БД!")
            return False
        
        self._load_map(starting_map['id'])
        
        # Стартовые предметы
        for item_id in self.player.starting_item_ids:
            item = self.entity_factory.create_item(item_id)
            if item:
                self.player.inventory.append(item)
        
        self.state = GameState.PLAYING
        self.add_message("Вы открываете глаза. Холодный потолок. Где вы?")
        self.add_message("Голова раскалывается. Имени не вспомнить...")
        
        self.san_system = SanSystem(self.player)
        self.quest_system = QuestSystem(self.db)
        
        return True    

    def _load_map(self, map_id: str):
        """Загрузить карту из БД."""
        map_data = self.db.get_map(map_id)
        if not map_data:
            self.add_message(f"Карта '{map_id}' не найдена в БД!")
            return
        
        file_path = map_data['file_path']
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self.current_map = [list(line.rstrip()) for line in f.readlines()]
        except FileNotFoundError:
            self.add_message(f"Файл карты не найден: {file_path}")
            return
        
        if not self.current_map:
            self.add_message("Карта пуста!")
            return
        
        map_height = len(self.current_map)
        map_width = len(self.current_map[0]) if map_height > 0 else 0
        
        # Инициализируем FOV
        self.fov_system = FOVSystem(map_width, map_height)
        self.fov_system.initialize(self.current_map)
        
        # ← НОВОЕ: Загружаем прозрачность тайлов из БД
        transparency = self.db.get_tile_transparency()
        self.fov_system.set_tile_transparency(transparency)
        
        # ← НОВОЕ: Находим источники света на карте
        self.light_sources = []
        light_types = self.db.get_light_sources()
        light_symbols = {lt['symbol']: lt for lt in light_types}
        
        for y in range(map_height):
            for x in range(map_width):
                tile = self.current_map[y][x]
                if tile in light_symbols:
                    lt = light_symbols[tile]
                    self.light_sources.append({
                        'x': x,
                        'y': y,
                        'type': lt['id'],
                        'symbol': lt['symbol'],
                        'color': lt['color'],
                        'radius': lt['radius'],
                        'intensity': lt['intensity'],
                        'flicker': bool(lt.get('flicker', 0))
                    })
                
        # Находим стартовую позицию игрока
        start_found = False
        
        # 1. Ищем символ '@' — точная позиция старта
        for y in range(map_height):
            for x in range(map_width):
                if self.current_map[y][x] == '@':
                    self.player.x = x
                    self.player.y = y
                    self.current_map[y][x] = '.'
                    start_found = True
                    break
            if start_found:
                break
        
        # 2. Если '@' нет — ищем лестницу 'S'
        if not start_found:
            for y in range(map_height):
                for x in range(map_width):
                    if self.current_map[y][x] == 'S':
                        self.player.x = x
                        self.player.y = y
                        start_found = True
                        break
                if start_found:
                    break
        
        # 3. Если ничего не нашли — центр карты
        if not start_found:
            self.player.x = map_width // 2
            self.player.y = map_height // 2
        
        # self.fov_system.compute_fov(self.player.x, self.player.y)
 
        # Вычисляем FOV с учётом источников света
        self.fov_system.compute_fov(
            self.player.x, 
            self.player.y,
            self.current_map,  # ← Передаём карту для проверки препятствий
            self.light_sources
        )
 
        # Спавним сущности процедурно
        self.entities = []
        self._spawn_entities_on_map()
        
        self.add_message(f"Загружена карта: {map_data['name']}")
    
    def _spawn_entities_on_map(self):
        """Заспавнить сущности на фиксированной карте."""
        if not self.current_map:
            return
        
        map_height = len(self.current_map)
        map_width = len(self.current_map[0]) if map_height > 0 else 0
        
        # Собираем все проходимые клетки
        all_walkable = []
        for y in range(map_height):
            for x in range(map_width):
                if self.current_map[y][x] == '.':
                    all_walkable.append((x, y))
        
        if not all_walkable:
            return
        
        random.shuffle(all_walkable)
        occupied = {(self.player.x, self.player.y)}
        
        # Спавним персонажей
        char_pool = self.db.get_dungeon_spawn_pool('character', self.player.san)
        total_chars = 0
        max_chars = 4
        
        for spawn_entry in char_pool:
            if total_chars >= max_chars:
                break
            
            entity_id = spawn_entry['entity_id']
            max_count = min(spawn_entry['max_count'], 2)
            
            for _ in range(max_count):
                if total_chars >= max_chars:
                    break
                
                for _ in range(20):
                    if not all_walkable:
                        break
                    x, y = all_walkable.pop(0)
                    if (x, y) not in occupied:
                        entity = self.entity_factory.create_character(entity_id)
                        if entity:
                            entity.x = x
                            entity.y = y
                            self.entities.append(entity)
                            occupied.add((x, y))
                            total_chars += 1
                            break
        
        # Спавним предметы
        item_pool = self.db.get_dungeon_spawn_pool('item', self.player.san)
        total_items = 0
        notes_spawned = 0
        max_notes = 6
        max_items = 10
        
        for spawn_entry in item_pool:
            if total_items >= max_items:
                break
            
            entity_id = spawn_entry['entity_id']
            max_count = spawn_entry['max_count']
            
            item_data = self.db.get_item(entity_id)
            is_note = item_data and item_data.get('type') == 'note'
            
            if is_note and notes_spawned >= max_notes:
                continue
            
            for _ in range(max_count):
                if total_items >= max_items:
                    break
                
                for _ in range(20):
                    if not all_walkable:
                        break
                    x, y = all_walkable.pop(0)
                    if (x, y) not in occupied:
                        entity = self.entity_factory.create_item(entity_id)
                        if entity:
                            entity.x = x
                            entity.y = y
                            self.entities.append(entity)
                            occupied.add((x, y))
                            total_items += 1
                            if is_note:
                                notes_spawned += 1
                            break
                        
    # def _load_room(self, room_id: str):
    #     """Загрузить комнату из блочного генератора."""
    #     from engine.map_builder import BlockMapGenerator
    #     generator = BlockMapGenerator(self.db)
    #     # СЛУЧАЙНОЕ КОЛИЧЕСТВО БЛОКОВ: от 30 до 50
    #     max_blocks = random.randint(30, 50)
    #     self.current_map, meta = generator.generate(self.player.san, max_blocks)
        
    #     if not self.current_map:
    #         self.add_message("Ошибка генерации карты!")
    #         return
        
    #     map_height = len(self.current_map)
    #     map_width = len(self.current_map[0]) if map_height > 0 else 0
    #     self.fov_system = FOVSystem(map_width, map_height)
    #     self.fov_system.initialize(self.current_map)
        
    #     self.fov_system.light_radius = self.light_radius
        
    #     # Сохраняем источники света
    #     self.light_sources = meta.get('light_sources', [])
        
    #     # НАХОДИМ БЛОК С ПРОХОДОМ ДЛЯ ИГРОКА
    #     start_found = False
    #     # Сначала ищем блок с проходами
    #     for y in range(map_height):
    #         for x in range(map_width):
    #             if self.current_map[y][x] == '@':
    #                 # Проверяем, есть ли проходы вокруг
    #                 has_passage = False
    #                 for dy in [-1, 0, 1]:
    #                     for dx in [-1, 0, 1]:
    #                         ny, nx = y + dy, x + dx
    #                         if 0 <= ny < map_height and 0 <= nx < map_width:
    #                             if self.current_map[ny][nx] == '.':
    #                                 has_passage = True
    #                                 break
    #                     if has_passage:
    #                         break
                    
    #                 if has_passage:
    #                     self.player.x = x
    #                     self.player.y = y
    #                     self.current_map[y][x] = '.'
    #                     start_found = True
    #                     break
    #         if start_found:
    #             break
        
    #     # Если не нашли подходящее место, ставим в центр проходимой клетки
    #     if not start_found:
    #         for y in range(map_height):
    #             for x in range(map_width):
    #                 if self.current_map[y][x] == '.':
    #                     self.player.x = x
    #                     self.player.y = y
    #                     start_found = True
    #                     break
    #             if start_found:
    #                 break
            
    #         # Если всё ещё не нашли, ставим в центр
    #         if not start_found:
    #             self.player.x = map_width // 2
    #             self.player.y = map_height // 2
        
    #     # Вычисляем начальный FOV
    #     self.fov_system.compute_fov(self.player.x, self.player.y)
        
    #     # Спавним сущности
    #     self.entities = []
    #     self._spawn_entities_across_blocks(meta)
        
    #     self.add_message(f"Комната загружена. Блоков: {meta.get('blocks_placed', 0)}")
    
    # def _spawn_entities_across_blocks(self, meta: Dict):
    #     """Заспавнить сущности, распределяя их по разным блокам."""
    #     if not self.current_map:
    #         return
        
    #     map_height = len(self.current_map)
    #     map_width = len(self.current_map[0]) if map_height > 0 else 0
        
    #     # Собираем проходимые клетки, ИСКЛЮЧАЯ проходы между блоками
    #     all_walkable = []
    #     for y in range(map_height):
    #         for x in range(map_width):
    #             if self.current_map[y][x] != '.':
    #                 continue
                
    #             # Проверяем, является ли клетка проходом между блоками
    #             # Проход = клетка '.', у которой есть стены с противоположных сторон
    #             is_passage = False
                
    #             # Горизонтальный проход: стены слева и справа
    #             left_wall = (x == 0 or self.current_map[y][x-1] == '#')
    #             right_wall = (x == map_width - 1 or self.current_map[y][x+1] == '#')
    #             if left_wall and right_wall:
    #                 is_passage = True
                
    #             # Вертикальный проход: стены сверху и снизу
    #             top_wall = (y == 0 or self.current_map[y-1][x] == '#')
    #             bottom_wall = (y == map_height - 1 or self.current_map[y+1][x] == '#')
    #             if top_wall and bottom_wall:
    #                 is_passage = True
                
    #             # Не спавним на проходах
    #             if not is_passage:
    #                 all_walkable.append((x, y))
        
    #     if not all_walkable:
    #         return
        
    #     # Перемешиваем
    #     random.shuffle(all_walkable)
        
    #     # Отслеживаем занятые позиции
    #     occupied = {(self.player.x, self.player.y)}
        
    #     # Спавним персонажей (ограничиваем)
    #     char_pool = self.db.get_dungeon_spawn_pool('character', self.player.san)
    #     total_chars = 0
    #     max_chars = 4
        
    #     for spawn_entry in char_pool:
    #         if total_chars >= max_chars:
    #             break
            
    #         entity_id = spawn_entry['entity_id']
    #         max_count = min(spawn_entry['max_count'], 2)
            
    #         for _ in range(max_count):
    #             if total_chars >= max_chars:
    #                 break
                
    #             for _ in range(20):
    #                 if not all_walkable:
    #                     break
    #                 x, y = all_walkable.pop(0)
    #                 if (x, y) not in occupied:
    #                     entity = self.entity_factory.create_character(entity_id)
    #                     if entity:
    #                         entity.x = x
    #                         entity.y = y
    #                         self.entities.append(entity)
    #                         occupied.add((x, y))
    #                         total_chars += 1
    #                         break
        
    #     # Спавним предметы (ограничиваем записки!)
    #     item_pool = self.db.get_dungeon_spawn_pool('item', self.player.san)
    #     total_items = 0
    #     notes_spawned = 0
    #     max_notes = 6
    #     max_items = 20
        
    #     print(f"[DEBUG] Пул предметов: {[item['entity_id'] for item in item_pool]}")
        
    #     for spawn_entry in item_pool:
    #         if total_items >= max_items:
    #             break
            
    #         entity_id = spawn_entry['entity_id']
    #         max_count = spawn_entry['max_count']
            
    #         #ОТЛАДКА: Проверяем, ключ ли это
    #         item_data = self.db.get_item(entity_id)
    #         is_key = item_data and item_data.get('type') == 'key'
    #         if is_key:
    #             print(f"[DEBUG] Ключ найден в пуле: {entity_id}")            
            
    #         item_data = self.db.get_item(entity_id)
    #         is_note = item_data and item_data.get('type') == 'note'
            
    #         if is_note and notes_spawned >= max_notes:
    #             continue
            
    #         for _ in range(max_count):
    #             if total_items >= max_items:
    #                 break
                
    #             for _ in range(20):
    #                 if not all_walkable:
    #                     break
    #                 x, y = all_walkable.pop(0)
    #                 if (x, y) not in occupied:
    #                     entity = self.entity_factory.create_item(entity_id)
    #                     if entity:
    #                         entity.x = x
    #                         entity.y = y
    #                         self.entities.append(entity)
    #                         occupied.add((x, y))
    #                         total_items += 1
    #                         if is_note:
    #                             notes_spawned += 1
                                
    #                         # ← ОТЛАДКА: Выводим информацию о ключе
    #                         if is_key:
    #                             print(f"[DEBUG] Ключ заспавнен: {entity_id} в ({x},{y})")
    #                             print(f"[DEBUG] Символ: {getattr(entity, 'symbol', 'НЕТ')}")
    #                             print(f"[DEBUG] Цвет: {getattr(entity, 'color', 'НЕТ')}")                                
                                
    #                         break                
                    
    def _clear_passages_from_entities(self):
        """Убрать сущности с проходов между блоками."""
        if not self.current_map:
            return
        
        map_height = len(self.current_map)
        map_width = len(self.current_map[0]) if map_height > 0 else 0
        
        # Находим все проходы (клетки '.' на границах или рядом с стенами)
        passage_positions = set()
        for y in range(map_height):
            for x in range(map_width):
                if self.current_map[y][x] == '.':
                    # Проверяем, есть ли рядом стена
                    has_wall_neighbor = False
                    for dy in [-1, 0, 1]:
                        for dx in [-1, 0, 1]:
                            ny, nx = y + dy, x + dx
                            if 0 <= ny < map_height and 0 <= nx < map_width:
                                if self.current_map[ny][nx] == '#':
                                    has_wall_neighbor = True
                                    break
                        if has_wall_neighbor:
                            break
                    
                    if has_wall_neighbor:
                        passage_positions.add((x, y))
        
        # Убираем сущности с проходов
        for entity in self.entities[:]:
            if (entity.x, entity.y) in passage_positions:
                # Находим новую позицию для сущности
                for _ in range(50):
                    new_x = random.randint(0, map_width - 1)
                    new_y = random.randint(0, map_height - 1)
                    if (new_x, new_y) not in passage_positions and \
                       (new_x, new_y) != (self.player.x, self.player.y) and \
                       self.current_map[new_y][new_x] == '.':
                        entity.x = new_x
                        entity.y = new_y
                        break       
                
    def handle_events(self):
        """Обработка ввода."""
        for event in tcod.event.wait():
            if event.type == "QUIT":
                return False
            if event.type != "KEYDOWN":
                continue

            if self.state == GameState.CLASS_SELECTION:
                if not self._handle_class_selection(event):
                    return False
            elif self.state == GameState.PLAYING:
                if not self._handle_playing(event):
                    return False
            elif self.state == GameState.COMBAT:
                if not self._handle_combat(event):
                    return False
            elif self.state == GameState.DIALOGUE:
                if not self._handle_dialogue(event):
                    return False
            elif self.state == GameState.GAME_OVER:
                if event.sym == tcod.event.KeySym.ESCAPE:
                    return False

            if self.player and not self.player.is_alive():
                self.state = GameState.GAME_OVER
                self.add_message("Вы погибли. Тени сомкнулись над вами...")
            break
        return True

    def _handle_class_selection(self, event) -> bool:
        if event.sym == tcod.event.KeySym.ESCAPE:
            return False
        elif event.sym in (tcod.event.KeySym.UP, tcod.event.KeySym.K):
            self.selected_class_index = (self.selected_class_index - 1) % len(self.available_classes)
        elif event.sym in (tcod.event.KeySym.DOWN, tcod.event.KeySym.J):
            self.selected_class_index = (self.selected_class_index + 1) % len(self.available_classes)
        elif event.sym == tcod.event.KeySym.RETURN:
            selected = self.available_classes[self.selected_class_index]
            self.start_game_with_class(selected['id'])
        return True

    def _handle_playing(self, event) -> bool:
        
        # Закрытие помощи по Esc
        if self.showing_help:
            if event.sym in (tcod.event.KeySym.ESCAPE, tcod.event.KeySym.SLASH, tcod.event.KeySym.F1):
                self.showing_help = False
                return True
            # Блокируем остальные действия пока открыта помощь
            return True
        
        if event.sym == tcod.event.KeySym.ESCAPE or event.sym == tcod.event.KeySym.Q:
            return False
        
        if event.sym == tcod.event.KeySym.ESCAPE or event.sym == tcod.event.KeySym.Q:
            return False
        elif event.sym in (tcod.event.KeySym.UP, tcod.event.KeySym.K):
            self._try_move(0, -1)
        elif event.sym in (tcod.event.KeySym.DOWN, tcod.event.KeySym.J):
            self._try_move(0, 1)
        elif event.sym in (tcod.event.KeySym.LEFT, tcod.event.KeySym.H):
            self._try_move(-1, 0)
        elif event.sym in (tcod.event.KeySym.RIGHT, tcod.event.KeySym.L):
            self._try_move(1, 0)
        elif event.sym == tcod.event.KeySym.E:
            self._try_interact()
        elif event.sym == tcod.event.KeySym.I:
            self._show_inventory()
        elif event.sym == tcod.event.KeySym.A:
            self._enter_attack_mode()
        elif event.sym == tcod.event.KeySym.R:
            self._try_read_note()
        elif event.sym == tcod.event.KeySym.SLASH or event.sym == tcod.event.KeySym.F1:
            self.showing_help = not self.showing_help            
          
        return True

    def _enter_attack_mode(self):
        """Войти в режим атаки."""
        directions = [(0, -1), (0, 1), (-1, 0), (1, 0)]
        for dx, dy in directions:
            x, y = self.player.x + dx, self.player.y + dy
            for entity in self.entities:
                if isinstance(entity, Character) and entity.x == x and entity.y == y:
                    if entity.type == 'enemy' or entity.ai_behavior == 'aggressive':
                        self.current_enemy = entity
                        self.state = GameState.COMBAT
                        self.add_message(f"БОЙ: {entity.name} (HP: {entity.hp}/{entity.max_hp})")
                        self.add_message("Space — атака | Esc — сбежать")
                        return
                    else:
                        self.add_message(f"{entity.name} не враг.")
                        return
        self.add_message("Рядом нет врагов.")

    def _handle_combat(self, event) -> bool:
        if self.current_enemy and not self.current_enemy.is_alive():
            self.add_message(f"{self.current_enemy.name} повержен!")
            if self.current_enemy in self.entities:
                self.entities.remove(self.current_enemy)
            self.current_enemy = None
            self.state = GameState.PLAYING
            self.add_message("Победа!")
            return True

        if not self.player.is_alive():
            self.state = GameState.GAME_OVER
            self.add_message("Вас одолели тени...")
            return True

        if self.current_enemy:
            dx = abs(self.current_enemy.x - self.player.x)
            dy = abs(self.current_enemy.y - self.player.y)
            if dx + dy > 1:
                self.add_message("Враг сбежал!")
                self.current_enemy = None
                self.state = GameState.PLAYING
                return True

        if event.sym == tcod.event.KeySym.ESCAPE:
            if random.random() > 0.5:
                self.add_message("Вы сбежали!")
                self.current_enemy = None
                self.state = GameState.PLAYING
            else:
                self.add_message("Не удалось сбежать!")
                if self.current_enemy:
                    hit, dmg, msg = perform_attack(self.current_enemy, self.player)
                    self.add_message(f"Враг атакует: {msg}")
                    if not self.player.is_alive():
                        self.state = GameState.GAME_OVER
            return True

        if event.sym == tcod.event.KeySym.SPACE or event.sym == tcod.event.KeySym.RETURN:
            if self.current_enemy:
                hit, damage, message = perform_attack(self.player, self.current_enemy)
                self.add_message(message)
                if not self.current_enemy.is_alive():
                    self.add_message(f"{self.current_enemy.name} погибает!")
                    if self.current_enemy in self.entities:
                        self.entities.remove(self.current_enemy)
                    self.current_enemy = None
                    self.state = GameState.PLAYING
                    self.add_message("Победа!")
                    return True
                if self.current_enemy and self.current_enemy.ai_behavior == 'aggressive':
                    enemy_hit, enemy_dmg, enemy_msg = perform_attack(self.current_enemy, self.player)
                    self.add_message(enemy_msg)
                    self.add_message(f"Враг HP: {self.current_enemy.hp}/{self.current_enemy.max_hp}")
                    if not self.player.is_alive():
                        self.state = GameState.GAME_OVER
                        self.add_message("Вы погибли...")
            return True

    def _handle_dialogue(self, event) -> bool:
        if event.sym == tcod.event.KeySym.ESCAPE:
            result = self.dialogue_engine.finish()
            self._apply_dialogue_result(result)
            self.state = GameState.PLAYING
            self.current_dialogue_text = ''
        elif event.sym == tcod.event.KeySym.SPACE or event.sym == tcod.event.KeySym.RETURN:
            text = self.dialogue_engine.advance()
            if text is None:
                result = self.dialogue_engine.finish()
                self._apply_dialogue_result(result)
                self.state = GameState.PLAYING
                self.current_dialogue_text = ''
            else:
                self.current_dialogue_text = text
        return True

    def _try_move(self, dx: int, dy: int):
        """Попытка двигаться."""
        new_x = self.player.x + dx
        new_y = self.player.y + dy
        
        # Проверяем границы карты
        if not (0 <= new_y < len(self.current_map) and 0 <= new_x < len(self.current_map[0])):
            return
        
        # Проверяем тайл
        tile = self.current_map[new_y][new_x]
        
        # Стены и пустота — блокируют
        if tile in ('#', ' '):
            return
        
        # ← НОВОЕ: Закрытая дверь — блокирует, нужен ключ
        if tile == 'd':
            self._try_open_locked_door(new_x, new_y)
            return
        
        # Проверяем NPC
        for entity in self.entities:
            if isinstance(entity, Character) and entity.x == new_x and entity.y == new_y:
                self.add_message(f"Перед вами — {entity.name}.")
                return
        
        # Двигаемся
        self.player.x = new_x
        self.player.y = new_y
        
        # Проверяем подбор предметов
        self._check_pickup()
        
        # Проверяем триггеры
        trigger_result = self.trigger_system.check_enter_trigger(new_x, new_y, self.player)
        for msg in trigger_result.messages:
            self.add_message(msg)
        
        # Проверяем триггеры безумия
        san_triggers = self.trigger_system.check_san_trigger(new_x, new_y, self.player)
        for msg in san_triggers:
            self.add_message(msg)

    def _try_open_locked_door(self, x: int, y: int):
        """Попытка открыть запертую дверь."""
        # Ищем ключ в инвентаре
        key_item = None
        for item in self.player.inventory:
            if hasattr(item, 'use_effect') and item.use_effect == 'unlock_door':
                key_item = item
                break
        
        if key_item:
            # Открываем дверь
            self.current_map[y][x] = 'D'  # Меняем на открытую дверь
            
            # Удаляем ключ из инвентаря
            self.player.inventory.remove(key_item)
            
            self.add_message(f"Вы отперли дверь ключом '{key_item.name}'.")
        else:
            self.add_message("Дверь заперта. Нужен ключ.")
        
    def _check_pickup(self):
        """Проверить, есть ли предмет под игроком."""
        for entity in self.entities[:]:
            if hasattr(entity, 'x') and hasattr(entity, 'y'):
                if entity.x == self.player.x and entity.y == self.player.y:
                    # Если это записка - читаем автоматически
                    if hasattr(entity, 'type') and entity.type == 'note':
                        self._read_note(entity)
                    else:
                        # Обычный предмет - в инвентарь
                        self.player.inventory.append(entity)
                        self.entities.remove(entity)
                        self.add_message(f"Подобрали: {entity.name}")
                    
    def _try_interact(self):
        """Попытка взаимодействия с соседним NPC."""
        directions = [(0, -1), (0, 1), (-1, 0), (1, 0), (0, 0)]
        for dx, dy in directions:
            x, y = self.player.x + dx, self.player.y + dy
            for entity in self.entities:
                if isinstance(entity, Character) and entity.x == x and entity.y == y:
                    if entity.dialogue_id:
                        if self.dialogue_engine.start_dialogue(entity.dialogue_id):
                            self.state = GameState.DIALOGUE
                            self.current_dialogue_speaker = entity.name
                            text = self.dialogue_engine.advance()
                            if text:
                                self.current_dialogue_text = text
                            return
                    else:
                        self.add_message(f"{entity.name} не желает разговаривать.")
                        return
        self.add_message("Рядом никого нет.")
    
    def _apply_dialogue_result(self, result: Optional[dict]):
        if not result:
            return
        if result.get('sanity_change', 0) != 0:
            self.player.change_san(result['sanity_change'])
        for item_id in result.get('items_given', []):
            item = self.entity_factory.create_item(item_id)
            if item:
                self.player.inventory.append(item)
                self.add_message(f"Получено: {item.name}")

    def _show_inventory(self):
        """Показать инвентарь."""
        if not self.player.inventory:
            self.add_message("Инвентарь пуст.")
            return
        
        items_list = []
        for item in self.player.inventory:
            if hasattr(item, 'use_effect') and item.use_effect == 'unlock_door':
                items_list.append(f"{item.name} (ключ)")
            else:
                items_list.append(item.name)
        
        self.add_message(f"С собой: {', '.join(items_list)}")
    
    def _read_note(self, note):
        """Прочитать записку."""
        if hasattr(self, 'quest_system') and self.quest_system:
            if note.id in self.quest_system.found_notes:
                self.add_message("Вы уже читали эту записку.")
                return
            content = self.quest_system.add_note(note.id)
            if content:
                self.add_message(f"=== {note.name} ===")
                self.add_message(content)
                sanity_damage = getattr(note, 'sanity_damage', 0)
                if sanity_damage != 0:
                    self.player.change_san(sanity_damage)
                    effect_text = "теряете" if sanity_damage < 0 else "получаете"
                    self.add_message(f"Вы {effect_text} {abs(sanity_damage)} рассудка...")
                if note in self.entities:
                    self.entities.remove(note)
                self._check_quest_completion()
        else:
            self.add_message(f"Вы нашли: {note.name}")
            self.player.inventory.append(note)
            if note in self.entities:
                self.entities.remove(note)

    def _try_read_note(self):
        """Попытаться прочитать записку рядом."""
        directions = [(0, -1), (0, 1), (-1, 0), (1, 0), (0, 0)]
        for dx, dy in directions:
            x, y = self.player.x + dx, self.player.y + dy
            for entity in self.entities:
                if hasattr(entity, 'type') and entity.type == 'note':
                    if entity.x == x and entity.y == y:
                        if entity.id in self.quest_system.found_notes:
                            self.add_message("Вы уже читали эту записку.")
                            return
                        content = self.quest_system.add_note(entity.id)
                        if content:
                            self.add_message(f"=== {entity.name} ===")
                            self.add_message(content)
                            sanity_damage = getattr(entity, 'sanity_damage', 0)
                            if sanity_damage != 0:
                                self.player.change_san(sanity_damage)
                                effect_text = "теряете" if sanity_damage < 0 else "получаете"
                                self.add_message(f"Вы {effect_text} {abs(sanity_damage)} рассудка...")
                            if entity in self.entities:
                                self.entities.remove(entity)
                                self.player.inventory.append(entity)
                                self._check_quest_completion()
                            quest_desc = self.quest_system.get_active_quest_descriptions()
                            if quest_desc:
                                self.add_message(f"Квест: {quest_desc[0]}")
                        return
        self.add_message("Рядом нет записок для чтения.")
    
    def _check_quest_completion(self):
        if not hasattr(self, 'quest_system') or not self.quest_system:
            return
        for quest in self.quest_system.completed_quests:
            if quest['id'] not in [q['id'] for q in getattr(self, 'notified_quests', [])]:
                self.add_message("═══════════════════════════════════")
                self.add_message(f"КВЕСТ ВЫПОЛНЕН: {quest['title']}")
                self.add_message("═══════════════════════════════════")
                if not hasattr(self, 'notified_quests'):
                    self.notified_quests = []
                self.notified_quests.append(quest)
        if self.quest_system.is_all_completed():
            self.add_message("═══════════════════════════════════")
            self.add_message("ВСЕ КВЕСТЫ ВЫПОЛНЕНЫ!")
            self.add_message("Тайна клиники раскрыта...")
            self.add_message("═══════════════════════════════════")

    def render(self):
        """Отрисовка кадра."""
        self.renderer.clear()
        if self.state == GameState.CLASS_SELECTION:
            self.renderer.draw_class_selection(self.available_classes, self.selected_class_index)
        else:
            if self.current_map:
                map_height = len(self.current_map)
                map_width = len(self.current_map[0]) if map_height > 0 else 0
                self.renderer.set_camera_position(
                    self.player.x, self.player.y, map_width, map_height
                )
            # Обновляем FOV с источниками света
            if self.fov_system:
                self.fov_system.compute_fov(
                    self.player.x, 
                    self.player.y,
                    self.current_map,
                    getattr(self, 'light_sources', [])
                )
            
            self.renderer.fov_system = self.fov_system
            self.renderer.draw_map(self.current_map)
            self.renderer.draw_entities(self.entities)
            self.renderer.draw_player(self.player)
            self.renderer.draw_hud(self.player)
            self.renderer.draw_messages(self.messages)
            
            if hasattr(self, 'light_sources') and self.light_sources:
                # Используем синхронизированный радиус
                self.renderer.draw_light_sources(
                    self.light_sources,
                    self.player.x,
                    self.player.y,
                    self.fov_system.light_radius  # Используем радиус из FOVSystem
                )                
                
            if self.quest_system:
                quest_desc = self.quest_system.get_active_quest_descriptions()
                if quest_desc:
                    self.renderer.draw_quests(quest_desc)
            if self.state == GameState.DIALOGUE:
                self.renderer.draw_dialogue(self.current_dialogue_text, self.current_dialogue_speaker)
            if self.state == GameState.GAME_OVER:
                for y in range(SCREEN_HEIGHT):
                    for x in range(SCREEN_WIDTH):
                        self.renderer.console.bg[x, y] = libtcodpy.Color(10, 5, 5)
                self.renderer.console.print(
                    SCREEN_WIDTH // 2 - 10, SCREEN_HEIGHT // 2,
                    "КОНЕЦ. Тени победили.",
                    fg=libtcodpy.Color(180, 50, 50)
                )
                
            if self.showing_help:
                self.renderer.draw_help()                
                
        self.renderer.present(self.context)