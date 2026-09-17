"""Главный игровой движок."""
import random
import time
from typing import List, Optional, Tuple

import tcod
from tcod import libtcodpy

from engine.clinic_font import apply_sprite_mode
from engine.combat_system import perform_attack
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
    UNARMED_DAMAGE_DIE,
    SEARCHABLE_TILES,
    SHOULDER_DOOR,
    TILE_BUMP_MESSAGES,
    TRANSITION_TILES,
    WALKABLE_TILES,
)
from engine.db_loader import DBLoader
from engine.dialogue_engine import DialogueEngine
from engine.dialogue_keys import choice_index_from_key
from engine.entity_factory import Character, EntityFactory, Player
from engine.look_memory import parse_standing, remember
from engine.shop import (
    apply_buy,
    apply_sell,
    can_open_shop,
    kopeck_phrase,
    merchant_record,
    refuse_shop,
    sellable_items,
)
from engine.equipment import (
    EQUIP_SLOTS,
    SLOT_INDEX,
    first_item_for_slot,
    item_in_slot,
    slot_for_item,
    slot_name,
    worn_phrase,
)
from engine.fov_system import FOVSystem
from engine.quest_system import (
    NOTE_TRUTH,
    QuestSystem,
    can_pass_fog,
    debt_face,
    has_debt,
    has_name,
)
from engine.rpg_system import (
    SAN_EVENTS,
    SAN_SPEECH_FLAGS,
    is_canon_loot,
    san_loss_for,
    skill_phrase,
)
from engine.talent_system import (
    TALENT_GLIMPSES,
    has_hear_lamp,
    has_opening_crit,
    has_trace_glimpse,
    roll_verb,
    take_talent,
    visible_talents,
)
from engine.paintings import oil_id_for_item, oil_id_for_map
from engine.save_system import has_save, read_save, restore_map_states, write_save
from engine.renderer import Renderer
from engine.sanity_system import SanSystem
from engine.sound import play as play_sound
from engine import music as clinic_music
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
    ABILITY_MENU = 'ability_menu'
    DIALOGUE = 'dialogue'
    GAME_OVER = 'game_over'
    ENDING = 'ending'


class GameEngine:
    """Главный движок игры."""

    def __init__(self, context, tileset=None, view=None):
        self.context = context
        self.clinic_tileset = tileset
        self.view = view
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
        self.current_dialogue_portrait = ''
        self.current_dialogue_choices: List[str] = []
        self.current_check_banner = ''

        self.fov_system = None
        self.current_enemy = None
        self.battle_kind = ""
        self.party_ids: List[str] = []
        self.san_system = None
        self.quest_system = None
        self.notified_quests = []
        self.fired_triggers = set()
        self.flags = set()
        self.standing = {}
        self.visited_regions = set()
        self.visited_maps = set()
        self.ending_id = None
        self.bred_return = None
        self.bred_seed = 1

        self.showing_help = False
        self.is_inventory_open = False
        self.is_talents_open = False
        self.is_character_open = False
        self.is_shop_open = False
        self.inventory_selected_index = 0
        self.talent_selected_index = 0
        self.character_selected_index = 0
        self.shop_selected_index = 0
        self.shop_tab = "sell"
        self.shop_merchant_id = ""
        self.shop_merchant_name = ""
        self.oil_overlay = None
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
        """Тайлсет живёт на движке: у tcod.Context поля tileset нет."""
        return getattr(self, "clinic_tileset", None)

    def _apply_glyph_mode(self, sprites: bool) -> bool:
        tileset = self._clinic_tileset()
        if tileset is not None:
            apply_sprite_mode(tileset, sprites)
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
            if self.state in (
                GameState.CLASS_SELECTION,
                GameState.ENDING,
                GameState.GAME_OVER,
            ):
                clinic_music.stop()
            else:
                clinic_music.set_ducked(self._world_is_frozen())
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
        self.party_ids = [class_id]
        self.battle_kind = ""
        self.standing = {}
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

        self.oil_overlay = None
        self._load_map(starting_map['id'], spawn_player=True)

        for item_id in self.player.starting_item_ids:
            item = self.entity_factory.create_item(item_id)
            if item:
                self.player.inventory.append(item)
        self._equip_defaults()
        self._open_arrival(starting_map['id'])

        self.state = GameState.PLAYING
        self.add_message("Вы открыли глаза. Потолок холодный, как мокрый холст. Где вы? Впрочем, вы и сами не знаете, кто спрашивает.")
        self.add_message("Голова раскалывается. Имени нет. Нет — и стыдно, что нет.")

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
        clinic_music.stop()
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
        try:
            self.player.kopecks = max(0, int(pdata.get("kopecks") or 0))
        except (TypeError, ValueError):
            self.player.kopecks = 0
        self.player.inventory = []
        for item_id in pdata.get("inventory") or []:
            item = self.entity_factory.create_item(item_id)
            if item:
                self.player.inventory.append(item)
        self.player.talents = [
            talent_id
            for talent_id in pdata.get("talents") or []
            if isinstance(talent_id, str)
        ]
        equipped = pdata.get("equipped")
        if isinstance(equipped, dict):
            self.player.equipped = {
                str(slot): str(item_id)
                for slot, item_id in equipped.items()
                if slot and item_id
            }
        else:
            weapon = pdata.get("equipped_weapon_id")
            self.player.equipped_weapon_id = weapon if isinstance(weapon, str) else None
            self._wear_starting_robe()
        self._ensure_robe_in_pocket()
        self._refresh_player_weapon()

        self.flags = set(payload.get("flags") or [])
        self.flags.add(f'class_{self.player.id}')
        self.standing = parse_standing(payload.get("standing"))
        self.visited_regions = set(payload.get("visited_regions") or [])
        self.visited_maps = set(payload.get("visited_maps") or [])
        self.bred_seed = payload.get("bred_seed") or 1
        self.bred_return = payload.get("bred_return")
        self.notified_quests = list(payload.get("notified_quests") or [])
        self.fired_triggers = set(payload.get("fired_triggers") or [])
        self.ending_id = None
        self.current_enemy = None
        self.battle_kind = ""
        from engine.party import parse_party
        self.party_ids = parse_party(payload, payload.get("class_id") or "")
        self.showing_help = False
        self.is_inventory_open = False
        self.is_talents_open = False
        self.is_character_open = False
        self.is_shop_open = False
        self.oil_overlay = None
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
        self._snap_player_if_lost()
        self._compute_fov()

        self.san_system = SanSystem(self.player)
        self.quest_system = QuestSystem(self.db)
        self.quest_system.found_notes = list(payload.get("found_notes") or [])
        self.quest_system._check_quest_progress()
        self.state = GameState.PLAYING
        self.add_message("Вы снова открыли глаза. Потолок тот же. Тот же — и уже не тот.")
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
        lamps = {(item['x'], item['y']) for item in lights}

        def near_lamp(x: int, y: int, reach: int) -> bool:
            for lx, ly in lamps:
                if abs(lx - x) + abs(ly - y) <= reach:
                    return True
            return False

        for y, row in enumerate(self.current_map):
            for x, tile in enumerate(row):
                if tile in "BTOC" and not near_lamp(x, y, 2):
                    lights.append({
                        'x': x,
                        'y': y,
                        'type': 'ember',
                        'symbol': '',
                        'color': '',
                        'radius': 2,
                        'intensity': 0.38,
                        'flicker': True,
                    })
                elif tile == "." and (x * 13 + y * 29) % 14 == 0 and not near_lamp(x, y, 3):
                    lights.append({
                        'x': x,
                        'y': y,
                        'type': 'ember',
                        'symbol': '',
                        'color': '',
                        'radius': 1,
                        'intensity': 0.28,
                        'flicker': True,
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

    def _cell_walkable(self, x: int, y: int) -> bool:
        if not self.current_map:
            return False
        height = len(self.current_map)
        width = len(self.current_map[0]) if height else 0
        if not (0 <= y < height and 0 <= x < width):
            return False
        return self.current_map[y][x] in WALKABLE_TILES

    def _cell_free_to_stand(self, x: int, y: int) -> bool:
        if not self._cell_walkable(x, y):
            return False
        if self._character_at(x, y):
            return False
        return True

    def _snap_player_if_lost(self):
        if not self.player:
            return
        if self._cell_walkable(self.player.x, self.player.y):
            return
        self._place_player_on_start()

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
        clinic_music.set_for_map(map_id)
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
            if spawn_type != 'character':
                continue
            entity = self.entity_factory.create_character(spawn_id)
            if not entity:
                continue
            entity.x = x
            entity.y = y
            self.entities.append(entity)
            occupied.add((x, y))

    def _refresh_player_weapon(self):
        """Урон — с того, что в правой руке. Кулак, если рука пуста."""
        if not self.player:
            return
        equipped_id = self.player.equipped_weapon_id
        die = UNARMED_DAMAGE_DIE
        if equipped_id:
            held = next(
                (
                    item
                    for item in self.player.inventory
                    if getattr(item, "id", None) == equipped_id
                ),
                None,
            )
            if (
                held
                and getattr(held, "type", "") == "weapon"
                and getattr(held, "damage_die", "")
            ):
                die = held.damage_die
            else:
                self.player.equipped_weapon_id = None
        self.player.damage_die = die

    def _ensure_robe_in_pocket(self) -> None:
        if not self.player:
            return
        if any(getattr(item, "id", None) == "item_robe" for item in self.player.inventory):
            return
        robe = self.entity_factory.create_item("item_robe") if self.entity_factory else None
        if robe:
            self.player.inventory.append(robe)

    def _wear_starting_robe(self) -> None:
        if not self.player:
            return
        self._ensure_robe_in_pocket()
        if "body" in (self.player.equipped or {}):
            return
        body = first_item_for_slot(self.player, "body")
        if body:
            self.player.equipped["body"] = body.id

    def _equip_defaults(self):
        """Халат на тело, нож в правую руку, если ещё не надето."""
        self._wear_starting_robe()
        self._equip_first_weapon()

    def _equip_first_weapon(self):
        """Стартовый нож сразу в руке, не лежит мёртвым грузом."""
        if not self.player:
            return
        if getattr(self.player, "equipped_weapon_id", None):
            self._refresh_player_weapon()
            return
        for item in self.player.inventory:
            if getattr(item, "type", "") == "weapon" and getattr(item, "damage_die", ""):
                self.player.equipped_weapon_id = item.id
                break
        self._refresh_player_weapon()

    def _toggle_equip(self, item) -> None:
        slot = slot_for_item(item)
        if not slot:
            self.add_message(f"{item.name} не надевают.")
            return
        if not isinstance(self.player.equipped, dict):
            self.player.equipped = {}
        current = self.player.equipped.get(slot)
        if current == item.id:
            self.player.equipped.pop(slot, None)
            self._refresh_player_weapon()
            self.add_message(f"{item.name} — сняли.")
            return
        self.player.equipped[slot] = item.id
        self._refresh_player_weapon()
        where = worn_phrase(self.player, item.id) or slot_name(slot)
        self.add_message(f"{where}: {item.name}.")

    def _take_into_hand_if_empty(self, item) -> None:
        if slot_for_item(item) != "main_hand":
            return
        if getattr(self.player, "equipped_weapon_id", None):
            return
        if not getattr(item, "damage_die", ""):
            return
        self._toggle_equip(item)

    def _item_in_hand(self):
        return item_in_slot(self.player, "main_hand") if self.player else None

    def _use_character_slot(self) -> None:
        if not self.player:
            return
        index = min(max(0, self.character_selected_index), len(EQUIP_SLOTS) - 1)
        slot_id, _name = EQUIP_SLOTS[index]
        worn = item_in_slot(self.player, slot_id)
        if worn:
            self._toggle_equip(worn)
            return
        spare = first_item_for_slot(self.player, slot_id)
        if spare:
            self._toggle_equip(spare)
            return
        if slot_id == "main_hand":
            self.add_message("В руке кулак. Оружия в кармане нет.")
            return
        self.add_message(f"{slot_name(slot_id).capitalize()} пусто. Пока нечего надеть.")

    def _open_arrival(self, map_id: str) -> None:
        map_data = self.db.get_map(map_id) if self.db else None
        name = (map_data or {}).get("name") or map_id
        body = (map_data or {}).get("description") or ""
        self.oil_overlay = {
            "kind": "place",
            "oil_id": oil_id_for_map(map_id),
            "title": name,
            "body": body,
        }

    def _open_item_look(self, item) -> None:
        if not item:
            return
        self.oil_overlay = {
            "kind": "thing",
            "oil_id": oil_id_for_item(getattr(item, "id", "") or ""),
            "title": getattr(item, "name", "вещь") or "вещь",
            "body": getattr(item, "description", "") or "",
            "item_type": getattr(item, "type", "") or "",
        }

    def _handle_oil_input(self, event) -> bool:
        """Вид места или вещи. Карта ждёт."""
        if event.sym in (tcod.event.KeySym.Q,):
            self.oil_overlay = None
            return self.quit_and_save()
        dismiss = (
            tcod.event.KeySym.ESCAPE,
            tcod.event.KeySym.RETURN,
            tcod.event.KeySym.SPACE,
            tcod.event.KeySym.E,
        )
        if event.sym in dismiss or event.sym in MOVE_KEY_DIRS:
            self.oil_overlay = None
        return True

    def _raw_events(self):
        view = getattr(self, "view", None)
        if view is not None:
            return view.poll_events()
        return tcod.event.get()

    def _adapt_event(self, raw):
        if isinstance(raw, tcod.event.Quit):
            return "quit", raw
        if isinstance(raw, tcod.event.KeyDown):
            return "keydown", raw
        if isinstance(raw, tcod.event.KeyUp):
            return "keyup", raw
        kind = getattr(raw, "kind", "") or ""
        if kind in ("quit", "keydown", "keyup"):
            return kind, raw
        return "", raw

    def handle_events(self):
        """Обработка ввода. Не блокирует кадр."""
        for raw in self._raw_events():
            kind, event = self._adapt_event(raw)
            if kind == "quit":
                return self.quit_and_save()
            if kind == "keydown":
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
            elif kind == "keyup":
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
        if event.sym == tcod.event.KeySym.M:
            muted = clinic_music.toggle_mute()
            self.add_message("Музыка молчит." if muted else "Музыка снова в коридоре.")
            return True
        if self.state == GameState.CLASS_SELECTION:
            return self._handle_class_selection(event)
        if self.state == GameState.PLAYING:
            return self._handle_playing(event)
        if self.state == GameState.COMBAT:
            return self._handle_combat(event)
        if self.state == GameState.ABILITY_MENU:
            self.state = GameState.COMBAT
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
        if self.showing_help or self.is_inventory_open or self.is_talents_open:
            return True
        if self.is_character_open or self.is_shop_open:
            return True
        if self.oil_overlay:
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
        if self.oil_overlay:
            return self._handle_oil_input(event)
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

        if self.is_talents_open:
            return self._handle_talents_input(event)

        if self.is_character_open:
            return self._handle_character_input(event)

        if self.is_shop_open:
            return self._handle_shop_input(event)

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
        elif event.sym == tcod.event.KeySym.T:
            self.is_talents_open = True
            self.talent_selected_index = 0
        elif event.sym == tcod.event.KeySym.C:
            self.is_character_open = True
            self.character_selected_index = SLOT_INDEX["body"]
        elif event.sym == tcod.event.KeySym.B:
            self._try_open_shop()
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

    def _handle_talents_input(self, event) -> bool:
        """Тетрадь: ветки восьми глаголов. Не дерево MMORPG."""
        nodes = visible_talents(self.player)
        last = max(0, len(nodes) - 1)
        if event.sym in (tcod.event.KeySym.T, tcod.event.KeySym.ESCAPE):
            self.is_talents_open = False
            return True
        if not nodes:
            return True
        if event.sym in (tcod.event.KeySym.UP, tcod.event.KeySym.K):
            self.talent_selected_index = max(0, self.talent_selected_index - 1)
        elif event.sym in (tcod.event.KeySym.DOWN, tcod.event.KeySym.J):
            self.talent_selected_index = min(last, self.talent_selected_index + 1)
        elif event.sym in (tcod.event.KeySym.E, tcod.event.KeySym.RETURN):
            node = nodes[min(self.talent_selected_index, last)]
            ok, phrase = take_talent(self.player, node.id, self.flags)
            self.add_message(phrase)
            if ok:
                play_sound("paper")
        return True

    def _handle_character_input(self, event) -> bool:
        """Кукла слотов. Халат снимают, если есть во что переодеться."""
        last = max(0, len(EQUIP_SLOTS) - 1)
        if event.sym in (tcod.event.KeySym.C, tcod.event.KeySym.ESCAPE):
            self.is_character_open = False
            return True
        if event.sym in (tcod.event.KeySym.UP, tcod.event.KeySym.K):
            self.character_selected_index = max(0, self.character_selected_index - 1)
        elif event.sym in (tcod.event.KeySym.DOWN, tcod.event.KeySym.J):
            self.character_selected_index = min(last, self.character_selected_index + 1)
        elif event.sym in (tcod.event.KeySym.E, tcod.event.KeySym.RETURN):
            self._use_character_slot()
        return True

    def _adjacent_merchant(self):
        if not self.player:
            return None
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0), (0, 0)):
            entity = self._character_at(self.player.x + dx, self.player.y + dy)
            if entity and merchant_record(getattr(entity, "id", "") or ""):
                return entity
        return None

    def _close_modals(self):
        self.showing_help = False
        self.is_inventory_open = False
        self.is_talents_open = False
        self.is_character_open = False
        self.is_shop_open = False
        self.oil_overlay = None

    def _try_open_shop(self) -> bool:
        entity = self._adjacent_merchant()
        if not entity:
            self.add_message("Лавки рядом нет.")
            return False
        character_id = getattr(entity, "id", "") or ""
        if not can_open_shop(self.player, character_id):
            self.add_message(refuse_shop(self.player, character_id))
            return False
        self._close_modals()
        self.is_shop_open = True
        self.shop_tab = "sell"
        self.shop_selected_index = 0
        self.shop_merchant_id = character_id
        self.shop_merchant_name = getattr(entity, "name", None) or "Лавочник"
        return True

    def _shop_rows(self):
        if self.shop_tab == "buy":
            record = merchant_record(self.shop_merchant_id) or {}
            rows = []
            for item_id in record.get("sells") or ():
                item = (
                    self.entity_factory.create_item(item_id)
                    if self.entity_factory
                    else None
                )
                if item is not None:
                    rows.append(item)
            return rows
        return sellable_items(self.player)

    def _handle_shop_input(self, event) -> bool:
        rows = self._shop_rows()
        last = max(0, len(rows) - 1)
        if event.sym in (tcod.event.KeySym.B, tcod.event.KeySym.ESCAPE):
            self.is_shop_open = False
            return True
        if event.sym in (
            tcod.event.KeySym.TAB,
            tcod.event.KeySym.LEFT,
            tcod.event.KeySym.H,
            tcod.event.KeySym.RIGHT,
            tcod.event.KeySym.L,
        ):
            self.shop_tab = "buy" if self.shop_tab == "sell" else "sell"
            self.shop_selected_index = 0
            return True
        if not rows:
            return True
        if event.sym in (tcod.event.KeySym.UP, tcod.event.KeySym.K):
            self.shop_selected_index = max(0, self.shop_selected_index - 1)
        elif event.sym in (tcod.event.KeySym.DOWN, tcod.event.KeySym.J):
            self.shop_selected_index = min(last, self.shop_selected_index + 1)
        elif event.sym in (tcod.event.KeySym.E, tcod.event.KeySym.RETURN):
            self._shop_confirm()
        return True

    def _shop_confirm(self):
        rows = self._shop_rows()
        if not rows:
            self.add_message(
                "Нечего продать." if self.shop_tab == "sell" else "Пока нечего купить."
            )
            return
        index = min(max(0, self.shop_selected_index), len(rows) - 1)
        item_id = getattr(rows[index], "id", "") or ""
        if self.shop_tab == "sell":
            _ok, phrase = apply_sell(
                self.player, item_id, self.standing, self.shop_merchant_id
            )
        else:
            _ok, phrase = apply_buy(
                self.player,
                item_id,
                self.entity_factory,
                self.standing,
                self.shop_merchant_id,
            )
        self.add_message(phrase)
        self._refresh_player_weapon()
        rows = self._shop_rows()
        if rows:
            self.shop_selected_index = min(self.shop_selected_index, len(rows) - 1)
        else:
            self.shop_selected_index = 0

    def _use_selected_item(self):
        """Использовать выбранный предмет в инвентаре."""
        if self.inventory_selected_index >= len(self.player.inventory):
            return
        item = self.player.inventory[self.inventory_selected_index]
        self._use_item(item)
        if self.inventory_selected_index >= len(self.player.inventory):
            self.inventory_selected_index = max(0, len(self.player.inventory))

    def _use_item(self, item):
        """Использовать предмет с интеграцией системы рассудка."""
        effect = getattr(item, 'use_effect', '') or ''
        item_type = getattr(item, 'type', '')

        if effect == 'heal' or (item_type == 'consumable' and getattr(item, 'healing', 0)):
            healing = getattr(item, 'healing', 0)
            if healing > 0:
                old_hp = self.player.hp
                self.player.hp = min(self.player.max_hp, self.player.hp + healing)
                self.add_message(
                    f"Вы используете '{item.name}'. Восстановлено {self.player.hp - old_hp} плоти."
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
                if self.san_system:
                    events = self.san_system.gain_san(restore, source="item")
                    for evt in events:
                        self.add_message(evt)
                else:
                    old_san = self.player.san
                    self.player.san = min(self.player.max_san, self.player.san + restore)
                    self.add_message(
                        f"Вы используете '{item.name}'. Восстановлено {self.player.san - old_san} рассудка."
                    )
                self.player.inventory.remove(item)
            else:
                self.add_message("Предмет не оказывает эффекта.")
            return

        if effect == 'stabilize_sanity':
            # Предметы временной стабилизации рассудка
            bonus = getattr(item, 'sanity_effect', 5)
            duration = getattr(item, 'duration', 0)
            if self.san_system:
                self.san_system.apply_stabilization(bonus, duration)
                self.add_message(f"'{item.name}' стабилизирует рассудок (+{bonus}).")
                self.player.inventory.remove(item)
            else:
                old_san = self.player.san
                self.player.san = min(self.player.max_san, self.player.san + bonus)
                self.add_message(f"'{item.name}' восстанавливает {bonus} рассудка.")
                self.player.inventory.remove(item)
            return

        if effect == 'unlock_door' or item_type == 'key':
            self.add_message("Ключи используются автоматически при взаимодействии с дверью.")
            return

        if item_type in ("weapon", "clothing") or slot_for_item(item):
            self._toggle_equip(item)
            return

        if effect == 'temporary_buff':
            value = int(getattr(item, 'buff_value', 0) or 2)
            duration = int(getattr(item, 'duration', 0) or 1)
            self.player.add_effect('damage_buff', value=value, duration=duration)
            self.add_message(f"{item.name}: рука тяжелее на {duration} удар.")
            self.player.inventory.remove(item)
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
        from engine.battle_stage import pick_kind
        self.battle_kind = pick_kind(self.current_map_id or "")
        self.state = GameState.COMBAT
        self.add_message(f"Сцена: {entity.name}. Плоть {entity.hp} из {entity.max_hp}.")
        self.add_message("1 — удар · 2 — умение класса · 3 — бежать")
        if has_opening_crit(self.player):
            self.player.add_effect("next_crit", True, 1)

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
                self._maybe_spawn_double()
                return
            self.add_message(f"{entity.name} не враг.")
            return
        self.add_message("Рядом нет врагов.")

    def _handle_combat(self, event) -> bool:
        if self.current_enemy and not self.current_enemy.is_alive():
            self.add_message(f"{self.current_enemy.name} упал. Упал — и всё равно смотрит.")
            if self.current_enemy in self.entities:
                self.entities.remove(self.current_enemy)
            self.current_enemy = None
            self.state = GameState.PLAYING
            self.add_message("Тишина после удара. Она не добрее боя.")
            return True

        if not self.player.is_alive():
            self.state = GameState.GAME_OVER
            self.add_message("Вас одолели. Тени сомкнулись — кротко, как сиделки.")
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
            self._fight_flee()
            return True

        rank = self._fight_rank_from_event(event)
        if rank == 0:
            self._fight_strike()
            return True
        if rank == 1:
            self._fight_verb()
            return True
        if rank == 2:
            self._fight_flee()
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
            self.add_message("Вы в бою. 1 — удар, 2 — умение, 3 — бежать.")
        return True

    def _fight_rank_from_event(self, event) -> Optional[int]:
        """Ряд сцены: 1 удар, 2 умение, 3 бег. Пробел и C — те же ряды."""
        name = getattr(event.sym, "name", "") or ""
        idx = choice_index_from_key(name)
        if idx is not None and 0 <= idx <= 2:
            return idx
        if event.sym in (tcod.event.KeySym.SPACE, tcod.event.KeySym.RETURN):
            return 0
        if event.sym == tcod.event.KeySym.C:
            return 1
        return None

    def _fight_strike(self):
        if not self.current_enemy:
            return
        san_penalty = 0
        if self.san_system:
            san_penalty = self.san_system.get_combat_penalty()
        _hit, _damage, message = perform_attack(
            self.player, self.current_enemy, san_penalty=san_penalty
        )
        self.add_message(message)
        self.player.update_effects()
        if not self.current_enemy.is_alive():
            self._fight_victory()
            return
        self._enemy_riposte()

    def _fight_verb(self):
        """Классовое умение в кадре. Не меню способности."""
        if not self.player:
            return
        if not getattr(self.player, "class_ability", None):
            self.add_message("У этого класса нет умения.")
            return
        success, msg = self.player.use_class_ability(self.san_system)
        self.add_message(msg)
        if not success:
            return
        if self.current_enemy and self._is_hostile(self.current_enemy):
            self._enemy_riposte()
        if self.current_enemy and self.player.is_alive():
            self.state = GameState.COMBAT
        elif self.state != GameState.GAME_OVER:
            self.state = GameState.PLAYING

    def _fight_flee(self):
        chance = 0.5
        from engine.talent_system import flee_bonus

        chance = min(0.85, chance + flee_bonus(self.player))
        if random.random() < chance:
            self.add_message("Вы отступили. Стыдно. И живы.")
            self.current_enemy = None
            self.state = GameState.PLAYING
            return
        self.add_message("Не отпустили. Ноги предали раньше воли.")
        self._enemy_riposte()

    def _fight_victory(self):
        if self.current_enemy:
            self.add_message(f"{self.current_enemy.name} падает. Падает — и всё равно смотрит.")
            if self.current_enemy in self.entities:
                self.entities.remove(self.current_enemy)
        self.current_enemy = None
        self.state = GameState.PLAYING
        self.add_message("Тишина после удара. Она не добрее боя.")

    def _enemy_riposte(self):
        if not self.current_enemy or not self._is_hostile(self.current_enemy):
            return
        if not self.current_enemy.is_alive():
            self._fight_victory()
            return
        _eh, _ed, enemy_msg = perform_attack(self.current_enemy, self.player)
        self.add_message(enemy_msg)
        self.add_message(
            f"Враг HP: {self.current_enemy.hp}/{self.current_enemy.max_hp}"
        )
        san_hit = getattr(self.current_enemy, "sanity_damage", 0) or 0
        if san_hit:
            if self.san_system:
                for evt in self.san_system.lose_san(abs(san_hit), source="combat"):
                    self.add_message(evt)
            else:
                self.player.change_san(-abs(san_hit))
        if not self.player.is_alive():
            self.state = GameState.GAME_OVER
            self.add_message("Вы погибли...")

    def _handle_ability_menu(self, event) -> bool:
        """Обработка ввода в меню способностей."""
        # Навигация по списку способностей (пока только одна способность у класса)
        if event.sym in (tcod.event.KeySym.UP, tcod.event.KeySym.K):
            self.selected_ability_index = max(0, self.selected_ability_index - 1)
            return True
        if event.sym in (tcod.event.KeySym.DOWN, tcod.event.KeySym.J):
            # Пока только одна способность, но оставляем на будущее
            self.selected_ability_index = min(0, self.selected_ability_index + 1)
            return True
        
        # Выбор способности
        if event.sym in (tcod.event.KeySym.SPACE, tcod.event.KeySym.RETURN):
            if self.player:
                success, msg = self.player.use_class_ability(self.san_system)
                self.add_message(msg)
                if success:
                    if self.current_enemy and self._is_hostile(self.current_enemy):
                        _eh, _ed, enemy_msg = perform_attack(self.current_enemy, self.player)
                        self.add_message(enemy_msg)
                        self.add_message(
                            f"Враг HP: {self.current_enemy.hp}/{self.current_enemy.max_hp}"
                        )
                        san_hit = getattr(self.current_enemy, 'sanity_damage', 0) or 0
                        if san_hit:
                            if self.san_system:
                                events = self.san_system.lose_san(abs(san_hit), source="combat")
                                for evt in events:
                                    self.add_message(evt)
                            else:
                                self.player.change_san(-abs(san_hit))
                        if not self.player.is_alive():
                            self.state = GameState.GAME_OVER
                            self.add_message("Вы погибли...")
                            return True
                    if self.current_enemy and self.player.is_alive():
                        self.state = GameState.COMBAT
                    elif self.state != GameState.GAME_OVER:
                        self.state = GameState.PLAYING
            return True
        
        # Отмена
        if event.sym == tcod.event.KeySym.ESCAPE:
            self.state = GameState.COMBAT
            return True
        
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
            'dialogue_lukin_intro': ('spoke_lukin', 'dialogue_lukin_repeat'),
            'dialogue_praskovya_intro': ('spoke_praskovya', 'dialogue_praskovya_repeat'),
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
            self.current_dialogue_portrait = ''
            self.current_check_banner = ''
            return
        if kind == 'choices':
            self.current_dialogue_choices = self.dialogue_engine.get_choices()
            self.current_check_banner = self.dialogue_engine.get_check_banner()
            if self.dialogue_engine.current_dialogue:
                kept = self.dialogue_engine.current_dialogue.last_text
                if kept:
                    self.current_dialogue_text = kept
            return
        self.current_dialogue_choices = []
        self.current_dialogue_text = text or ''
        self.current_check_banner = self.dialogue_engine.get_check_banner()

    def _handle_dialogue(self, event) -> bool:
        name = getattr(event.sym, "name", "") or ""
        choice_index = choice_index_from_key(name)
        if (
            choice_index is not None
            and self.current_dialogue_choices
            and 0 <= choice_index < len(self.current_dialogue_choices)
        ):
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
            self.current_dialogue_portrait = ''
            self.current_check_banner = ''
            return True
        elif event.sym == tcod.event.KeySym.B:
            portrait = self.current_dialogue_portrait
            result = self.dialogue_engine.finish()
            self._apply_dialogue_result(result)
            if self.state != GameState.ENDING:
                self.state = GameState.PLAYING
            self.current_dialogue_text = ''
            self.current_dialogue_choices = []
            self.current_dialogue_portrait = ''
            self.current_check_banner = ''
            if merchant_record(portrait):
                self._try_open_shop()
            else:
                self.add_message("Лавки рядом нет.")
            return True
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
                if self._try_sneak_past(entity, dx, dy):
                    return
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
        self._after_step(new_x, new_y)

    def _try_sneak_past(self, entity, dx: int, dy: int) -> bool:
        """3d6 Красться мимо тени. Провал — бой как сейчас. Одержимого не обходим."""
        if getattr(entity, "id", "") != "shadow_enemy":
            return False
        check = roll_verb(self.player, "sneak")
        if not check.success:
            self.add_message(skill_phrase(check, "sneak"))
            return False
        beyond_x = entity.x + dx
        beyond_y = entity.y + dy
        if self._cell_free_to_stand(beyond_x, beyond_y):
            self.player.x = beyond_x
            self.player.y = beyond_y
            self._hold_bump_cell = None
            self.add_message(skill_phrase(check, "sneak"))
            self._after_step(beyond_x, beyond_y)
            return True
        self.add_message("Прошли у плеча. Дальше стена.")
        return True

    def _after_step(self, new_x: int, new_y: int):
        self._check_pickup()

        trigger_result = self.trigger_system.check_enter_trigger(
            new_x, new_y, self.player, self.current_map_id, self.fired_triggers
        )
        self.fired_triggers.update(trigger_result.fired_ids)
        for msg in trigger_result.messages:
            self.add_message(msg)
        if (
            "trigger_whisper" in trigger_result.fired_ids
        ):
            self._hear_lamp_whisper()
        self._apply_trigger_spawns(trigger_result, new_x, new_y)
        self._check_region(new_x, new_y)
        self._maybe_spawn_double()
        self._check_street_ending()
        self._compute_fov()

    def _hear_lamp_whisper(self):
        """3d6 Слышать у лампы. Не новый этаж. Правды тумана не ставит."""
        if not self.player:
            return
        if getattr(self.player, "id", "") != "mystic" and not has_hear_lamp(self.player):
            return
        if "mystic_trace" in self.flags:
            return
        check = roll_verb(self.player, "hear")
        if check.success:
            self.flags.add("mystic_trace")
            self.add_message(skill_phrase(check, "hear"))
            return
        self.add_message(skill_phrase(check, "hear"))

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
                "Рядом стоит человек в таком же халате. Лица не разобрать. "
                "Не разобрать — или не хотите."
            )
            self._apply_san_event("double")

    def _try_open_door(self, x: int, y: int, tile: str):
        """Открыть дверь. Запертая требует свой ключ."""
        if tile == 'D':
            self.current_map[y][x] = "'"
            self.add_message("Вы открыли дверь. Скрипнул стыд, не петля.")
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
            elif self._try_shoulder_door(x, y):
                return
            elif required:
                hint = LOCKED_DOOR_HINTS.get(getattr(self.player, 'id', ''))
                if hint:
                    self.add_message(hint)
                needed = self.entity_factory.create_item(required)
                name = needed.name if needed else "особый ключ"
                self.add_message(f"Дверь заперта. Нужен {name}.")
            else:
                self.add_message("Дверь заперта. Нужен ключ.")

    def _try_shoulder_door(self, x: int, y: int) -> bool:
        """Бунтарь: одна дверь плечом. 3d6 Ломать. Стены .txt не рушим."""
        if getattr(self.player, "id", "") != "rebel":
            return False
        if (self.current_map_id, x, y) != SHOULDER_DOOR:
            return False
        if self.current_map[y][x] not in LOCKED_DOOR_TILES:
            return False
        check = roll_verb(self.player, "break")
        if not check.success:
            self.add_message(skill_phrase(check, "break"))
            return True
        self.current_map[y][x] = "'"
        self.player.change_san(-8)
        self.player.take_damage(1)
        self.flags.add("broke_door")
        self.add_message(skill_phrase(check, "break"))
        play_sound("door")
        self._mark_fov_dirty()
        self._maybe_spawn_double()
        return True

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
                self._take_into_hand_if_empty(entity)
                self._refresh_player_weapon()
                self._open_item_look(entity)

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
                        dialogue_id,
                        flags=self.flags,
                        san=self.player.san,
                        player=self.player,
                        standing=getattr(self, "standing", None),
                    ):
                        self.state = GameState.DIALOGUE
                        self.current_dialogue_speaker = entity.name
                        self.current_dialogue_portrait = getattr(entity, "id", "") or ""
                        kind, text = self.dialogue_engine.present()
                        self._apply_dialogue_view(kind, text)
                        return
                    self.add_message(f"{entity.name} не желает разговаривать.")
                else:
                    self.add_message(f"{entity.name} не желает разговаривать.")
                return

        if self._try_search():
            return

        self.add_message("Рядом никого нет.")

    def _apply_dialogue_result(self, result: Optional[dict]):
        if not result:
            return
        held = set(self.flags)
        new_flags = list(result.get('flags') or [])
        speech = [
            SAN_SPEECH_FLAGS[flag]
            for flag in new_flags
            if flag in SAN_SPEECH_FLAGS and flag not in held
        ]
        san_delta = result.get('sanity_change', 0) or 0
        if speech:
            for event_id in speech:
                self._apply_san_event(event_id)
        elif san_delta:
            self.player.change_san(san_delta)
        for item_id in result.get('items_given', []):
            item = self.entity_factory.create_item(item_id)
            if item:
                self.player.inventory.append(item)
                self.add_message(f"Получено: {item.name}")
        paid = int(result.get("kopecks_delta") or 0)
        if paid:
            self.add_message(f"В кармане {kopeck_phrase(paid)}.")
        for flag in new_flags:
            self.flags.add(flag)
        if not isinstance(getattr(self, "standing", None), dict):
            self.standing = {}
        remember(
            self.standing,
            result.get("character_id") or "",
            int(result.get("standing_delta") or 0),
        )
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
        if has_trace_glimpse(self.player):
            extra = TALENT_GLIMPSES.get(region['id'])
            seen = f"talent_trace:{region['id']}"
            if extra and seen not in self.flags:
                self.flags.add(seen)
                self.add_message(extra)
        effect = region.get('sanity_effect') or 0
        if effect:
            self.player.change_san(effect)

    def _fog_blocks_house(self):
        """Имя или долг порознь — вата, не крыльцо."""
        if has_name(self.flags) and not has_debt(self.flags):
            self.add_message(
                "Имя в вате есть. Долг ещё в коридоре. Туман не выпускает. Не выпускает — и прав."
            )
        elif has_debt(self.flags) and not has_name(self.flags):
            whom = debt_face(self.flags)
            if whom:
                self.add_message(
                    f"Вы должны {whom} — и безымянны. Туман не знает, кого выпускать. Не знает — и не врёт."
                )
            else:
                self.add_message(
                    "Вы должны — и безымянны. Туман не знает, кого выпускать."
                )
        else:
            self.add_message(
                "Туман густой, как вата. Без имени и долга он не выпускает. Вата сытая. Вы — нет."
            )

    def _check_street_ending(self):
        if self.current_map_id != 'street_outside' or not self.player:
            return
        if self.player.x < 50:
            return
        if self.player.san < 30:
            self._trigger_ending('madness')
            return
        if can_pass_fog(self.flags):
            if 'fog_house' not in self.flags:
                self.flags.add('fog_house')
                self.add_message(
                    "Туман редеет у камня. Канал дальше на восток — не титры."
                )
            return
        if 'fog_blocked' not in self.flags:
            self.flags.add('fog_blocked')
            self._fog_blocks_house()

    def _trigger_ending(self, ending_id: str):
        if self.state == GameState.ENDING:
            return
        self.ending_id = ending_id
        self.state = GameState.ENDING
        title, _body = ending_text(ending_id, getattr(self.player, 'id', ''))
        self.add_message(title)
        clinic_music.stop()
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

    def _try_search(self) -> bool:
        """Обыск стола, шкафа, бюро, картины. e, не шаг."""
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0), (0, 0)):
            x, y = self.player.x + dx, self.player.y + dy
            if not (0 <= y < len(self.current_map) and 0 <= x < len(self.current_map[0])):
                continue
            if self.current_map[y][x] in SEARCHABLE_TILES:
                self._search_container(x, y)
                return True
        return False

    def _apply_san_event(self, event_id: str):
        """Таблица CoC. Воля 3d6. Один раз на событие. Не инверсия клавиш."""
        if not self.player or event_id not in SAN_EVENTS:
            return
        seen = f"san_checked:{event_id}"
        if seen in self.flags:
            return
        self.flags.add(seen)
        amount, phrase = san_loss_for(event_id, self.player)
        if amount > 0:
            if self.san_system:
                for evt in self.san_system.lose_san(amount, source=event_id):
                    self.add_message(evt)
            else:
                self.player.change_san(-amount)
        if phrase:
            self.add_message(phrase)

    def _search_container(self, x: int, y: int):
        tile = self.current_map[y][x]
        flag = f"searched:{self.current_map_id}:{x}:{y}"
        if flag in self.flags:
            self.add_message("Уже смотрели. Пыль легла обратно.")
            return
        loot = self.db.get_container_loot(self.current_map_id, x, y)
        names = {
            "T": "Стол",
            "H": "Шкаф",
            "O": "Бюро",
            '"': "Рама",
        }
        label = names.get(tile, "Мебель")
        if not loot:
            self.flags.add(flag)
            self.add_message(f"{label}. Ничего, кроме пыли.")
            return
        item = self.entity_factory.create_item(loot["item_id"])
        if not item:
            self.flags.add(flag)
            self.add_message(f"{label}. Пусто.")
            return
        check = roll_verb(self.player, "search")
        if not check.success and not is_canon_loot(item):
            self.flags.add(flag)
            self.add_message(f"{label}. {skill_phrase(check, 'search')}")
            return
        self.flags.add(flag)
        if check.success:
            self.add_message(f"{label}. {skill_phrase(check, 'search')}")
        else:
            self.add_message(f"{label}. Нащупали вслепую.")
        if getattr(item, "type", "") == "note":
            self._read_note(item)
        else:
            self.player.inventory.append(item)
            self.add_message(f"Взяли: {item.name}")
            self._take_into_hand_if_empty(item)
            self._refresh_player_weapon()
            self._open_item_look(item)
        if (
            self.current_map_id == "hospital_floor_2"
            and (x, y) == (34, 5)
            and getattr(self.player, "id", "") == "seeker"
        ):
            self.flags.add("seeker_trace")

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
            self._open_item_look(note)
            for truth in NOTE_TRUTH.get(note.id, ()):
                if truth not in self.flags:
                    self.flags.add(truth)
                    if truth == "guilt_admitted":
                        self.add_message("Вы вспомнили, кому должны.")
                    elif truth == "knows_lizaveta":
                        self.add_message("Имя на полях — не ваше. Его ещё можно сказать вслух.")
            if note.id in SAN_EVENTS:
                self._apply_san_event(note.id)
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
            self._open_item_look(note)
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
                self._snap_player_if_lost()
                self._compute_fov()
                if target_map:
                    self.add_message(f"Вы переходите на: {target_map['name']}")
                self._open_arrival(target_id)
                return

        connection = self.db.get_connection_for_tile(self.current_map_id, tile, x, y)
        if not connection:
            self.add_message("Проход никуда не ведёт.")
            return

        if (
            connection.get("target_map_id") == "street_canal_east"
            and self.current_map_id == "street_outside"
        ):
            if not self.player:
                return
            if self.player.san < 30:
                self._trigger_ending("madness")
                return
            if not can_pass_fog(self.flags):
                self._fog_blocks_house()
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
            if self._cell_walkable(x, y):
                self.player.x, self.player.y = x, y
            else:
                self.player.x, self.player.y = 53, 6
            self._snap_player_if_lost()
            self._compute_fov()
            self.add_message("Это тот же коридор. И не тот.")
            self._open_arrival(BRED_MAP_ID)
            return

        target_map = self.db.get_map_by_id(connection['target_map_id'])
        if not target_map:
            self.add_message(f"Карта '{connection['target_map_id']}' не найдена!")
            return

        self.add_message(f"Вы используете: {connection.get('description', 'переход')}")
        self._load_map(connection['target_map_id'])
        self.player.x = connection['target_x']
        self.player.y = connection['target_y']
        self._snap_player_if_lost()
        self._compute_fov()
        self.add_message(f"Вы переходите на: {target_map['name']}")
        self._open_arrival(connection['target_map_id'])

    def render(self):
        """Отрисовка кадра."""
        view = getattr(self, "view", None)
        if view is not None:
            view.draw(self)
            return
        self.renderer.clear()

        if self.state == GameState.CLASS_SELECTION:
            self.renderer.draw_class_selection(
                self.available_classes,
                self.selected_class_index,
                has_save=has_save(),
            )
            self.renderer.present(self.context)
            return

        in_fight = self.state in (GameState.COMBAT, GameState.ABILITY_MENU)
        if in_fight and self.player:
            self.renderer.draw_fight_scene(
                self.player, self.current_enemy, self.messages
            )
        elif self.current_map and self.fov_system and self.player:
            map_height = len(self.current_map)
            map_width = len(self.current_map[0]) if map_height else 0
            self._ensure_fov()
            self.renderer.set_camera_position(
                self.player.x, self.player.y, map_width, map_height
            )
            self.renderer.draw_map(self.current_map)
            self.renderer.draw_entities(self.entities)
            self.renderer.draw_player(self.player)

        if self.state not in (
            GameState.CLASS_SELECTION,
            GameState.ENDING,
            GameState.GAME_OVER,
            GameState.COMBAT,
            GameState.ABILITY_MENU,
        ):
            self.renderer.draw_legend()

        if self.player:
            self.renderer.draw_hud(self.player)
        if self.state not in (GameState.COMBAT, GameState.ABILITY_MENU):
            self.renderer.draw_messages(self.messages)

        if self.quest_system and self.state not in (
            GameState.COMBAT, GameState.ABILITY_MENU,
        ):
            quest_desc = self.quest_system.get_active_quest_descriptions(self.flags)
            if quest_desc:
                self.renderer.draw_quests(quest_desc)

        if self.state == GameState.DIALOGUE:
            self.renderer.draw_dialogue(
                self.current_dialogue_text,
                self.current_dialogue_speaker,
                self.current_dialogue_choices,
                self.current_dialogue_portrait,
                self.current_check_banner,
            )

        if self.showing_help:
            self.renderer.draw_help()

        if self.is_inventory_open and self.player:
            self.renderer.draw_inventory(self.player, self.inventory_selected_index)

        if self.is_talents_open and self.player:
            self.renderer.draw_talents(
                self.player, self.talent_selected_index, self.flags
            )

        if self.is_character_open and self.player:
            self.renderer.draw_character(
                self.player, self.character_selected_index
            )

        if self.is_shop_open and self.player:
            from engine.look_memory import standing_of

            self.renderer.draw_shop(
                self.player,
                merchant_name=self.shop_merchant_name,
                tab=self.shop_tab,
                rows=self._shop_rows(),
                selected_index=self.shop_selected_index,
                standing=standing_of(self.standing, self.shop_merchant_id),
            )

        if self.oil_overlay:
            self.renderer.draw_oil_overlay(self.oil_overlay)

        if self.state == GameState.ENDING and self.ending_id:
            title, body = ending_text(
                self.ending_id, getattr(self.player, 'id', '')
            )
            self.renderer.draw_ending(title, body)
        elif self.state == GameState.GAME_OVER:
            from engine.renderer import COLOR_SANITY as _SAN, COLOR_VOID_BG as _VOID
            for y in range(SCREEN_HEIGHT):
                for x in range(SCREEN_WIDTH):
                    self.renderer.console.bg[x, y] = _VOID
            self.renderer.console.print(
                SCREEN_WIDTH // 2 - 10, SCREEN_HEIGHT // 2,
                "КОНЕЦ. Тени победили.",
                fg=_SAN,
            )

        self.renderer.present(self.context)
