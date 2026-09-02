"""Главный игровой движок."""
import random
import time
from typing import List, Optional, Tuple

import tcod
from tcod import libtcodpy

from engine.clinic_font import apply_sprite_mode
from engine.constants import (
    BLOCKING_TILES,
    BRED_MAP_ID,
    BRED_SAN_THRESHOLD,
    CLASS_GLIMPSES,
    DOOR_TILES,
    DOUBLE_SAN_THRESHOLD,
    ending_text,
    LOCKED_DOOR_HINTS,
    LOCKED_DOOR_TILES,
    NOTE_POSTSCRIPTS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TILE_BUMP_MESSAGES,
    TRANSITION_TILES,
    WALKABLE_TILES,
)
from engine.db_loader import DBLoader
from engine.dialogue_engine import DialogueEngine
from engine.entity_factory import Character, EntityFactory, Player
from engine.fov_system import FOVSystem
from engine.quest_system import QuestSystem, can_pass_fog, debt_face, has_debt, has_name
from engine.renderer import Renderer
from engine.sanity_system import SanSystem
from engine.save_system import has_save, read_save, restore_map_states, write_save
from engine.sound import play as play_sound
from engine.trigger_system import TriggerSystem

MOVE_STEP_SECONDS = 0.15
MOVE_KEY_DIRS = {
    tcod.event.KeySym.UP: (0, -1),
    tcod.event.KeySym.K: (0, -1),
    tcod.event.KeySym.DOWN: (0, 1),
    tcod.event.KeySym.J: (0, 1),
    tcod.event.KeySym.LEFT: (-1, 0),
    tcod.event.KeySym.H: (-1, 0),
    tcod.event.KeySym.RIGHT: (1, 0),
    tcod.event.KeySym.L: (1, 0),
}


class GameState:
    """Состояние игры."""
    CLASS_SELECTION = 'class_selection'
    PLAYING = 'playing'
    COMBAT = 'combat'
    DIALOGUE = 'dialogue'
    GAME_OVER = 'game_over'
    ENDING = 'ending'


class GameEngine:
    """Главный движок игры."""

    def __init__(self, context):
        self.context = context
        self.db = DBLoader()
        self.entity_factory = EntityFactory(self.db)
        self.trigger_system = TriggerSystem(self.db)
        self.dialogue_engine = DialogueEngine(self.db)
        self.renderer = Renderer(SCREEN_WIDTH, SCREEN_HEIGHT)
        self.renderer.game_engine = self
        self.renderer.load_tile_colors_from_db(self.db)

        self.player: Optional[Player] = None
        self.current_map: List[List[str]] = []
        self.current_map_id: Optional[str] = None
        self.entities: List = []
        self.light_sources: List = []
        self.map_states = {}
        self.messages: List[str] = []
        self.state = GameState.CLASS_SELECTION

        self.available_classes = self.db.get_all_player_classes()
        self.selected_class_index = 0

        self.current_dialogue_text = ''
        self.current_dialogue_speaker = ''
        self.current_dialogue_choices: List[str] = []

        self.fov_system = None
        self.current_enemy = None
        self.san_system = None
        self.quest_system = None
        self.notified_quests = []
        self.fired_triggers = set()
        self.flags = set()
        self.visited_regions = set()
        self.visited_maps = set()
        self.ending_id = None
        self.bred_return = None
        self.bred_seed = 1

        self.showing_help = False
        self.is_inventory_open = False
        self.inventory_selected_index = 0
        self.use_sprites = True
        self._reset_realtime()

    def _reset_realtime(self):
        """Сброс часов кадра и зажатых стрелок."""
        self._fov_dirty = True
        self._held_dirs: List[Tuple[object, int, int]] = []
        self._move_cooldown = 0.0
        self._hold_bump_cell = None
        self._clock = time.perf_counter()

    def _clinic_tileset(self):
        return getattr(getattr(self, "context", None), "tileset", None)

    def _apply_glyph_mode(self, sprites: bool) -> bool:
        tileset = self._clinic_tileset()
        if tileset is None:
            self.use_sprites = bool(sprites)
            return True
        if not apply_sprite_mode(tileset, sprites):
            return False
        self.use_sprites = bool(sprites)
        return True

    def _toggle_glyph_mode(self) -> None:
        """F4: маски или буквы. Книга должна читаться без картинок."""
        want = not getattr(self, "use_sprites", True)
        if not self._apply_glyph_mode(want):
            self.add_message("Чернильница недоступна.")
            return
        if self.use_sprites:
            self.add_message("Вид: картинки.")
        else:
            self.add_message("Вид: буквы.")

    def add_message(self, text: str):
        """Добавить сообщение в лог."""
        self.messages.append(text)
        if len(self.messages) > 20:
            self.messages.pop(0)

    def run(self):
        """Главный цикл: кадр идёт сам, шаг — по часам."""
        running = True
        self._clock = time.perf_counter()
        while running:
            now = time.perf_counter()
            dt = now - self._clock
            self._clock = now
            running = self.handle_events()
            if running:
                self._tick_held_walk(dt)
            if self.san_system:
                for event in self.san_system.update():
                    self.add_message(event)
            self.render()
        self.db.close()

    def start_game_with_class(self, class_id: str):
        """Начать игру с выбранным классом."""
        class_data = self.db.get_player_class(class_id)
        if not class_data:
            return False

        self.player = Player(class_data)
        self.map_states = {}
        self.flags = {f'class_{class_id}'}
        self.visited_regions = set()
        self.visited_maps = set()
        self.ending_id = None
        self.bred_return = None
        self.bred_seed = random.randint(1, 10**9)
        self.fired_triggers = set()
        self.current_dialogue_choices = []
        self._reset_realtime()

        starting_map = self.db.get_starting_map()
        if not starting_map:
            self.add_message("Стартовая карта не найдена в БД!")
            return False

        self._load_map(starting_map['id'], spawn_player=True)

        for item_id in self.player.starting_item_ids:
            item = self.entity_factory.create_item(item_id)
            if item:
                self.player.inventory.append(item)
        self._refresh_player_weapon()

        self.state = GameState.PLAYING
        self.add_message("Вы открываете глаза. Холодный потолок. Где вы?")
        self.add_message("Голова раскалывается. Имени не вспомнить...")

        self.san_system = SanSystem(self.player)
        self.quest_system = QuestSystem(self.db)
        return True

    def save_game(self, path=None) -> bool:
        """Записать один слот. Не сохраняет экран смерти и концовку."""
        if not self.player or self.state in (
            GameState.CLASS_SELECTION, GameState.ENDING, GameState.GAME_OVER
        ):
            self.add_message("Сейчас сохранять нечего.")
            return False
        write_save(self, path)
        self.add_message("Ночь записана. F9 — вернуться.")
        return True

    def _can_save(self) -> bool:
        return bool(self.player) and self.state not in (
            GameState.CLASS_SELECTION, GameState.ENDING, GameState.GAME_OVER
        )

    def quit_and_save(self, path=None) -> bool:
        """Выход: записать слот, если есть партия. Титул, смерть и финал не пишут."""
        if self._can_save():
            write_save(self, path)
        return False

    def load_game(self, path=None) -> bool:
        """Восстановить слот. Класс и карта — из файла."""
        payload = read_save(path)
        if not payload:
            self.add_message("Записи нет. Или она чужая.")
            return False
        class_data = self.db.get_player_class(payload["class_id"])
        if not class_data:
            self.add_message("Класс из записи больше не существует.")
            return False
        self.player = Player(class_data)
        pdata = payload.get("player") or {}
        self.player.x = int(pdata.get("x", 0))
        self.player.y = int(pdata.get("y", 0))
        self.player.max_hp = int(pdata.get("max_hp") or self.player.max_hp)
        self.player.hp = int(pdata.get("hp") or self.player.hp)
        self.player.max_san = int(pdata.get("max_san") or self.player.max_san)
        self.player.san = int(pdata.get("san") or self.player.san)
        self.player.inventory = []
        for item_id in pdata.get("inventory") or []:
            item = self.entity_factory.create_item(item_id)
            if item:
                self.player.inventory.append(item)
        self._refresh_player_weapon()

        self.flags = set(payload.get("flags") or [])
        self.flags.add(f'class_{self.player.id}')
        self.visited_regions = set(payload.get("visited_regions") or [])
        self.visited_maps = set(payload.get("visited_maps") or [])
        self.bred_seed = payload.get("bred_seed") or 1
        self.bred_return = payload.get("bred_return")
        self.notified_quests = list(payload.get("notified_quests") or [])
        self.fired_triggers = set(payload.get("fired_triggers") or [])
        self.ending_id = None
        self.current_enemy = None
        self.showing_help = False
        self.is_inventory_open = False
        self.current_dialogue_choices = []
        self.current_map_id = None
        self.current_map = []
        self.entities = []
        self.messages = []
        self._reset_realtime()
        self.map_states = restore_map_states(self, payload)
        self._apply_glyph_mode(bool(payload.get("use_sprites", True)))

        map_id = payload["map_id"]
        self._load_map(map_id)
        self.player.x = int(pdata.get("x", self.player.x))
        self.player.y = int(pdata.get("y", self.player.y))
        if self.current_map:
            height = len(self.current_map)
            width = len(self.current_map[0]) if height else 0
            if not (0 <= self.player.y < height and 0 <= self.player.x < width):
                self._place_player_on_start()
        self._compute_fov()

        self.san_system = SanSystem(self.player)
        self.quest_system = QuestSystem(self.db)
        self.quest_system.found_notes = list(payload.get("found_notes") or [])
        self.quest_system._check_quest_progress()
        self.state = GameState.PLAYING
        self.add_message("Вы снова открываете глаза. Потолок тот же.")
        return True

    def _save_current_map_state(self):
        """Запомнить открытые двери, сущности и туман войны."""
        if not self.current_map_id or not self.current_map:
            return
        explored = None
        if self.fov_system is not None:
            explored = self.fov_system.explored.copy()
        self.map_states[self.current_map_id] = {
            'tiles': [row[:] for row in self.current_map],
            'entities': list(self.entities),
            'light_sources': list(self.light_sources),
            'explored': explored,
        }

    def _read_map_file(self, file_path: str) -> List[List[str]]:
        with open(file_path, 'r', encoding='utf-8', newline='') as f:
            raw = [line.rstrip('\r\n') for line in f]
        if not raw:
            return []
        width = max(len(row) for row in raw)
        return [list(row.ljust(width)) for row in raw]

    def _collect_light_sources(self) -> List[dict]:
        lights = []
        light_types = self.db.get_light_sources()
        light_symbols = {lt['symbol']: lt for lt in light_types if lt.get('symbol')}
        for y, row in enumerate(self.current_map):
            for x, tile in enumerate(row):
                if tile not in light_symbols:
                    continue
                lt = light_symbols[tile]
                lights.append({
                    'x': x,
                    'y': y,
                    'type': lt['id'],
                    'symbol': lt['symbol'],
                    'color': lt['color'],
                    'radius': int(lt['radius'] or 0),
                    'intensity': float(lt['intensity'] or 0),
                    'flicker': bool(lt.get('flicker', 0)),
                })
        return lights

    def _init_fov(self, explored=None):
        map_height = len(self.current_map)
        map_width = len(self.current_map[0]) if map_height else 0
        self.fov_system = FOVSystem(map_width, map_height)
        self.fov_system.initialize(self.current_map)
        self.fov_system.set_tile_transparency(self.db.get_tile_transparency())
        if explored is not None:
            self.fov_system.explored = explored
        self.renderer.fov_system = self.fov_system
        self._fov_dirty = True

    def _mark_fov_dirty(self):
        self._fov_dirty = True

    def _ensure_fov(self):
        if getattr(self, '_fov_dirty', True):
            self._compute_fov()

    def _compute_fov(self):
        if not self.fov_system or not self.player or not self.current_map:
            return
        self.fov_system.compute_fov(
            self.player.x,
            self.player.y,
            self.current_map,
            self.light_sources,
        )
        self._fov_dirty = False

    def _place_player_on_start(self):
        map_height = len(self.current_map)
        map_width = len(self.current_map[0]) if map_height else 0
        for y, row in enumerate(self.current_map):
            for x, tile in enumerate(row):
                if tile == '@':
                    self.player.x = x
                    self.player.y = y
                    self.current_map[y][x] = '.'
                    return
        for y, row in enumerate(self.current_map):
            for x, tile in enumerate(row):
                if tile in TRANSITION_TILES:
                    self.player.x = x
                    self.player.y = y
                    return
        self.player.x = map_width // 2
        self.player.y = map_height // 2

    def _load_map(self, map_id: str, spawn_player: bool = False):
        """Загрузить карту. Повторный визит восстанавливает состояние сессии."""
        if self.current_map_id and self.current_map_id != map_id:
            self._save_current_map_state()

        map_data = self.db.get_map(map_id)
        if not map_data:
            self.add_message(f"Карта '{map_id}' не найдена в БД!")
            return

        saved = self.map_states.get(map_id)
        self.current_map_id = map_id

        if saved:
            self.current_map = [row[:] for row in saved['tiles']]
            self.entities = list(saved['entities'])
            self.light_sources = list(saved.get('light_sources') or [])
            if not self.light_sources:
                self.light_sources = self._collect_light_sources()
            self._init_fov(saved.get('explored'))
        else:
            if map_id == BRED_MAP_ID:
                from pathlib import Path as _Path
                from engine.bred_floor import generate_bred_floor

                floor1 = _Path(self.db.db_path).resolve().parent / "maps" / "floor_1.txt"
                self.current_map = generate_bred_floor(
                    floor1, getattr(self, "bred_seed", 1)
                )
            else:
                try:
                    self.current_map = self._read_map_file(map_data['file_path'])
                except FileNotFoundError:
                    self.add_message(f"Файл карты не найден: {map_data['file_path']}")
                    return
            if not self.current_map:
                self.add_message("Карта пуста!")
                return
            self.light_sources = self._collect_light_sources()
            self._init_fov()
            self.entities = []
            if spawn_player:
                self._place_player_on_start()
            self._spawn_authored_entities()

        if spawn_player and saved:
            self._place_player_on_start()

        self._compute_fov()
        first_visit = map_id not in self.visited_maps
        self.visited_maps.add(map_id)
        if first_visit and map_data.get('description'):
            self.add_message(map_data['description'])
        else:
            self.add_message(f"{map_data['name']}.")

    def _spawn_authored_entities(self):
        """Расставить NPC и предметы по точкам из БД, не случайным пулом."""
        occupied = {(self.player.x, self.player.y)}
        height = len(self.current_map)
        width = len(self.current_map[0]) if height else 0

        for placement in self.db.get_map_placements(self.current_map_id):
            x, y = placement['x'], placement['y']
            if not (0 <= y < height and 0 <= x < width):
                continue
            if self.current_map[y][x] not in WALKABLE_TILES:
                continue
            if (x, y) in occupied:
                continue

            spawn_type = placement['spawn_type']
            spawn_id = placement['spawn_id']
            if spawn_type == 'character':
                entity = self.entity_factory.create_character(spawn_id)
            else:
                entity = self.entity_factory.create_item(spawn_id)
            if not entity:
                continue
            entity.x = x
            entity.y = y
            self.entities.append(entity)
            occupied.add((x, y))

    def _refresh_player_weapon(self):
        """Урон игрока берётся с лучшего оружия в инвентаре."""
        if not self.player:
            return
        best = self.player.damage_die or '1d6'
        for item in self.player.inventory:
            if getattr(item, 'type', '') == 'weapon' and getattr(item, 'damage_die', ''):
                best = item.damage_die
        self.player.damage_die = best

    def handle_events(self):
        """Обработка ввода. Не блокирует кадр."""
        for event in tcod.event.get():
            if isinstance(event, tcod.event.Quit):
                return self.quit_and_save()
            if isinstance(event, tcod.event.KeyDown):
                if event.sym in MOVE_KEY_DIRS:
                    self._press_move_key(event.sym)
                if (
                    getattr(event, 'repeat', False)
                    and event.sym in MOVE_KEY_DIRS
                    and not self._world_is_frozen()
                ):
                    continue
                if not self._dispatch_key(event):
                    return False
            elif isinstance(event, tcod.event.KeyUp):
                if event.sym in MOVE_KEY_DIRS:
                    self._release_move_key(event.sym)

        if (
            self.player
            and self.state not in (GameState.ENDING, GameState.GAME_OVER, GameState.CLASS_SELECTION)
        ):
            if self.player.san <= 0:
                self._trigger_ending('madness')
            elif not self.player.is_alive():
                self.state = GameState.GAME_OVER
                self.add_message("Вы погибли. Тени сомкнулись над вами...")
        return True

    def _dispatch_key(self, event) -> bool:
        if event.sym == tcod.event.KeySym.F4:
            self._toggle_glyph_mode()
            return True
        if self.state == GameState.CLASS_SELECTION:
            return self._handle_class_selection(event)
        if self.state == GameState.PLAYING:
            return self._handle_playing(event)
        if self.state == GameState.COMBAT:
            return self._handle_combat(event)
        if self.state == GameState.DIALOGUE:
            return self._handle_dialogue(event)
        if self.state == GameState.ENDING:
            if event.sym in (
                tcod.event.KeySym.ESCAPE,
                tcod.event.KeySym.RETURN,
                tcod.event.KeySym.SPACE,
            ):
                return False
            return True
        if self.state == GameState.GAME_OVER:
            if event.sym == tcod.event.KeySym.ESCAPE:
                return False
        return True

    def _world_is_frozen(self) -> bool:
        """Диалог, бой, инвентарь и титул останавливают коридор."""
        if self.state != GameState.PLAYING:
            return True
        if self.showing_help or self.is_inventory_open:
            return True
        return False

    def _press_move_key(self, sym):
        self._held_dirs = [item for item in self._held_dirs if item[0] != sym]
        dx, dy = MOVE_KEY_DIRS[sym]
        self._held_dirs.append((sym, dx, dy))

    def _release_move_key(self, sym):
        self._held_dirs = [item for item in self._held_dirs if item[0] != sym]
        self._hold_bump_cell = None
        if not self._held_dirs:
            self._move_cooldown = 0.0

    def _tick_held_walk(self, dt: float):
        """Один шаг ~150 мс, пока стрелка зажата. Модалки стопают мир."""
        if self._world_is_frozen() or not self.player or not self._held_dirs:
            if not self._held_dirs:
                self._move_cooldown = 0.0
            return
        self._move_cooldown -= dt
        if self._move_cooldown > 0:
            return
        _sym, dx, dy = self._held_dirs[-1]
        self._try_move(dx, dy)
        self._move_cooldown = MOVE_STEP_SECONDS

    def _handle_class_selection(self, event) -> bool:
        if event.sym == tcod.event.KeySym.ESCAPE:
            return False
        elif event.sym in (tcod.event.KeySym.UP, tcod.event.KeySym.K):
            self.selected_class_index = (
                (self.selected_class_index - 1) % len(self.available_classes)
            )
        elif event.sym in (tcod.event.KeySym.DOWN, tcod.event.KeySym.J):
            self.selected_class_index = (
                (self.selected_class_index + 1) % len(self.available_classes)
            )
        elif event.sym == tcod.event.KeySym.RETURN:
            selected = self.available_classes[self.selected_class_index]
            self.start_game_with_class(selected['id'])
        elif event.sym == tcod.event.KeySym.C:
            if has_save():
                self.load_game()
            else:
                self.add_message("Записи нет.")
        return True

    def _handle_playing(self, event) -> bool:
        """Обработка ввода в режиме игры."""
        if self.showing_help:
            if event.sym in (
                tcod.event.KeySym.SLASH,
                tcod.event.KeySym.QUESTION,
                tcod.event.KeySym.F1,
                tcod.event.KeySym.ESCAPE,
            ):
                self.showing_help = False
            return True

        if self.is_inventory_open:
            return self._handle_inventory_input(event)

        if event.sym in (tcod.event.KeySym.Q, tcod.event.KeySym.ESCAPE):
            return self.quit_and_save()

        if event.sym in MOVE_KEY_DIRS:
            return True
        elif event.sym == tcod.event.KeySym.A:
            self._try_attack()
        elif event.sym == tcod.event.KeySym.E:
            self._try_interact()
        elif event.sym == tcod.event.KeySym.R:
            self._try_read()
        elif event.sym == tcod.event.KeySym.I:
            self.is_inventory_open = True
            self.inventory_selected_index = 0
        elif event.sym in (
            tcod.event.KeySym.SLASH,
            tcod.event.KeySym.QUESTION,
            tcod.event.KeySym.F1,
        ):
            self.showing_help = True
        elif event.sym == tcod.event.KeySym.F5:
            self.save_game()
        elif event.sym == tcod.event.KeySym.F9:
            self.load_game()
        return True

    def _handle_inventory_input(self, event) -> bool:
        """Обработка ввода когда инвентарь открыт."""
        if event.sym in (tcod.event.KeySym.UP, tcod.event.KeySym.K):
            self.inventory_selected_index = max(0, self.inventory_selected_index - 1)
        elif event.sym in (tcod.event.KeySym.DOWN, tcod.event.KeySym.J):
            max_index = len(self.player.inventory)
            self.inventory_selected_index = min(max_index, self.inventory_selected_index + 1)
        elif event.sym in (tcod.event.KeySym.I, tcod.event.KeySym.ESCAPE):
            self.is_inventory_open = False
        elif event.sym in (tcod.event.KeySym.E, tcod.event.KeySym.RETURN):
            if self.inventory_selected_index >= len(self.player.inventory):
                self.is_inventory_open = False
            else:
                self._use_selected_item()
        return True

    def _use_selected_item(self):
        """Использовать выбранный предмет в инвентаре."""
        if self.inventory_selected_index >= len(self.player.inventory):
            return
        item = self.player.inventory[self.inventory_selected_index]
        self._use_item(item)
        if self.inventory_selected_index >= len(self.player.inventory):
            self.inventory_selected_index = max(0, len(self.player.inventory))

    def _use_item(self, item):
        """Использовать предмет."""
        effect = getattr(item, 'use_effect', '') or ''
        item_type = getattr(item, 'type', '')

        if effect == 'heal' or (item_type == 'consumable' and getattr(item, 'healing', 0)):
            healing = getattr(item, 'healing', 0)
            if healing > 0:
                old_hp = self.player.hp
                self.player.hp = min(self.player.max_hp, self.player.hp + healing)
                self.add_message(
                    f"Вы используете '{item.name}'. Восстановлено {self.player.hp - old_hp} HP."
                )
                self.player.inventory.remove(item)
            else:
                self.add_message("Предмет не оказывает эффекта.")
            return

        if effect == 'restore_sanity' or (
            item_type == 'consumable' and getattr(item, 'sanity_restore', 0)
        ):
            restore = getattr(item, 'sanity_restore', 0)
            if restore > 0:
                old_san = self.player.san
                self.player.san = min(self.player.max_san, self.player.san + restore)
                self.add_message(
                    f"Вы используете '{item.name}'. Восстановлено {self.player.san - old_san} рассудка."
                )
                self.player.inventory.remove(item)
            else:
                self.add_message("Предмет не оказывает эффекта.")
            return

        if effect == 'unlock_door' or item_type == 'key':
            self.add_message("Ключи используются автоматически при взаимодействии с дверью.")
            return

        if item_type == 'note' or effect == 'read_note':
            content = getattr(item, 'content', '') or ''
            if not content and self.quest_system:
                note_data = self.db.get_note(item.id)
                content = (note_data or {}).get('content', '') or getattr(item, 'description', '')
            self._present_testimony(item.name, content or "Чернила выцвели.")
            return

        self.add_message(f"Нельзя использовать {item.name}.")

    def _character_at(self, x: int, y: int) -> Optional[Character]:
        for entity in self.entities:
            if isinstance(entity, Character) and entity.x == x and entity.y == y:
                return entity
        return None

    def _is_hostile(self, entity: Character) -> bool:
        return entity.type == 'enemy' or entity.ai_behavior == 'aggressive'

    def _start_combat(self, entity: Character):
        self.current_enemy = entity
        self.state = GameState.COMBAT
        self.add_message(f"БОЙ: {entity.name} (HP: {entity.hp}/{entity.max_hp})")
        self.add_message("Space — атака | Esc — сбежать")

    def _try_attack(self):
        """Атаковать соседнего врага."""
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            entity = self._character_at(self.player.x + dx, self.player.y + dy)
            if not entity:
                continue
            if self._is_hostile(entity):
                self._start_combat(entity)
                return
            if getattr(entity, 'id', '') == 'player_double':
                self.add_message(f"{entity.name} не враг. Рука проходит сквозь халат.")
                self.player.change_san(-4)
                self._maybe_spawn_double()
                return
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
                    _hit, _dmg, msg = perform_attack(self.current_enemy, self.player)
                    self.add_message(f"Враг атакует: {msg}")
                    if not self.player.is_alive():
                        self.state = GameState.GAME_OVER
            return True

        if event.sym in (tcod.event.KeySym.SPACE, tcod.event.KeySym.RETURN):
            if self.current_enemy:
                _hit, _damage, message = perform_attack(self.player, self.current_enemy)
                self.add_message(message)
                if not self.current_enemy.is_alive():
                    self.add_message(f"{self.current_enemy.name} погибает!")
                    if self.current_enemy in self.entities:
                        self.entities.remove(self.current_enemy)
                    self.current_enemy = None
                    self.state = GameState.PLAYING
                    self.add_message("Победа!")
                    return True
                if self.current_enemy and self._is_hostile(self.current_enemy):
                    _eh, _ed, enemy_msg = perform_attack(self.current_enemy, self.player)
                    self.add_message(enemy_msg)
                    self.add_message(
                        f"Враг HP: {self.current_enemy.hp}/{self.current_enemy.max_hp}"
                    )
                    san_hit = getattr(self.current_enemy, 'sanity_damage', 0) or 0
                    if san_hit:
                        self.player.change_san(-abs(san_hit))
                    if not self.player.is_alive():
                        self.state = GameState.GAME_OVER
                        self.add_message("Вы погибли...")
            return True

        if event.sym == tcod.event.KeySym.F5:
            self.save_game()
            return True
        if event.sym == tcod.event.KeySym.F9:
            self.load_game()
            return True

        if event.sym in (
            tcod.event.KeySym.UP, tcod.event.KeySym.DOWN,
            tcod.event.KeySym.LEFT, tcod.event.KeySym.RIGHT,
            tcod.event.KeySym.H, tcod.event.KeySym.J,
            tcod.event.KeySym.K, tcod.event.KeySym.L,
        ):
            self.add_message("Вы в бою. Пробел — удар, Esc — бежать.")
        return True

    def _dialogue_repeat_id(self, dialogue_id: str) -> str:
        mapping = {
            'dialogue_shpilkin_intro': ('spoke_shpilkin', 'dialogue_shpilkin_repeat'),
            'dialogue_nastasya_intro': ('spoke_nastasya', 'dialogue_nastasya_repeat'),
            'dialogue_panteleimon_intro': ('spoke_panteleimon', 'dialogue_panteleimon_repeat'),
            'dialogue_double_intro': ('spoke_double', 'dialogue_double_repeat'),
            'dialogue_innkeeper_intro': ('spoke_innkeeper', 'dialogue_innkeeper_repeat'),
            'dialogue_watchman_intro': ('spoke_watchman', 'dialogue_watchman_repeat'),
            'dialogue_beggar_intro': ('spoke_beggar', 'dialogue_beggar_repeat'),
            'dialogue_archivist_intro': ('spoke_archivist', 'dialogue_archivist_repeat'),
            'dialogue_possessed_intro': ('spoke_possessed', 'dialogue_possessed_repeat'),
        }
        if dialogue_id in mapping:
            flag, repeat_id = mapping[dialogue_id]
            if flag in self.flags:
                return repeat_id
        return dialogue_id

    def _apply_dialogue_view(self, kind: str, text: Optional[str]):
        if kind == 'end':
            result = self.dialogue_engine.finish()
            self._apply_dialogue_result(result)
            if self.state != GameState.ENDING:
                self.state = GameState.PLAYING
            self.current_dialogue_text = ''
            self.current_dialogue_choices = []
            return
        if kind == 'choices':
            self.current_dialogue_choices = self.dialogue_engine.get_choices()
            if self.dialogue_engine.current_dialogue:
                kept = self.dialogue_engine.current_dialogue.last_text
                if kept:
                    self.current_dialogue_text = kept
            return
        self.current_dialogue_choices = []
        self.current_dialogue_text = text or ''

    def _handle_dialogue(self, event) -> bool:
        name = getattr(event.sym, "name", "") or ""
        choice_index = {
            "N1": 0, "N2": 1, "N3": 2, "N4": 3,
            "KP_1": 0, "KP_2": 1, "KP_3": 2, "KP_4": 3,
        }.get(name)
        if choice_index is not None and self.current_dialogue_choices:
            kind, text = self.dialogue_engine.choose(choice_index)
            self._apply_dialogue_view(kind, text)
            return True
        if event.sym == tcod.event.KeySym.ESCAPE:
            result = self.dialogue_engine.finish()
            self._apply_dialogue_result(result)
            if self.state != GameState.ENDING:
                self.state = GameState.PLAYING
            self.current_dialogue_text = ''
            self.current_dialogue_choices = []
        elif event.sym in (tcod.event.KeySym.SPACE, tcod.event.KeySym.RETURN):
            if self.current_dialogue_choices:
                return True
            kind, text = self.dialogue_engine.advance()
            self._apply_dialogue_view(kind, text)
        return True

    def _bump_message(self, x: int, y: int, message: str):
        cell = (x, y)
        if getattr(self, '_hold_bump_cell', None) == cell:
            return
        self._hold_bump_cell = cell
        if message:
            self.add_message(message)

    def _try_move(self, dx: int, dy: int):
        """Попытка двигаться."""
        new_x = self.player.x + dx
        new_y = self.player.y + dy

        if not (0 <= new_y < len(self.current_map) and 0 <= new_x < len(self.current_map[0])):
            self._bump_message(new_x, new_y, "Дальше нет пола — только тьма за зданием.")
            return

        tile = self.current_map[new_y][new_x]

        if tile in BLOCKING_TILES:
            if self._maybe_study_desk(new_x, new_y, tile):
                return
            message = TILE_BUMP_MESSAGES.get(tile)
            if message:
                self._bump_message(new_x, new_y, message)
            else:
                self._bump_message(new_x, new_y, "Не пройти.")
            return

        if tile in DOOR_TILES:
            self._try_open_door(new_x, new_y, tile)
            return

        entity = self._character_at(new_x, new_y)
        if entity:
            if self._is_hostile(entity):
                self._start_combat(entity)
            else:
                self._bump_message(new_x, new_y, f"Перед вами — {entity.name}.")
            return

        if tile not in WALKABLE_TILES:
            self._bump_message(new_x, new_y, "Клетка пустая на вид — и всё же стена.")
            return

        self.player.x = new_x
        self.player.y = new_y
        self._hold_bump_cell = None
        self._check_pickup()

        trigger_result = self.trigger_system.check_enter_trigger(
            new_x, new_y, self.player, self.current_map_id, self.fired_triggers
        )
        self.fired_triggers.update(trigger_result.fired_ids)
        for msg in trigger_result.messages:
            self.add_message(msg)
        if (
            "trigger_whisper" in trigger_result.fired_ids
            and getattr(self.player, "id", "") == "mystic"
            and "mystic_trace" not in self.flags
        ):
            self.flags.add("mystic_trace")
            self.add_message(
                "Шёпот узнаёт вас. Это уже не первый раз — вы просто не помните."
            )
        self._apply_trigger_spawns(trigger_result, new_x, new_y)
        self._check_region(new_x, new_y)
        self._maybe_spawn_double()
        self._check_street_ending()
        self._compute_fov()

    def _apply_trigger_spawns(self, result, x: int, y: int):
        if result.spawn_character_id:
            self._spawn_near(result.spawn_character_id, 'character', x, y)
        if result.spawn_item_id:
            self._spawn_near(result.spawn_item_id, 'item', x, y)

    def _spawn_near(self, spawn_id: str, spawn_type: str, x: int, y: int):
        height = len(self.current_map)
        width = len(self.current_map[0]) if height else 0
        occupied = {(self.player.x, self.player.y)}
        occupied.update((e.x, e.y) for e in self.entities if hasattr(e, 'x'))
        candidates = [(x, y)]
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                candidates.append((x + dx, y + dy))
        for nx, ny in candidates:
            if not (0 <= ny < height and 0 <= nx < width):
                continue
            if self.current_map[ny][nx] not in WALKABLE_TILES:
                continue
            if (nx, ny) in occupied:
                continue
            if spawn_type == 'character':
                entity = self.entity_factory.create_character(spawn_id)
            else:
                entity = self.entity_factory.create_item(spawn_id)
            if not entity:
                return False
            entity.x = nx
            entity.y = ny
            self.entities.append(entity)
            return True
        return False

    def _maybe_spawn_double(self):
        """При низком SAN в коридоре появляется человек в вашем халате."""
        if not self.player or not self.current_map:
            return
        if 'double_spawned' in self.flags:
            return
        if self.player.san > DOUBLE_SAN_THRESHOLD:
            return
        if any(getattr(e, 'id', None) == 'player_double' for e in self.entities):
            self.flags.add('double_spawned')
            return
        spawned = self._spawn_near(
            'player_double', 'character', self.player.x, self.player.y
        )
        if spawned:
            self.flags.add('double_spawned')
            self.add_message(
                "Рядом стоит человек в таком же халате. Лица не разобрать."
            )

    def _try_open_door(self, x: int, y: int, tile: str):
        """Открыть дверь. Запертая требует свой ключ."""
        if tile == 'D':
            self.current_map[y][x] = "'"
            self.add_message("Вы открыли дверь.")
            play_sound("door")
            self._mark_fov_dirty()
            return

        if tile in LOCKED_DOOR_TILES:
            required = self.db.get_door_lock(self.current_map_id, x, y)
            key_item = None
            for item in self.player.inventory:
                is_key = (
                    getattr(item, 'use_effect', '') == 'unlock_door'
                    or getattr(item, 'type', '') == 'key'
                )
                if not is_key:
                    continue
                if required and item.id != required:
                    continue
                key_item = item
                break
            if key_item:
                self.current_map[y][x] = "'"
                self.player.inventory.remove(key_item)
                self.add_message(
                    f"Вы отперли дверь ключом '{key_item.name}'. Ключ сломался в замке."
                )
                play_sound("door")
                self._mark_fov_dirty()
            elif required:
                hint = LOCKED_DOOR_HINTS.get(getattr(self.player, 'id', ''))
                if hint:
                    self.add_message(hint)
                if getattr(self.player, 'id', '') == 'rebel':
                    self.current_map[y][x] = "'"
                    self.player.change_san(-8)
                    self.player.take_damage(1)
                    self.flags.add('broke_door')
                    self.add_message(
                        "Вы выбиваете дверь плечом. Замок орёт. Рассудок — тоже."
                    )
                    play_sound("door")
                    self._mark_fov_dirty()
                    self._maybe_spawn_double()
                    return
                needed = self.entity_factory.create_item(required)
                name = needed.name if needed else "особый ключ"
                self.add_message(f"Дверь заперта. Нужен {name}.")
            else:
                self.add_message("Дверь заперта. Нужен ключ.")

    def _check_pickup(self):
        """Проверить, есть ли предмет под игроком."""
        for entity in self.entities[:]:
            if getattr(entity, 'x', None) != self.player.x:
                continue
            if getattr(entity, 'y', None) != self.player.y:
                continue
            if isinstance(entity, Character):
                continue
            if getattr(entity, 'type', '') == 'note':
                self._read_note(entity)
            else:
                self.player.inventory.append(entity)
                self.entities.remove(entity)
                self.add_message(f"Подобрали: {entity.name}")
                self._refresh_player_weapon()

    def _try_interact(self):
        """Попытка взаимодействия с соседним объектом."""
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0), (0, 0)):
            x, y = self.player.x + dx, self.player.y + dy
            if not (0 <= y < len(self.current_map) and 0 <= x < len(self.current_map[0])):
                continue
            tile = self.current_map[y][x]

            if tile in TRANSITION_TILES:
                self._try_transition(x, y)
                return

            if tile in DOOR_TILES:
                self._try_open_door(x, y, tile)
                return

            entity = self._character_at(x, y)
            if entity:
                if entity.dialogue_id:
                    dialogue_id = self._dialogue_repeat_id(entity.dialogue_id)
                    if self.dialogue_engine.start_dialogue(
                        dialogue_id, flags=self.flags, san=self.player.san
                    ):
                        self.state = GameState.DIALOGUE
                        self.current_dialogue_speaker = entity.name
                        kind, text = self.dialogue_engine.present()
                        self._apply_dialogue_view(kind, text)
                        return
                    self.add_message(f"{entity.name} не желает разговаривать.")
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
        for flag in result.get('flags') or []:
            self.flags.add(flag)
        self._refresh_player_weapon()
        self._maybe_spawn_double()
        ending_id = result.get('ending_id')
        if ending_id:
            self._trigger_ending(ending_id)

    def _check_region(self, x: int, y: int):
        if not self.current_map_id:
            return
        region = self.db.get_region_at(self.current_map_id, x, y)
        if not region or region['id'] in self.visited_regions:
            return
        self.visited_regions.add(region['id'])
        text = region.get('first_visit_text')
        if text:
            self.add_message(text)
        glimpse = CLASS_GLIMPSES.get((getattr(self.player, 'id', ''), region['id']))
        if glimpse:
            self.add_message(glimpse)
        effect = region.get('sanity_effect') or 0
        if effect:
            self.player.change_san(effect)

    def _check_street_ending(self):
        if self.current_map_id != 'street_outside' or not self.player:
            return
        if self.player.x < 50:
            return
        can_flee = self.player.san >= 30 and can_pass_fog(self.flags)
        if can_flee:
            self._trigger_ending('flee')
        elif self.player.san < 30:
            self._trigger_ending('madness')
        elif 'fog_blocked' not in self.flags:
            self.flags.add('fog_blocked')
            if has_name(self.flags) and not has_debt(self.flags):
                self.add_message(
                    "Имя в вате есть. Долг ещё в коридоре. Туман не выпускает."
                )
            elif has_debt(self.flags) and not has_name(self.flags):
                whom = debt_face(self.flags)
                if whom:
                    self.add_message(
                        f"Вы должны {whom} — и безымянны. Туман не знает, кого выпускать."
                    )
                else:
                    self.add_message(
                        "Вы должны — и безымянны. Туман не знает, кого выпускать."
                    )
            else:
                self.add_message(
                    "Туман густой, как вата. Без имени и долга он не выпускает."
                )

    def _trigger_ending(self, ending_id: str):
        if self.state == GameState.ENDING:
            return
        self.ending_id = ending_id
        self.state = GameState.ENDING
        title, _body = ending_text(ending_id, getattr(self.player, 'id', ''))
        self.add_message(title)
        play_sound("end")

    def _present_testimony(self, name: str, content: str, first_hearing: bool = True):
        """Бумага в логе — показание, не добыча."""
        if first_hearing:
            self.add_message(f"Показание. {name}.")
            play_sound("paper")
        else:
            self.add_message("Это показание вы уже слышали.")
        if content:
            self.add_message(content)

    def _maybe_study_desk(self, x: int, y: int, tile: str) -> bool:
        """Пустой кабинет 2-го этажа отвечает бюро. Карту не двигаем."""
        if tile != 'O' or self.current_map_id != 'hospital_floor_2':
            return False
        if 'study_desk' in self.flags:
            return False
        region = self.db.get_region_at(self.current_map_id, x, y)
        if not region or region['id'] != 'f2_study':
            return False
        self.flags.add('study_desk')
        self.add_message(
            "Бюро. Под прессом черновик: «Пациент вспоминает. Нельзя.» "
            "Почерк тот же, что внизу, у микстуры."
        )
        extra = {
            'seeker': "Дата на полях — сегодняшняя. Имени нет.",
            'mystic': "Бумага ещё тёплая, будто только что отняли руку.",
            'rebel': "Можно скомкать. Вы не комкаете — пока.",
        }.get(getattr(self.player, 'id', ''))
        if getattr(self.player, 'id', '') == 'seeker':
            self.flags.add('seeker_trace')
        if extra:
            self.add_message(extra)
        return True

    def _read_note(self, note):
        """Прочитать записку как показание."""
        if self.quest_system:
            already = note.id in self.quest_system.found_notes
            if already:
                content = getattr(note, 'content', '') or getattr(note, 'description', '')
                if not content:
                    note_data = self.db.get_note(note.id)
                    content = (note_data or {}).get('content', '')
                self._present_testimony(note.name, content, first_hearing=False)
                if note in self.entities:
                    self.entities.remove(note)
                return
            content = self.quest_system.add_note(note.id)
            if not content:
                content = getattr(note, 'content', '') or getattr(note, 'description', '')
            self._present_testimony(note.name, content or "Чернила выцвели.")
            sanity_damage = getattr(note, 'sanity_damage', 0) or 0
            if sanity_damage != 0:
                self.player.change_san(sanity_damage)
                if sanity_damage < 0:
                    self.add_message("Строка держит дольше, чем взгляд.")
                else:
                    self.add_message("Строка отпускает — ненадолго.")
            postscript = NOTE_POSTSCRIPTS.get(getattr(self.player, 'id', ''))
            if postscript:
                self.add_message(postscript)
            if note.id == 'letter_1':
                self.flags.add('read_study_letter')
            if note in self.entities:
                self.entities.remove(note)
            self._maybe_spawn_double()
            self._check_quest_completion()
        else:
            self._present_testimony(note.name, getattr(note, 'content', '') or "")
            self.player.inventory.append(note)
            if note in self.entities:
                self.entities.remove(note)

    def _try_read(self):
        """Прочитать записку рядом или под ногами."""
        for dx, dy in ((0, 0), (0, -1), (0, 1), (-1, 0), (1, 0)):
            x, y = self.player.x + dx, self.player.y + dy
            for entity in self.entities:
                if getattr(entity, 'type', '') == 'note' and entity.x == x and entity.y == y:
                    self._read_note(entity)
                    return
        self.add_message("Рядом нет записок для чтения.")

    def _check_quest_completion(self):
        if not self.quest_system:
            return
        notified_ids = {q['id'] for q in self.notified_quests}
        for quest in self.quest_system.completed_quests:
            if quest['id'] not in notified_ids:
                self.add_message("Бумаги молчат. Дальше — только правда или капли.")
                self.notified_quests.append(quest)

    def _try_transition(self, x: int, y: int):
        """Попытка перехода на другую карту."""
        if not self.current_map_id:
            return
        tile = self.current_map[y][x]
        dx = abs(self.player.x - x)
        dy = abs(self.player.y - y)
        if dx > 1 or dy > 1:
            return

        if self.current_map_id == BRED_MAP_ID:
            ret = getattr(self, "bred_return", None)
            if ret:
                target_id, tx, ty = ret
                self.bred_return = None
                target_map = self.db.get_map_by_id(target_id)
                self.add_message("Коридор складывается обратно в план.")
                self._load_map(target_id)
                self.player.x, self.player.y = tx, ty
                self._compute_fov()
                if target_map:
                    self.add_message(f"Вы переходите на: {target_map['name']}")
                return

        connection = self.db.get_connection_for_tile(self.current_map_id, tile, x, y)
        if not connection:
            self.add_message("Проход никуда не ведёт.")
            return

        is_stairs = connection.get("connection_type") in ("stairs_up", "stairs_down")
        if (
            is_stairs
            and self.player
            and self.player.san <= BRED_SAN_THRESHOLD
            and "visited_bred" not in self.flags
            and self.current_map_id != BRED_MAP_ID
        ):
            self.flags.add("visited_bred")
            self.bred_return = (
                connection["target_map_id"],
                connection["target_x"],
                connection["target_y"],
            )
            self.add_message("Ступени длятся дольше, чем здание.")
            self._load_map(BRED_MAP_ID)
            if (
                y < len(self.current_map)
                and x < len(self.current_map[0])
                and self.current_map[y][x] in WALKABLE_TILES
            ):
                self.player.x, self.player.y = x, y
            else:
                self.player.x, self.player.y = 46, 15
            self._compute_fov()
            self.add_message("Это тот же коридор. И не тот.")
            return

        target_map = self.db.get_map_by_id(connection['target_map_id'])
        if not target_map:
            self.add_message(f"Карта '{connection['target_map_id']}' не найдена!")
            return

        self.add_message(f"Вы используете: {connection.get('description', 'переход')}")
        self._load_map(connection['target_map_id'])
        self.player.x = connection['target_x']
        self.player.y = connection['target_y']
        self._compute_fov()
        self.add_message(f"Вы переходите на: {target_map['name']}")

    def render(self):
        """Отрисовка кадра."""
        self.renderer.clear()

        if self.state == GameState.CLASS_SELECTION:
            self.renderer.draw_class_selection(
                self.available_classes,
                self.selected_class_index,
                has_save=has_save(),
            )
            self.renderer.present(self.context)
            return

        if self.current_map and self.fov_system and self.player:
            map_height = len(self.current_map)
            map_width = len(self.current_map[0]) if map_height else 0
            self._ensure_fov()
            self.renderer.set_camera_position(
                self.player.x, self.player.y, map_width, map_height
            )
            self.renderer.draw_map(self.current_map)
            self.renderer.draw_entities(self.entities)
            self.renderer.draw_player(self.player)

        if self.state not in (GameState.CLASS_SELECTION, GameState.ENDING, GameState.GAME_OVER):
            self.renderer.draw_legend()

        if self.player:
            self.renderer.draw_hud(self.player)
        self.renderer.draw_messages(self.messages)

        if self.quest_system:
            quest_desc = self.quest_system.get_active_quest_descriptions(self.flags)
            if quest_desc:
                self.renderer.draw_quests(quest_desc)

        if self.state == GameState.DIALOGUE:
            self.renderer.draw_dialogue(
                self.current_dialogue_text,
                self.current_dialogue_speaker,
                self.current_dialogue_choices,
            )

        if self.showing_help:
            self.renderer.draw_help()

        if self.is_inventory_open and self.player:
            self.renderer.draw_inventory(self.player, self.inventory_selected_index)

        if self.state == GameState.ENDING and self.ending_id:
            title, body = ending_text(
                self.ending_id, getattr(self.player, 'id', '')
            )
            self.renderer.draw_ending(title, body)
        elif self.state == GameState.GAME_OVER:
            for y in range(SCREEN_HEIGHT):
                for x in range(SCREEN_WIDTH):
                    self.renderer.console.bg[x, y] = libtcodpy.Color(10, 5, 5)
            self.renderer.console.print(
                SCREEN_WIDTH // 2 - 10, SCREEN_HEIGHT // 2,
                "КОНЕЦ. Тени победили.",
                fg=libtcodpy.Color(180, 50, 50)
            )

        self.renderer.present(self.context)
