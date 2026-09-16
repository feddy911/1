"""Проверка фазы 0 без окна tcod."""
import ast
from collections import deque
from pathlib import Path

from engine.constants import WALKABLE_TILES
from engine.db_loader import DBLoader
from engine.entity_factory import Player
from engine.game_engine import GameEngine

ROOT = Path(__file__).resolve().parents[1]
APPROACHABLE = WALKABLE_TILES | {"@", "D"}


def load_map(path: Path):
    raw = path.read_text(encoding="utf-8").splitlines()
    width = max(len(r) for r in raw)
    return [list(r.ljust(width)) for r in raw]


def _flood(grid, start):
    height, width = len(grid), len(grid[0])
    sx, sy = start
    seen = {(sx, sy)}
    queue = deque([(sx, sy)])
    while queue:
        x, y = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if (nx, ny) in seen:
                continue
            if grid[ny][nx] not in APPROACHABLE:
                continue
            seen.add((nx, ny))
            queue.append((nx, ny))
    return seen


def _door_has_two_sides(grid, x, y):
    height, width = len(grid), len(grid[0])

    def cell(cx, cy):
        if 0 <= cx < width and 0 <= cy < height:
            return grid[cy][cx]
        return "#"

    north, south = cell(x, y - 1), cell(x, y + 1)
    west, east = cell(x - 1, y), cell(x + 1, y)
    ns = north in WALKABLE_TILES and south in WALKABLE_TILES
    ew = west in WALKABLE_TILES and east in WALKABLE_TILES
    return ns or ew


def assert_map_walkable(errors, name, grid, start, expect_width):
    widths = {len(row) for row in grid}
    if widths != {expect_width}:
        errors.append(f"{name}: ширина {widths}, ждали {expect_width}")
        return
    if not (0 <= start[1] < len(grid) and 0 <= start[0] < expect_width):
        errors.append(f"{name}: старт {start} вне карты")
        return
    if grid[start[1]][start[0]] not in APPROACHABLE:
        errors.append(
            f"{name}: старт {start} на '{grid[start[1]][start[0]]}'"
        )
        return
    reachable = _flood(grid, start)
    for y, row in enumerate(grid):
        for x, tile in enumerate(row):
            if tile in {"D", "d"}:
                if not _door_has_two_sides(grid, x, y):
                    errors.append(
                        f"{name}: дверь ({x},{y}) не стоит в стене с проходом с двух сторон"
                    )
                neighbors = (
                    (x + 1, y),
                    (x - 1, y),
                    (x, y + 1),
                    (x, y - 1),
                )
                if not any(pos in reachable for pos in neighbors):
                    errors.append(f"{name}: дверь ({x},{y}) недостижима")
            if tile in {"S", "s", "E"}:
                if (x, y) not in reachable:
                    errors.append(f"{name}: переход '{tile}' ({x},{y}) недостижим")



def main():
    errors = []
    from engine.sound import set_enabled as _mute_sound
    from engine.music import set_enabled as _mute_music

    _mute_sound(False)
    _mute_music(False)
    src = (ROOT / "engine" / "game_engine.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    methods = {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "GameEngine"
        for node in node.body
        if isinstance(node, ast.FunctionDef)
    }
    for name in (
        "_try_attack",
        "_try_read",
        "_try_interact",
        "_maybe_spawn_double",
        "save_game",
        "load_game",
        "quit_and_save",
        "_present_testimony",
        "_try_search",
        "_apply_san_event",
        "_handle_combat",
        "_fight_strike",
        "_fight_verb",
        "_fight_flee",
        "_handle_talents_input",
        "_handle_oil_input",
        "_open_arrival",
        "_toggle_equip",
    ):
        if name not in methods:
            errors.append(f"нет метода {name}")
    from engine import game_engine as ge_mod
    if not hasattr(ge_mod, "perform_attack"):
        errors.append("бой: perform_attack не импортирован")
    if "draw_legend" not in (
        node.name
        for node in ast.parse((ROOT / "engine" / "renderer.py").read_text(encoding="utf-8")).body
        if isinstance(node, ast.ClassDef) and node.name == "Renderer"
        for node in node.body
        if isinstance(node, ast.FunctionDef)
    ):
        errors.append("нет легенды символов на экране")
    from engine.constants import TILE_LEGEND
    symbols = {row[0] for row in TILE_LEGEND}
    for needed in ("@", "d", "S", "B", "W"):
        if needed not in symbols:
            errors.append(f"в легенде нет символа {needed}")

    db = DBLoader(str(ROOT / "data" / "petersburg.db"))
    classes = {c["id"]: db.get_player_class(c["id"]) for c in db.get_all_player_classes()}
    players = {cid: Player(data) for cid, data in classes.items()}
    strs = {cid: p.stats["STR"] for cid, p in players.items()}
    if len(set(strs.values())) < 2:
        errors.append(f"классы с одинаковой STR: {strs}")
    if not players["rebel"].starting_item_ids:
        errors.append("у бунтаря пустой стартовый инвентарь")
    if players["rebel"].attack_bonus <= players["mystic"].attack_bonus:
        errors.append("бунтарь должен бить сильнее мистика")
    skill_n = db.conn.execute("SELECT COUNT(*) AS n FROM class_skills").fetchone()["n"]
    if skill_n != 24:
        errors.append(f"навыков не 24: {skill_n}")
    if players["seeker"].skills.get("search") != 12:
        errors.append("искатель ищет не на 12")
    if players["rebel"].skills.get("break") != 12:
        errors.append("бунтарь ломает не на 12")
    if players["mystic"].skills.get("hear") != 12:
        errors.append("мистик слышит не на 12")
    from engine.rpg_system import SKILL_IDS, SKILL_PHRASES, RollResult, skill_phrase

    if len(SKILL_IDS) != 8:
        errors.append(f"навыков не 8: {SKILL_IDS}")
    if "talk" in SKILL_PHRASES:
        errors.append("говорить звучит второй строкой лога")
    for sid in ("search", "sneak", "hear", "break"):
        pack = SKILL_PHRASES.get(sid)
        if not pack or len(pack) != 4:
            errors.append(f"нет четырёх фраз для {sid}")
    hear_18 = RollResult(total=18, target=12, success=False, crit=False, fumble=True)
    if "сбился" not in skill_phrase(hear_18, "hear").lower():
        errors.append("фумбл слуха без «сбился»")
    sneak_3 = RollResult(total=3, target=10, success=True, crit=True, fumble=False)
    if "мимо" not in skill_phrase(sneak_3, "sneak").lower():
        errors.append("крит красться без «мимо»")
    if skill_phrase(sneak_3, "talk"):
        errors.append("говорить имеет фразу таблицы")
    from engine.talent_system import (
        TALENTS,
        has_hear_lamp,
        has_note_hold,
        has_opening_crit,
        has_trace_glimpse,
        take_talent,
        visible_talents,
    )
    from engine.rpg_system import skill_modifier

    combat_n = sum(1 for node in TALENTS if node.branch == "combat")
    world_n = sum(1 for node in TALENTS if node.branch == "world")
    if combat_n < 4 or world_n < 4:
        errors.append(f"дерево без боя и мира: бой {combat_n} мир {world_n}")
    if not any(node.parent_id for node in TALENTS):
        errors.append("дерево без ветвления")
    if any(node.verb == "see_trace" and node.effects.get("reroll") for node in TALENTS):
        errors.append("след снова бросает кость")
    for node in TALENTS:
        text = (node.description or "").lower()
        if not any(
            token in text
            for token in (
                "3d6",
                "d20",
                "+1",
                "+2",
                "75%",
                "без броска",
                "повторяется",
            )
        ):
            errors.append(f"умение без правила: {node.id}")
        if len(node.description or "") < 40:
            errors.append(f"умение слишком короткое: {node.id}")
    rebel = players["rebel"]
    rebel.san = 80
    rebel.talents = []
    ok, _msg = take_talent(rebel, "fight_2", set())
    if ok:
        errors.append("вторая ветка боя без корня")
    ok, _msg = take_talent(rebel, "fight_1", set())
    if not ok:
        errors.append("бунтарь не берёт корень боя")
    if rebel.san >= 80:
        errors.append("талант не берёт волю")
    after = skill_modifier(rebel, "break")
    take_talent(rebel, "break_1", set())
    if skill_modifier(rebel, "break") <= after:
        errors.append("ветка ломать не меняет бросок")
    seeker = players["seeker"]
    seeker.san = 80
    seeker.talents = []
    base_search = skill_modifier(seeker, "search")
    take_talent(seeker, "search_1", set())
    if skill_modifier(seeker, "search") <= base_search:
        errors.append("ветка обыска не меняет бросок")
    if len(visible_talents(seeker)) <= 1:
        errors.append("после корня не открываются ветки")
    if "see_trace" in SKILL_PHRASES:
        errors.append("след получил фразы броска")
    rebel.talents = ["fight_1", "fight_2", "fight_3"]
    if not has_opening_crit(rebel):
        errors.append("талант «Насквозь» не готовит удар")
    seeker.talents = ["hear_1", "hear_2"]
    if not has_hear_lamp(seeker):
        errors.append("талант слуха у лампы не ставится")
    seeker.talents = ["search_1", "trace_1"]
    if not has_trace_glimpse(seeker):
        errors.append("талант следа не ставится")
    mystic = players["mystic"]
    mystic.talents = ["hear_1", "read_1", "read_2"]
    if not has_note_hold(mystic):
        errors.append("талант чужого почерка не ставится")
    import engine.rpg_system as rpg_hold

    class _WillFail:
        success = False
        total = 18
        target = 10
        crit = False
        fumble = True

    old_will = rpg_hold.roll_will
    rpg_hold.roll_will = lambda player: _WillFail()
    amount, phrase = rpg_hold.san_loss_for("note_canal", mystic)
    rpg_hold.roll_will = old_will
    if amount != 1 or "почерк" not in (phrase or "").lower():
        errors.append(f"чужой почерк не держит бумагу: {amount} {phrase}")
    rebel.talents = []
    seeker.talents = []
    mystic.talents = []
    rebel.san = rebel.max_san
    seeker.san = seeker.max_san
    mystic.san = mystic.max_san
    from engine.constants import UNARMED_DAMAGE_DIE
    from engine.entity_factory import EntityFactory
    from engine.paintings import LOCATION_FILES, oil_id_for_item, oil_id_for_map, painting_path

    knife = EntityFactory(db).create_item("item_knife")
    if not knife or knife.type != "weapon" or knife.damage_die != "1d6":
        errors.append("ржавый нож без кости")
    host = GameEngine.__new__(GameEngine)
    host.player = players["seeker"]
    host.messages = []
    host.add_message = lambda text: host.messages.append(text)
    host.player.inventory = []
    host.player.equipped_weapon_id = None
    host._refresh_player_weapon()
    if host.player.damage_die != UNARMED_DAMAGE_DIE:
        errors.append("кулак не 1d3")
    host.player.inventory = [knife]
    host.player.equipped = {}
    host._toggle_equip(knife)
    if host.player.equipped_weapon_id != "item_knife" or host.player.damage_die != "1d6":
        errors.append("нож нельзя взять в руку")
    host._toggle_equip(knife)
    if host.player.equipped_weapon_id or host.player.damage_die != UNARMED_DAMAGE_DIE:
        errors.append("нож не уходит в карман")
    from engine.equipment import EQUIP_SLOTS, SLOT_INDEX

    slot_ids = [slot_id for slot_id, _name in EQUIP_SLOTS]
    for needed in ("head", "body", "main_hand", "off_hand", "legs", "feet"):
        if needed not in slot_ids:
            errors.append(f"нет слота {needed}")
    robe = EntityFactory(db).create_item("item_robe")
    coat = EntityFactory(db).create_item("item_coat")
    if not robe or robe.type != "clothing" or (robe.equip_slot or "") != "body":
        errors.append("халат не одежда на тело")
    if not coat or coat.type != "clothing" or (coat.equip_slot or "") != "body":
        errors.append("сюртук не одежда на тело")
    host.character_selected_index = SLOT_INDEX["main_hand"]
    host.player.inventory = [knife]
    host.player.equipped = {}
    host._refresh_player_weapon()
    host._use_character_slot()
    if host.player.equipped_weapon_id != "item_knife":
        errors.append("слот руки не берёт нож")
    host._use_character_slot()
    if host.player.equipped_weapon_id:
        errors.append("слот руки не кладёт нож в карман")
    host.character_selected_index = SLOT_INDEX["head"]
    host.messages = []
    host._use_character_slot()
    if not any("пусто" in (msg or "").lower() for msg in host.messages):
        errors.append(f"пустой слот без отказа: {host.messages}")
    host.player.inventory = [robe, coat]
    host.player.equipped = {}
    host.character_selected_index = SLOT_INDEX["body"]
    host._use_character_slot()
    if (host.player.equipped or {}).get("body") != "item_robe":
        errors.append("халат не надевается")
    host._use_character_slot()
    if (host.player.equipped or {}).get("body"):
        errors.append("халат не снимается")
    host._toggle_equip(coat)
    if (host.player.equipped or {}).get("body") != "item_coat":
        errors.append("сюртук не надевается")
    host._toggle_equip(robe)
    if (host.player.equipped or {}).get("body") != "item_robe":
        errors.append("халат не сменяет сюртук")
    loot_coat = db.conn.execute(
        "SELECT item_id FROM container_loot WHERE map_id = ? AND x = ? AND y = ?",
        ("street_tenement", 44, 3),
    ).fetchone()
    if not loot_coat or loot_coat["item_id"] != "item_coat":
        errors.append("сюртук не в шкафу квартиры")
    for cid, pdata in classes.items():
        if "item_robe" not in (pdata.get("starting_items") or []):
            errors.append(f"{cid} без халата")
    engine_src = (ROOT / "engine" / "game_engine.py").read_text(encoding="utf-8")
    renderer_src = (ROOT / "engine" / "renderer.py").read_text(encoding="utf-8")
    if "Халат не снимают" in engine_src or "Халат не снимают" in renderer_src:
        errors.append("халат всё ещё нельзя снять")
    host.player.inventory = []
    host.player.equipped_weapon_id = None
    host._refresh_player_weapon()
    for map_id in LOCATION_FILES:
        if painting_path(oil_id_for_map(map_id)) is None:
            errors.append(f"нет масла места {map_id}")
    if painting_path(oil_id_for_item("item_knife")) is None:
        errors.append("нет масла ножа")
    if players["seeker"].stats.get("WILL") != 13:
        errors.append("воля искателя не из SAN занятия")
    shadow = EntityFactory(db).create_character("shadow_enemy")
    if not shadow:
        errors.append("нет тени для боя")
    else:
        hit, dmg, msg = ge_mod.perform_attack(players["seeker"], shadow)
        if not isinstance(msg, str) or not msg:
            errors.append(f"удар без сообщения: {hit} {dmg} {msg}")
    from engine.renderer import Renderer
    from engine.constants import SCREEN_HEIGHT, SCREEN_WIDTH

    fight = Renderer(SCREEN_WIDTH, SCREEN_HEIGHT)

    class _FightHost:
        use_sprites = False
        san_system = None
        state = "combat"
        messages = []
        flags = set()
        quest_system = None

    fight.game_engine = _FightHost()
    fight.draw_fight_scene(players["seeker"], shadow, ["КРИТИЧЕСКИЙ УДАР"])
    fight.draw_hud(players["seeker"])
    engine_src = (ROOT / "engine" / "game_engine.py").read_text(encoding="utf-8")
    renderer_src = (ROOT / "engine" / "renderer.py").read_text(encoding="utf-8")
    if "плоть" not in renderer_src or "воля" not in renderer_src:
        errors.append("HUD не карта больного")
    if "КАРМАН ХАЛАТА" not in renderer_src:
        errors.append("карман всё ещё инвентарь")
    if "на полях" not in renderer_src:
        errors.append("нет полей легенды")
    if "пробел — удар" in renderer_src or "C — способность" in renderer_src:
        errors.append("кадр помнит старый бой")
    if "ИНВЕНТАРЬ" in renderer_src:
        errors.append("карман подписан как инвентарь")
    if "Color(200, 180, 100)" in renderer_src:
        errors.append("долг на карте золотом не из чернил")
    if (ROOT / "engine" / "inventory.py").exists():
        errors.append("мёртвый InventoryManager всё ещё в репо")
    if "InventoryManager" in engine_src or "class InventoryManager" in renderer_src:
        errors.append("InventoryManager ещё импортируют")
    if "chart_marks" not in renderer_src:
        errors.append("баффы не в карте больного")
    if "draw_oil_overlay" not in renderer_src:
        errors.append("нет вида места")
    if "в руке" not in renderer_src:
        errors.append("HUD не показывает руку")
    if "def draw_character" not in renderer_src or "НА СЕБЕ" not in renderer_src:
        errors.append("нет окна персонажа со слотами")
    if "EQUIP_SLOTS" not in engine_src or "is_character_open" not in engine_src:
        errors.append("слоты экипировки не открываются")
    if "KeySym.C" not in engine_src:
        errors.append("нет клавиши окна персонажа")
    if "temporary_buff" not in engine_src:
        errors.append("бафф предмета не идёт в эффекты")
    rebel = players["rebel"]
    saved_fx, saved_san = list(rebel.active_effects), rebel.san
    rage_ok, _rage_msg = rebel.use_class_ability()
    if not rage_ok or "рука тяжелее" not in rebel.chart_marks():
        errors.append(f"ярость не помечает дело: {rebel.chart_marks()}")
    fight.draw_hud(rebel)
    rebel.active_effects = saved_fx
    rebel.san = saved_san
    if "draw_fight_scene" not in engine_src:
        errors.append("бой всё ещё рисует коридор")
    if "def draw_fight_scene" not in renderer_src:
        errors.append("нет сцены боя")
    if "1  Удар · d20" not in renderer_src or "3  Бежать" not in renderer_src:
        errors.append("нет рядов сцены")
    if "self.state = GameState.ABILITY_MENU" in engine_src:
        errors.append("C всё ещё открывает меню способности")
    if "draw_ability_menu" in engine_src:
        errors.append("бой всё ещё рисует меню способности")

    from types import SimpleNamespace
    from tcod import event as tcod_event
    from engine.game_engine import GameState

    if shadow:
        foe = EntityFactory(db).create_character("shadow_enemy")
        dummy = GameEngine.__new__(GameEngine)
        dummy.player = players["seeker"]
        dummy.current_enemy = foe
        dummy.entities = [foe]
        dummy.messages = []
        dummy.state = GameState.COMBAT
        dummy.san_system = None
        dummy.player.x, dummy.player.y = 5, 5
        foe.x, foe.y = 6, 5
        dummy._handle_combat(SimpleNamespace(sym=tcod_event.KeySym.C))
        if dummy.state == GameState.ABILITY_MENU:
            errors.append("C открывает меню способности")
        if dummy.state not in (
            GameState.COMBAT,
            GameState.PLAYING,
            GameState.GAME_OVER,
        ):
            errors.append(f"после глагола состояние {dummy.state}")

    window = db.get_light_source("window")
    if not window or window["symbol"] != "W" or float(window["radius"]) < 1:
        errors.append(f"окно-свет сломано: {window}")

    pante = db.get_dialogue("dialogue_panteleimon_intro")
    if not pante or not pante.get("lines"):
        errors.append("нет диалога Пантелеймона")

    doctor = db.get_character("doctor_shpilkin")
    if doctor and doctor["symbol"] == "D":
        errors.append("символ доктора всё ещё D, конфликт с дверью")

    floor = load_map(ROOT / "data" / "maps" / "floor_1.txt")
    for row in floor:
        if len(row) != len(floor[0]):
            errors.append("неровная ширина floor_1")
            break
    if floor[2][12] != "d":
        errors.append("запертая дверь кабинета не на месте")
    if floor[3][52] != "D":
        errors.append("дверь к лестнице должна быть открываемой")
    if floor[1][18] != "*" or floor[1][42] != "*":
        errors.append("лампы в коридоре не на месте")
    if floor[4][16] != "@":
        errors.append("игрок съехал со старта")
    if floor[1][0] != "#" or floor[3][12] != "#":
        errors.append("сломан каркас кабинета на 1 этаже")

    assert_map_walkable(errors, "floor_1", floor, (16, 4), 57)

    for map_id, grid in (
        ("hospital_floor_1", floor),
        ("hospital_floor_2", load_map(ROOT / "data" / "maps" / "floor_2.txt")),
        ("hospital_basement", load_map(ROOT / "data" / "maps" / "basement.txt")),
        ("street_outside", load_map(ROOT / "data" / "maps" / "street.txt")),
        ("street_traktir", load_map(ROOT / "data" / "maps" / "traktir.txt")),
        ("street_tenement", load_map(ROOT / "data" / "maps" / "tenement.txt")),
    ):
        for p in db.get_map_placements(map_id):
            x, y = p["x"], p["y"]
            if y >= len(grid) or x >= len(grid[0]):
                errors.append(f"спавн {p['spawn_id']} вне карты {map_id} ({x},{y})")
                continue
            tile = grid[y][x]
            if tile not in WALKABLE_TILES and tile != "@":
                errors.append(
                    f"спавн {p['spawn_id']} на непроходимом '{tile}' {map_id} ({x},{y})"
                )

    # Состояние карт: два визита не должны переспавнивать
    class DummyContext:
        pass

    engine = GameEngine.__new__(GameEngine)
    engine.db = db
    from engine.entity_factory import EntityFactory
    from engine.dialogue_engine import DialogueEngine
    from engine.trigger_system import TriggerSystem
    from engine.renderer import Renderer
    from engine.constants import SCREEN_WIDTH, SCREEN_HEIGHT

    engine.entity_factory = EntityFactory(db)
    engine.trigger_system = TriggerSystem(db)
    engine.dialogue_engine = DialogueEngine(db)
    engine.renderer = Renderer(SCREEN_WIDTH, SCREEN_HEIGHT)
    engine.renderer.game_engine = engine
    engine.renderer.load_tile_colors_from_db(db)
    engine.player = players["seeker"]
    engine.current_map = []
    engine.current_map_id = None
    engine.entities = []
    engine.light_sources = []
    engine.map_states = {}
    engine.messages = []
    engine.fov_system = None
    engine.quest_system = None
    engine.san_system = None
    engine.notified_quests = []
    engine.fired_triggers = set()
    engine.flags = set()
    engine.visited_regions = set()
    engine.visited_maps = set()
    engine.ending_id = None
    engine.bred_return = None
    engine.bred_seed = 1
    engine.current_dialogue_choices = []
    engine.current_dialogue_text = ""
    engine.current_dialogue_speaker = ""
    engine.current_dialogue_portrait = ""
    engine.showing_help = False
    engine.is_inventory_open = False
    engine.is_talents_open = False
    engine.is_character_open = False
    engine.oil_overlay = None
    engine.inventory_selected_index = 0
    engine.current_enemy = None
    engine.state = "playing"
    engine._reset_realtime()

    engine._load_map("hospital_floor_1", spawn_player=True)
    first_count = len(engine.entities)
    names = sorted(
        getattr(e, "id", "") for e in engine.entities if hasattr(e, "id")
    )
    if "doctor_shpilkin" not in names:
        errors.append("доктор не заспавнился на 1 этаже")
    if names.count("doctor_shpilkin") != 1:
        errors.append(f"доктор заспавнился {names.count('doctor_shpilkin')} раз")

    engine._load_map("hospital_basement")
    engine._load_map("hospital_floor_1")
    if len(engine.entities) != first_count:
        errors.append(
            f"после возврата сущностей {len(engine.entities)}, было {first_count}"
        )

    # Фаза 1: диалоги, ключи, карты
    dlg = db.get_dialogue("dialogue_shpilkin_intro")
    groups = {line.get("choice_group") for line in dlg["lines"] if line.get("choice_group")}
    if not groups:
        errors.append("у Шпилькина нет веток выбора")
    if db.get_door_lock("hospital_floor_1", 12, 2) != "key_warden":
        errors.append("кабинет должен открываться ключом смотрителя")
    if db.get_door_lock("street_tenement", 27, 2) != "key_tenement":
        errors.append("нет замка квартиры при лавке")
    if db.get_door_lock("hospital_basement", 40, 3) != "key_basement":
        errors.append("лаборатория должна открываться ключом от подвала")
    if not db.get_region_at("street_outside", 8, 10):
        errors.append("у улицы нет описания крыльца")
    floor2 = load_map(ROOT / "data" / "maps" / "floor_2.txt")
    if floor2[4][51] != "s":
        errors.append("лестница 2 этажа съехала")
    if floor2[3][37] != "d":
        errors.append("дверь кабинета главврача съехала")
    if db.get_door_lock("hospital_floor_2", 37, 3) != "key_doctor":
        errors.append("кабинет 2 этажа должен открываться ключом врача")
    assert_map_walkable(errors, "floor_2", floor2, (53, 6), 57)
    basement = load_map(ROOT / "data" / "maps" / "basement.txt")
    if basement[3][40] != "d":
        errors.append("дверь лаборатории съехала")
    if basement[6][43] not in WALKABLE_TILES:
        errors.append("документ в лаборатории на стене")
    if basement[7][3] not in WALKABLE_TILES:
        errors.append("дверь камеры в подвале снова упирается в стену")
    if basement[1][25] != "#" or basement[1][36] != "#":
        errors.append("в подвале нет столбов")
    assert_map_walkable(errors, "basement", basement, (53, 6), 57)
    street = load_map(ROOT / "data" / "maps" / "street.txt")
    if street[9][0] != "E" or street[16][10] != "=":
        errors.append("улица: нет выхода или канала")
    if street[6][32] != "E" or street[6][33] != "E":
        errors.append("вход в трактир съехал")
    if street[7][32] not in WALKABLE_TILES:
        errors.append("дверь трактира не открывается с улицы")
    if street[6][12] not in WALKABLE_TILES or street[5][12] not in WALKABLE_TILES:
        errors.append("нет проёма во двор")
    if street[3][11] != "D":
        errors.append("нет двери из двора в службу")
    assert_map_walkable(errors, "street", street, (1, 9), 60)
    traktir = load_map(ROOT / "data" / "maps" / "traktir.txt")
    if traktir[7][0] != "E" or traktir[7][1] not in WALKABLE_TILES:
        errors.append("трактир: нет выхода на улицу")
    if traktir[7][35] != "E" or traktir[7][34] not in WALKABLE_TILES:
        errors.append("трактир: нет чёрного хода")
    if traktir[3][7] != "T":
        errors.append("нет стойки к улице")
    if traktir[7][26] != "D":
        errors.append("нет двери в кухню")
    if street[3][26] != "E":
        errors.append("чёрный ход не выходит во двор")
    assert_map_walkable(errors, "traktir", traktir, (1, 7), 36)
    tenement = load_map(ROOT / "data" / "maps" / "tenement.txt")
    if tenement[6][0] != "E" or tenement[7][0] != "E":
        errors.append("доходный дом: нет входа с тумана")
    if tenement[2][27] != "d":
        errors.append("доходный дом: нет запертой квартиры")
    if tenement[3][24] != "H" or tenement[2][44] != "O":
        errors.append("доходный дом: ключ или книга не в мебели")
    if any(cell in {"S", "s"} for row in tenement for cell in row):
        errors.append("доходный дом: лестница стала переходом")
    if street[9][58] != "E" or street[10][58] != "E":
        errors.append("туман не ведёт в дом")
    if street[9][57] not in WALKABLE_TILES:
        errors.append("из дома некуда выйти в туман")
    assert_map_walkable(errors, "tenement", tenement, (1, 6), 48)
    from engine.constants import SEARCHABLE_TILES
    from engine.db_migrate import CONTAINER_LOOT

    floor_items = list(
        db.conn.execute(
            "SELECT map_id, x, y, spawn_id FROM map_placements WHERE spawn_type = 'item'"
        )
    )
    if floor_items:
        errors.append(f"предметы снова на полу: {floor_items}")
    loot_grids = {
        "hospital_floor_1": floor,
        "hospital_floor_2": floor2,
        "hospital_basement": basement,
        "street_outside": street,
        "street_traktir": traktir,
        "street_tenement": tenement,
    }
    for map_id, x, y, item_id in CONTAINER_LOOT:
        grid = loot_grids.get(map_id)
        if grid is None:
            errors.append(f"лут {item_id} на неизвестной карте {map_id}")
            continue
        if y >= len(grid) or x >= len(grid[y]) or grid[y][x] not in SEARCHABLE_TILES:
            cell = grid[y][x] if grid and y < len(grid) and x < len(grid[y]) else "?"
            errors.append(f"лут {item_id} не в мебели ({map_id} {x},{y}) {cell!r}")
    if floor[1][12] != '"':
        errors.append("нет картины в кабинете 1 этажа")
    if street[15][18] != "T":
        errors.append("нет скамьи у канала")
    if db.get_connection_at_position("street_outside", 32, 6) is None:
        errors.append("нет связи улица → трактир")
    link_grids = {
        "hospital_floor_1": floor,
        "hospital_floor_2": floor2,
        "hospital_basement": basement,
        "street_outside": street,
        "street_traktir": traktir,
        "street_tenement": tenement,
    }
    for map_id, expect_w, expect_h in (
        ("hospital_floor_1", 57, 12),
        ("hospital_floor_2", 57, 12),
        ("hospital_basement", 57, 12),
        ("street_outside", 60, 20),
        ("street_traktir", 36, 14),
        ("hospital_bred", 57, 12),
        ("street_tenement", 48, 14),
    ):
        meta = db.get_map(map_id)
        if not meta or meta["width"] != expect_w or meta["height"] != expect_h:
            errors.append(
                f"карта {map_id}: размер БД {None if not meta else (meta['width'], meta['height'])}, "
                f"ждали {expect_w}×{expect_h}"
            )
    for map_id, grid in link_grids.items():
        for y, row in enumerate(grid):
            for x, tile in enumerate(row):
                if tile not in {"S", "s", "E"}:
                    continue
                conn_row = db.get_connection_for_tile(map_id, tile, x, y)
                if not conn_row:
                    errors.append(f"нет связи {map_id} '{tile}' ({x},{y})")
                    continue
                tid = conn_row["target_map_id"]
                tx, ty = conn_row["target_x"], conn_row["target_y"]
                target = link_grids.get(tid)
                if target is None:
                    errors.append(f"связь {map_id} ({x},{y}) ведёт на неизвестную {tid}")
                    continue
                if not (0 <= ty < len(target) and 0 <= tx < len(target[0])):
                    errors.append(
                        f"связь {map_id} ({x},{y}) → {tid} ({tx},{ty}) вне карты"
                    )
                    continue
                if target[ty][tx] not in WALKABLE_TILES:
                    errors.append(
                        f"связь {map_id} ({x},{y}) → {tid} ({tx},{ty}) "
                        f"на '{target[ty][tx]}'"
                    )
    old_states = engine.map_states
    engine.map_states = {}
    engine.visited_maps = set()
    engine.flags.add("visited_bred")
    hops = (
        ("hospital_floor_1", 51, 4, "hospital_floor_2"),
        ("hospital_floor_2", 51, 4, "hospital_floor_1"),
        ("hospital_floor_1", 53, 4, "hospital_basement"),
        ("hospital_basement", 51, 4, "hospital_floor_1"),
        ("hospital_floor_1", 56, 1, "street_outside"),
        ("street_outside", 0, 9, "hospital_floor_1"),
    )
    for src, sx, sy, dest in hops:
        engine._load_map(src)
        engine.player.x, engine.player.y = sx, sy
        engine._try_transition(sx, sy)
        if engine.current_map_id != dest:
            errors.append(
                f"лестница {src} ({sx},{sy}) привела на {engine.current_map_id}, ждали {dest}"
            )
            break
        if not (
            0 <= engine.player.y < len(engine.current_map)
            and 0 <= engine.player.x < len(engine.current_map[0])
            and engine.current_map[engine.player.y][engine.player.x] in WALKABLE_TILES
        ):
            errors.append(
                f"лестница {src} → {dest} высадила в ({engine.player.x},{engine.player.y})"
            )
            break
    engine.map_states = old_states
    engine.visited_maps = set()
    engine.flags.discard("visited_bred")
    engine._load_map("hospital_floor_1", spawn_player=True)
    if not db.get_character("innkeeper_semyon"):
        errors.append("нет трактирщика")
    if not db.get_character("shopkeeper_lukin") or not db.get_character(
        "landlady_praskovya"
    ):
        errors.append("нет жильцов доходного дома")

    from engine.dialogue_engine import DialogueEngine
    de = DialogueEngine(db)
    if not de.start_dialogue("dialogue_nastasya_intro", flags=set(), san=80):
        errors.append("не стартует диалог Настасьи")
    de.present()
    de.advance()
    kind, _text = de.advance()
    if kind != "choices" or len(de.get_choices()) != 3:
        errors.append(f"выбор Настасьи: {kind} / {de.get_choices()}")
    nas_opts = de.get_choices()
    exit_c = next((c for c in nas_opts if "выйти" in c.lower()), "")
    seen_c = next((c for c in nas_opts if "видел" in c.lower()), "")
    if "(долг" not in exit_c.lower() or "настась" not in exit_c.lower():
        errors.append(f"выход Настасье без скобок долга: {exit_c}")
    if "воля" not in seen_c.lower() or "-6" not in seen_c:
        errors.append(f"признание теней без воли в скобках: {seen_c}")
    de_seek = DialogueEngine(db)
    if de_seek.start_dialogue("dialogue_nastasya_intro", flags={"class_seeker"}, san=80):
        de_seek.present()
        de_seek.advance()
        kind_s, _t = de_seek.advance()
        n_seek = len(de_seek.get_choices())
        if kind_s != "choices" or n_seek != 4:
            errors.append(f"искатель должен слышать 4-й ответ Настасьи: {n_seek}")
        elif not any("стёрт" in c for c in de_seek.get_choices()):
            errors.append(f"нет классовой реплики искателя: {de_seek.get_choices()}")
    else:
        errors.append("не стартует диалог Настасьи для искателя")
    de.choose(2)
    fin = de.finish()
    if "nastasya_escape" not in (fin.get("flags") or []):
        errors.append(f"флаг побега не ставится: {fin}")

    shadow = db.get_character("shadow_enemy")
    if not shadow or shadow.get("symbol") != "&":
        errors.append(f"тень без ASCII-символа: {shadow}")

    double = db.get_character("player_double")
    if not double or double.get("symbol") != "&":
        errors.append(f"двойник не как живой NPC: {double}")
    de2 = DialogueEngine(db)
    if not de2.start_dialogue("dialogue_double_intro", flags=set(), san=40):
        errors.append("не стартует диалог двойника")
    else:
        de2.present()
        de2.advance()
        kind, _text = de2.advance()
        if kind != "choices" or len(de2.get_choices()) != 3:
            errors.append(f"выбор двойника: {kind} / {de2.get_choices()}")
        else:
            de2.choose(2)
            fin2 = de2.finish()
            if "guilt_admitted" not in (fin2.get("flags") or []):
                errors.append(f"признание двойнику не ставит вину: {fin2}")

    engine.player.san = 30
    engine._maybe_spawn_double()
    doubles = [
        e for e in engine.entities if getattr(e, "id", "") == "player_double"
    ]
    if len(doubles) != 1:
        errors.append(f"двойник должен появиться один раз, есть {len(doubles)}")
    engine._maybe_spawn_double()
    doubles = [
        e for e in engine.entities if getattr(e, "id", "") == "player_double"
    ]
    if len(doubles) != 1:
        errors.append("двойник заспавнился повторно")

    from engine.bred_floor import generate_bred_floor
    from engine.constants import BRED_MAP_ID, BRED_SAN_THRESHOLD

    bred = generate_bred_floor(ROOT / "data" / "maps" / "floor_1.txt", 7)
    assert_map_walkable(errors, "bred", bred, (53, 6), 57)
    engine.player.san = BRED_SAN_THRESHOLD
    engine.flags.discard("visited_bred")
    engine.bred_return = None
    engine._load_map(BRED_MAP_ID)
    if engine.current_map_id != BRED_MAP_ID or not engine.current_map:
        errors.append("этаж бреда не загружается")
    de3 = DialogueEngine(db)
    if de3.start_dialogue("dialogue_beggar_intro", flags=set(), san=50):
        de3.present()
        de3.advance()
        kind, _text = de3.advance()
        if kind == "choices":
            de3.choose(2)
            fin3 = de3.finish()
            if "sennaya_name" in (fin3.get("flags") or []) or "archive_name" in (
                fin3.get("flags") or []
            ):
                errors.append(f"нищий сам выдал имя: {fin3}")
        else:
            errors.append("у нищего нет выбора")
    else:
        errors.append("не стартует диалог нищего")

    for repeat_id in (
        "dialogue_shpilkin_repeat",
        "dialogue_nastasya_repeat",
        "dialogue_panteleimon_repeat",
        "dialogue_double_repeat",
        "dialogue_innkeeper_repeat",
        "dialogue_watchman_repeat",
        "dialogue_beggar_repeat",
        "dialogue_archivist_repeat",
        "dialogue_possessed_repeat",
    ):
        de_r = DialogueEngine(db)
        if not de_r.start_dialogue(repeat_id, flags=set(), san=70):
            errors.append(f"не стартует повтор {repeat_id}")
            continue
        de_r.present()
        kind, _text = de_r.advance()
        n_repeat = len(de_r.get_choices())
        want = 4 if repeat_id == "dialogue_nastasya_repeat" else 3
        if kind != "choices" or n_repeat != want:
            errors.append(f"повтор без выбора: {repeat_id} {kind} / {de_r.get_choices()}")

    stay_repeat = DialogueEngine(db)
    if stay_repeat.start_dialogue("dialogue_shpilkin_repeat", flags=set(), san=70):
        stay_repeat.present()
        stay_repeat.advance()
        mix = next((c for c in stay_repeat.get_choices() if "микстур" in c.lower()), "")
        if "воля" not in mix.lower() or "остаться" not in mix.lower():
            errors.append(f"микстура без ставки в скобках: {mix}")
        stay_repeat.choose(1)
        fin_stay = stay_repeat.finish()
        if fin_stay.get("ending_id") != "stay":
            errors.append(f"повтор Шпилькина не даёт остаться: {fin_stay}")
    else:
        errors.append("повтор Шпилькина не стартует для концовки")

    possessed = db.get_character("possessed_patient")
    if not possessed or possessed.get("dialogue_id") != "dialogue_possessed_intro":
        errors.append(f"одержимый без речи: {possessed}")
    de_p = DialogueEngine(db)
    if not de_p.start_dialogue("dialogue_possessed_intro", flags=set(), san=50):
        errors.append("не стартует диалог одержимого")
    else:
        de_p.present()
        kind, _text = de_p.advance()
        if kind != "choices" or len(de_p.get_choices()) != 3:
            errors.append(f"одержимый без выбора: {kind} / {de_p.get_choices()}")
        de_pr = DialogueEngine(db)
        if de_pr.start_dialogue(
            "dialogue_possessed_intro", flags={"class_rebel"}, san=50
        ):
            de_pr.present()
            de_pr.advance()
            if len(de_pr.get_choices()) != 4:
                errors.append(
                    f"бунтарь должен слышать 4-й ответ одержимого: {de_pr.get_choices()}"
                )

    if not db.get_character("archivist_klara"):
        errors.append("нет архивариуса")
    engine._load_map("hospital_floor_2")
    floor2_ids = [getattr(e, "id", "") for e in engine.entities]
    if "archivist_klara" not in floor2_ids:
        errors.append("архивариус не стоит на 2 этаже")
    if not db.get_container_loot("hospital_floor_2", 1, 1):
        errors.append("в архиве нет дела в шкафу")
    de4 = DialogueEngine(db)
    if de4.start_dialogue("dialogue_archivist_intro", flags=set(), san=50):
        de4.present()
        de4.advance()
        kind, _text = de4.advance()
        if kind == "choices":
            de4.choose(2)
            fin4 = de4.finish()
            if "archive_name" not in (fin4.get("flags") or []):
                errors.append(f"архив не даёт имя: {fin4}")
        else:
            errors.append("у архивариуса нет выбора")
    else:
        errors.append("не стартует диалог архивариуса")

    import tempfile
    from engine.save_system import read_save
    from engine.sanity_system import SanSystem
    from engine.quest_system import QuestSystem

    class _SanPlayer:
        def __init__(self):
            self.san = 100

    san_p = _SanPlayer()
    san_sys = SanSystem(san_p)
    if san_sys.update():
        errors.append("SAN без изменения не должен писать в лог")
    san_p.san = 70
    first_san = san_sys.update()
    if len(first_san) != 1:
        errors.append(f"порог SAN должен дать одну фразу, дал {first_san}")
    if san_sys.update():
        errors.append("повторный кадр без смены SAN снова пишет в лог")
    san_p.san = 65
    if san_sys.update():
        errors.append("SAN внутри того же порога не должен писать снова")
    san_p.san = 45
    next_san = san_sys.update()
    if len(next_san) != 1:
        errors.append(f"следующий порог SAN: {next_san}")

    full = SanSystem(_SanPlayer())
    if full.get_sanity_effects().get("visual"):
        errors.append("полный рассудок уже искажает экран")
    low = _SanPlayer()
    low.san = 50
    low_fx = SanSystem(low).get_sanity_effects()
    if low_fx.get("visual") != "periphery":
        errors.append(f"низкий SAN visual={low_fx.get('visual')}")
    if low_fx.get("control") is not None:
        errors.append("SAN не должен инвертировать клавиши")
    if low_fx.get("hallucinations"):
        errors.append("галлюцинации размазаны по карте")
    renderer_src = (ROOT / "engine" / "renderer.py").read_text(encoding="utf-8")
    if "distortion_level" in renderer_src:
        errors.append("карта всё ещё скремблируется при низком SAN")
    if "_draw_sanity_periphery" not in renderer_src:
        errors.append("нет периферии SAN")

    qs = QuestSystem(db)
    hud0 = " ".join(qs.get_active_quest_descriptions(set()))
    if "записок найдено" in hud0 or "записок" in hud0:
        errors.append(f"HUD квеста считает записки: {hud0}")
    if "имя" not in hud0.lower() and "долг" not in hud0.lower():
        errors.append(f"HUD квеста без имени/долга: {hud0}")
    hud1 = " ".join(qs.get_active_quest_descriptions({"archive_name"}))
    if "записок" in hud1:
        errors.append(f"HUD после имени всё ещё про записки: {hud1}")
    if "туман" not in hud1.lower():
        errors.append(f"HUD после имени без тумана: {hud1}")
    if "долг" not in hud1.lower():
        errors.append(f"HUD после имени не просит долг: {hud1}")
    if "уже слышал" in hud1:
        errors.append(f"одно имя уже закрывает HUD: {hud1}")
    hud_debt = " ".join(qs.get_active_quest_descriptions({"guilt_admitted"}))
    if "имен" not in hud_debt.lower():
        errors.append(f"HUD после долга без имени: {hud_debt}")
    if "лизавет" not in hud_debt.lower():
        errors.append(f"HUD долга без лица Лизаветы: {hud_debt}")
    hud_nas = " ".join(qs.get_active_quest_descriptions({"nastasya_escape"}))
    if "настась" not in hud_nas.lower():
        errors.append(f"HUD долга без лица Настасьи: {hud_nas}")
    hud_ok = " ".join(
        qs.get_active_quest_descriptions({"archive_name", "guilt_admitted"})
    )
    if "уже слышал" not in hud_ok:
        errors.append(f"HUD с обеими правдами: {hud_ok}")

    from engine.quest_system import can_pass_fog, debt_face, has_debt, has_name

    if can_pass_fog({"archive_name"}) or can_pass_fog({"guilt_admitted"}):
        errors.append("один флаг правды открывает туман")
    if not can_pass_fog({"archive_name", "guilt_admitted"}):
        errors.append("имя и долг вместе не открывают туман")
    if has_name({"sennaya_name"}):
        errors.append("нищий снова считается именем без архива")
    if not has_name({"archive_name"}) or not has_debt({"nastasya_escape"}):
        errors.append("флаги имени и долга перепутаны")
    if debt_face({"guilt_admitted"}) != "Лизавете":
        errors.append(f"лицо долга вины: {debt_face({'guilt_admitted'})}")
    if "Настасье" not in debt_face({"nastasya_escape", "guilt_admitted"}):
        errors.append("два лица долга не сходятся")

    canal = db.get_note("note_canal") or db.get_item("note_canal") or {}
    canal_text = (canal.get("content") or "").lower()
    if "лизавет" not in canal_text:
        errors.append(f"записка с набережной без лица долга: {canal}")

    de_liz = DialogueEngine(db)
    if de_liz.start_dialogue("dialogue_panteleimon_intro", flags=set(), san=70):
        de_liz.present()
        de_liz.advance()
        kind_p, text_p = de_liz.choose(2)
        fin_p = de_liz.finish()
        if "guilt_admitted" not in (fin_p.get("flags") or []):
            errors.append(f"Пантелеймон не ставит вину: {fin_p}")
        if "лизавет" not in (text_p or "").lower():
            errors.append(f"Пантелеймон не называет Лизавету: {kind_p} {text_p}")
    else:
        errors.append("не стартует Пантелеймон для лица долга")

    de_w = DialogueEngine(db)
    if de_w.start_dialogue("dialogue_watchman_intro", flags=set(), san=70):
        de_w.present()
        de_w.advance()
        de_w.choose(1)
        fin_w = de_w.finish()
        if "guilt_admitted" in (fin_w.get("flags") or []):
            errors.append(f"постовой сам засчитал долг: {fin_w}")
    else:
        errors.append("не стартует постовой")

    import engine.rpg_system as rpg

    def _talk_to(dialogue_id, needle, flags=None):
        de = DialogueEngine(db)
        if not de.start_dialogue(
            dialogue_id,
            flags=flags or set(),
            san=70,
            player=players["seeker"],
        ):
            return None, None
        de.present()
        for _ in range(4):
            if de.get_choices():
                break
            kind, _text = de.advance()
            if kind in ("end", None):
                break
        choices = de.get_choices()
        idx = next((i for i, line in enumerate(choices) if needle in line.lower()), None)
        return de, idx

    old_talk = rpg.roll_3d6
    try:
        rpg.roll_3d6 = lambda: 3
        held = {"archive_name", "guilt_admitted"}
        de_lie = DialogueEngine(db)
        if not de_lie.start_dialogue(
            "dialogue_watchman_intro",
            flags=set(held),
            san=70,
            player=players["seeker"],
        ):
            errors.append("не стартует постовой для кости речи")
        else:
            de_lie.present()
            de_lie.advance()
            choices = de_lie.get_choices()
            idx = next((i for i, line in enumerate(choices) if "болен" in line.lower()), None)
            if idx is None:
                errors.append(f"нет лжи постовому: {choices}")
            else:
                _kind, text_lie = de_lie.choose(idx)
                if "халат не документ" not in (text_lie or "").lower():
                    errors.append(f"провал речи постовому не сменил ответ: {text_lie}")
                if "свисток пока молчит" in (text_lie or "").lower():
                    errors.append(f"провал речи совпал с успехом: {text_lie}")
                state = de_lie.current_dialogue
                if state and not held <= state.flags:
                    errors.append(f"провал речи снял правду: {sorted(state.flags)}")
                fin_lie = de_lie.finish()
                gained = set(fin_lie.get("flags") or [])
                if "archive_name" in gained or "guilt_admitted" in gained:
                    errors.append(f"ложь постовому выдала правду: {fin_lie}")
        de_ivan = DialogueEngine(db)
        if not de_ivan.start_dialogue(
            "dialogue_beggar_intro",
            flags={"archive_name"},
            san=70,
            player=players["seeker"],
        ):
            errors.append("не стартует нищий для кости речи")
        else:
            de_ivan.present()
            de_ivan.advance()
            choices = de_ivan.get_choices()
            idx = next((i for i, line in enumerate(choices) if "иван" in line.lower()), None)
            if idx is None:
                errors.append(f"нет чужого имени нищему: {choices}")
            else:
                _kind, text_ivan = de_ivan.choose(idx)
                if "чужое имя" not in (text_ivan or "").lower():
                    errors.append(f"провал Ивана не сменил ответ: {text_ivan}")
                if "иван так иван" in (text_ivan or "").lower():
                    errors.append(f"провал Ивана совпал с успехом: {text_ivan}")
                if (
                    de_ivan.current_dialogue
                    and "archive_name" not in de_ivan.current_dialogue.flags
                ):
                    errors.append("Иван снял имя архива")
                fin_ivan = de_ivan.finish()
                if "archive_name" in (fin_ivan.get("flags") or []):
                    errors.append(f"Иван выдал archive_name: {fin_ivan}")
        de_luk_fail, idx = _talk_to("dialogue_lukin_intro", "жилец")
        if de_luk_fail is None:
            errors.append("не стартует Лукин для провала речи")
        elif idx is None:
            errors.append("нет «жилец» у Лукина")
        else:
            _kind, text_luk_fail = de_luk_fail.choose(idx)
            if "не верю-с" not in (text_luk_fail or "").lower():
                errors.append(f"провал Лукина не сменил ответ: {text_luk_fail}")
            if "графы считаю" in (text_luk_fail or "").lower():
                errors.append(f"провал Лукина совпал с успехом: {text_luk_fail}")
            de_luk_fail.finish()
        de_doc_fail, idx = _talk_to("dialogue_shpilkin_intro", "не болен")
        if de_doc_fail is None:
            errors.append("не стартует Шпилькин для провала речи")
        elif idx is None:
            errors.append("нет отказа у Шпилькина")
        else:
            _kind, text_doc_fail = de_doc_fail.choose(idx)
            if "все так говорят" not in (text_doc_fail or "").lower():
                errors.append(f"провал Шпилькина не сменил ответ: {text_doc_fail}")
            if "капель не берите" in (text_doc_fail or "").lower():
                errors.append(f"провал Шпилькина совпал с успехом: {text_doc_fail}")
            de_doc_fail.finish()
        de_nas_fail, idx = _talk_to("dialogue_nastasya_intro", "это бред")
        if de_nas_fail is None:
            errors.append("не стартует Настасья для провала речи")
        elif idx is None:
            errors.append("нет бреда у Настасьи")
        else:
            _kind, text_nas_fail = de_nas_fail.choose(idx)
            if "это не бред" not in (text_nas_fail or "").lower():
                errors.append(f"провал Настасьи не сменил ответ: {text_nas_fail}")
            if "назовём бредом" in (text_nas_fail or "").lower():
                errors.append(f"провал Настасьи совпал с успехом: {text_nas_fail}")
            de_nas_fail.finish()
        rpg.roll_3d6 = lambda: 18
        de_ok = DialogueEngine(db)
        if de_ok.start_dialogue(
            "dialogue_watchman_intro",
            flags=set(),
            san=70,
            player=players["seeker"],
        ):
            de_ok.present()
            de_ok.advance()
            choices = de_ok.get_choices()
            idx = next((i for i, line in enumerate(choices) if "болен" in line.lower()), 0)
            _kind, text_ok = de_ok.choose(idx)
            if "свисток пока молчит" not in (text_ok or "").lower():
                errors.append(f"успех речи постовому сломан: {text_ok}")
            if "халат не документ" in (text_ok or "").lower():
                errors.append(f"успех речи совпал с провалом: {text_ok}")
            de_ok.finish()
        else:
            errors.append("не стартует постовой для успеха речи")
        de_ivan_ok = DialogueEngine(db)
        if de_ivan_ok.start_dialogue(
            "dialogue_beggar_intro",
            flags=set(),
            san=70,
            player=players["seeker"],
        ):
            de_ivan_ok.present()
            de_ivan_ok.advance()
            choices = de_ivan_ok.get_choices()
            idx = next((i for i, line in enumerate(choices) if "иван" in line.lower()), 0)
            _kind, text_ivan_ok = de_ivan_ok.choose(idx)
            if "иван так иван" not in (text_ivan_ok or "").lower():
                errors.append(f"успех Ивана сломан: {text_ivan_ok}")
            if "чужое имя" in (text_ivan_ok or "").lower():
                errors.append(f"успех Ивана совпал с провалом: {text_ivan_ok}")
            de_ivan_ok.finish()
        else:
            errors.append("не стартует нищий для успеха речи")
        de_luk_ok = DialogueEngine(db)
        if de_luk_ok.start_dialogue(
            "dialogue_lukin_intro",
            flags=set(),
            san=70,
            player=players["seeker"],
        ):
            de_luk_ok.present()
            de_luk_ok.advance()
            choices = de_luk_ok.get_choices()
            idx = next((i for i, line in enumerate(choices) if "жилец" in line.lower()), 0)
            _kind, text_luk_ok = de_luk_ok.choose(idx)
            if "шкафу" not in (text_luk_ok or "").lower():
                errors.append(f"успех Лукина сломан: {text_luk_ok}")
            if "не верю-с" in (text_luk_ok or "").lower():
                errors.append(f"успех Лукина совпал с провалом: {text_luk_ok}")
            de_luk_ok.finish()
        else:
            errors.append("не стартует Лукин для успеха речи")
        de_doc_ok, idx = _talk_to("dialogue_shpilkin_intro", "не болен")
        if de_doc_ok is None:
            errors.append("не стартует Шпилькин для успеха речи")
        elif idx is None:
            errors.append("нет отказа у Шпилькина для успеха")
        else:
            _kind, text_doc_ok = de_doc_ok.choose(idx)
            if "капель не берите" not in (text_doc_ok or "").lower():
                errors.append(f"успех Шпилькина сломан: {text_doc_ok}")
            if "все так говорят" in (text_doc_ok or "").lower():
                errors.append(f"успех Шпилькина совпал с провалом: {text_doc_ok}")
            de_doc_ok.finish()
        de_nas_ok, idx = _talk_to("dialogue_nastasya_intro", "это бред")
        if de_nas_ok is None:
            errors.append("не стартует Настасья для успеха речи")
        elif idx is None:
            errors.append("нет бреда у Настасьи для успеха")
        else:
            _kind, text_nas_ok = de_nas_ok.choose(idx)
            if "назовём бредом" not in (text_nas_ok or "").lower():
                errors.append(f"успех Настасьи сломан: {text_nas_ok}")
            if "это не бред" in (text_nas_ok or "").lower():
                errors.append(f"успех Настасьи совпал с провалом: {text_nas_ok}")
            de_nas_ok.finish()
    finally:
        rpg.roll_3d6 = old_talk

    de_tag = DialogueEngine(db)
    if de_tag.start_dialogue(
        "dialogue_watchman_intro",
        flags={"class_mystic"},
        san=70,
        player=players["seeker"],
    ):
        de_tag.present()
        de_tag.advance()
        tagged = de_tag.get_choices()
        lie = next((line for line in tagged if "болен" in line.lower()), "")
        hear = next((line for line in tagged if "свисток" in line.lower()), "")
        plain = next((line for line in tagged if "документов нет" in line.lower()), "")
        if "говорить" not in lie.lower() or "3d6" not in lie.lower() or "ложь" not in lie.lower():
            errors.append(f"ложь постовому без метки умения: {lie}")
        if "слышать" not in hear.lower() or "3d6" not in hear.lower():
            errors.append(f"свисток без метки слуха: {hear}")
        if "ложь" in hear.lower():
            errors.append(f"свисток помечен как ложь: {hear}")
        if "3d6" in plain.lower() or "ложь" in plain.lower():
            errors.append(f"признание не должно быть проверкой: {plain}")
        rpg.roll_3d6 = lambda: 18
        idx = next((i for i, line in enumerate(tagged) if "болен" in line.lower()), 0)
        de_tag.choose(idx)
        banner = de_tag.get_check_banner()
        if "говорить" not in banner.lower() or "успех" not in banner.lower() or "≥" not in banner:
            errors.append(f"после лжи нет строки броска: {banner}")
        de_tag.finish()
    else:
        errors.append("не стартует постовой для меток умения")
    rpg.roll_3d6 = old_talk

    from engine.dialogue_keys import MAX_DIALOGUE_CHOICES, choice_index_from_key

    if choice_index_from_key("N5") != 4 or choice_index_from_key("KP_5") != 4:
        errors.append("клавиша 5 не даёт пятый ответ")
    if choice_index_from_key("F5") is not None:
        errors.append("F5 не должна быть ответом")
    if choice_index_from_key("N9") != 8 or choice_index_from_key("N10") is not None:
        errors.append("диалог должен брать 1–9, не 10")
    de_five = DialogueEngine(db)
    if de_five.start_dialogue(
        "dialogue_watchman_intro",
        flags={"class_seeker", "knows_lizaveta"},
        san=70,
    ):
        de_five.present()
        de_five.advance()
        n_five = len(de_five.get_choices())
        if n_five != 5:
            errors.append(f"у постового с классом и бумагой не 5 ответов: {de_five.get_choices()}")
    else:
        errors.append("не стартует постовой для пяти ответов")

    de_dup = DialogueEngine(db)
    if de_dup.start_dialogue(
        "dialogue_watchman_repeat",
        flags={"guilt_admitted", "knows_lizaveta"},
        san=70,
    ):
        de_dup.present()
        de_dup.advance()
        liz_lines = [c for c in de_dup.get_choices() if "лизавет" in c.lower()]
        if len(liz_lines) != 1:
            errors.append(f"две «Лизавете» на повторе: {liz_lines}")
    else:
        errors.append("не стартует повтор постового для долга")

    pile = {
        "archive_name",
        "guilt_admitted",
        "nastasya_escape",
        "knows_lizaveta",
        "class_seeker",
        "broke_door",
        "mystic_trace",
        "seeker_trace",
    }
    max_n = 0
    max_id = ""
    for (did,) in db.conn.execute("SELECT id FROM dialogues"):
        de_max = DialogueEngine(db)
        if not de_max.start_dialogue(did, flags=pile, san=70):
            continue
        de_max.present()
        de_max.advance()
        n_opts = len(de_max.get_choices())
        if n_opts > max_n:
            max_n = n_opts
            max_id = did
    if max_n > MAX_DIALOGUE_CHOICES:
        errors.append(
            f"живой потолок ответов {max_n} у {max_id} > {MAX_DIALOGUE_CHOICES}"
        )
    engine_src = (ROOT / "engine" / "game_engine.py").read_text(encoding="utf-8")
    if "choice_index_from_key" not in engine_src:
        errors.append("движок диалога не берёт клавиши 1–9")

    canal_note = engine.entity_factory.create_item("note_canal")
    if canal_note:
        from engine.quest_system import QuestSystem as _NoteQuest

        engine.quest_system = engine.quest_system or _NoteQuest(db)
        engine.flags.discard("guilt_admitted")
        engine.flags.discard("knows_lizaveta")
        if canal_note.id in engine.quest_system.found_notes:
            engine.quest_system.found_notes.remove(canal_note.id)
        engine._read_note(canal_note)
        if "guilt_admitted" not in engine.flags:
            errors.append("записка с набережной не возвращает долг")
        engine.flags.discard("guilt_admitted")
        engine.flags.discard("knows_lizaveta")

    de_face = DialogueEngine(db)
    if de_face.start_dialogue("dialogue_shpilkin_repeat", flags={"guilt_admitted"}, san=70):
        kind_f, text_f = de_face.present()
        if kind_f != "text" or "лизавет" not in (text_f or "").lower():
            errors.append(f"Шпилькин не называет Лизавету: {kind_f} {text_f}")
        de_face.advance()
        if not any("лизавет" in c.lower() for c in de_face.get_choices()):
            errors.append(f"нет реплики про Лизавету: {de_face.get_choices()}")
    else:
        errors.append("не стартует повтор Шпилькина с виной")

    de_nface = DialogueEngine(db)
    if de_nface.start_dialogue(
        "dialogue_nastasya_repeat", flags={"nastasya_escape"}, san=70
    ):
        kind_n, text_n = de_nface.present()
        if kind_n != "text" or "настась" not in (text_n or "").lower() and "мне" not in (text_n or "").lower():
            errors.append(f"Настасья не слышит свой долг: {kind_n} {text_n}")
        de_nface.advance()
        if not any("выйти" in c.lower() or "выход" in c.lower() for c in de_nface.get_choices()):
            errors.append(f"нет реплики про выход Настасье: {de_nface.get_choices()}")
    else:
        errors.append("не стартует повтор Настасьи с долгом выхода")

    de_late = DialogueEngine(db)
    if de_late.start_dialogue("dialogue_nastasya_repeat", flags=set(), san=70):
        de_late.present()
        de_late.advance()
        late_opts = de_late.get_choices()
        idx = next(
            (
                i
                for i, line in enumerate(late_opts)
                if "выйти" in line.lower() or "долг вам" in line.lower()
            ),
            None,
        )
        if idx is None:
            errors.append(f"на повторе Настасьи без долга нет выхода: {late_opts}")
        else:
            late_line = late_opts[idx]
            if "(долг" not in late_line.lower() or "настась" not in late_line.lower():
                errors.append(f"поздний выход без скобок долга: {late_line}")
            de_late.choose(idx)
            fin_late = de_late.finish()
            if "nastasya_escape" not in (fin_late.get("flags") or []):
                errors.append(f"поздний долг Настасье не ставится: {fin_late}")
    else:
        errors.append("не стартует повтор Настасьи без долга")

    de_h = DialogueEngine(db)
    if de_h.start_dialogue("dialogue_shpilkin_repeat", flags={"archive_name"}, san=70):
        kind_h, text_h = de_h.present()
        if kind_h != "text" or "долг" not in (text_h or "").lower():
            errors.append(f"Шпилькин не слышит имя: {kind_h} {text_h}")
        kind_h, _ = de_h.advance()
        n_h = len(de_h.get_choices())
        if kind_h != "choices" or n_h < 4:
            errors.append(f"Шпилькин после имени без 4-й реплики: {de_h.get_choices()}")
        elif not any("назвал" in c.lower() for c in de_h.get_choices()):
            errors.append(f"нет вопроса про имя: {de_h.get_choices()}")
    else:
        errors.append("не стартует повтор Шпилькина с именем")

    for rid in (
        "dialogue_innkeeper_repeat",
        "dialogue_watchman_repeat",
        "dialogue_double_repeat",
        "dialogue_panteleimon_repeat",
        "dialogue_possessed_repeat",
    ):
        de_c = DialogueEngine(db)
        if de_c.start_dialogue(rid, flags={"archive_name"}, san=70):
            kind_c, text_c = de_c.present()
            if kind_c != "text" or "долг" not in (text_c or "").lower():
                errors.append(f"{rid} не слышит имя: {kind_c} {text_c}")
            de_c.advance()
            if len(de_c.get_choices()) < 4:
                errors.append(f"{rid} после имени без 4-й реплики: {de_c.get_choices()}")
        else:
            errors.append(f"не стартует {rid} с именем")

    de_pante_g = DialogueEngine(db)
    if de_pante_g.start_dialogue(
        "dialogue_panteleimon_repeat", flags={"guilt_admitted"}, san=70
    ):
        kind_g, text_g = de_pante_g.present()
        if kind_g != "text" or "лизавет" not in (text_g or "").lower():
            errors.append(f"Пантелеймон не слышит Лизавету: {kind_g} {text_g}")
        de_pante_g.advance()
        if not any("лизавет" in c.lower() for c in de_pante_g.get_choices()):
            errors.append(f"нет реплики Пантелеймона про Лизавету: {de_pante_g.get_choices()}")
    else:
        errors.append("не стартует повтор Пантелеймона с виной")

    de_poss_n = DialogueEngine(db)
    if de_poss_n.start_dialogue(
        "dialogue_possessed_repeat", flags={"nastasya_escape"}, san=70
    ):
        kind_q, text_q = de_poss_n.present()
        if kind_q != "text" or "настась" not in (text_q or "").lower():
            errors.append(f"одержимый не слышит Настасью: {kind_q} {text_q}")
        de_poss_n.advance()
        n_q = len(de_poss_n.get_choices())
        if n_q < 4 or not any("настась" in c.lower() for c in de_poss_n.get_choices()):
            errors.append(f"одержимый без реплики про Настасью: {de_poss_n.get_choices()}")
    else:
        errors.append("не стартует повтор одержимого с долгом выхода")

    map_grids = {
        "hospital_floor_1": floor,
        "hospital_floor_2": floor2,
        "hospital_basement": basement,
        "street_outside": street,
    }
    trig_rows = db.conn.execute(
        "SELECT id, map_id, x, y FROM triggers WHERE type = 'on_enter'"
    ).fetchall()
    if not trig_rows:
        errors.append("нет живых триггеров")
    for row in trig_rows:
        mid, x, y = row["map_id"], row["x"], row["y"]
        grid = map_grids.get(mid)
        if grid is None:
            errors.append(f"триггер {row['id']} на неизвестной карте {mid}")
            continue
        if y >= len(grid) or x >= len(grid[0]):
            errors.append(f"триггер {row['id']} вне карты {mid} ({x},{y})")
            continue
        tile = grid[y][x]
        if tile not in WALKABLE_TILES:
            errors.append(f"триггер {row['id']} на '{tile}' {mid} ({x},{y})")
    if db.get_triggers_at(15, 25, "hospital_floor_1"):
        errors.append("старый триггер 15,25 жив")
    if not db.get_triggers_at(18, 1, "hospital_floor_1"):
        errors.append("нет шёпота у лампы 1 этажа")

    engine.fired_triggers = set()
    san_before = engine.player.san
    r1 = engine.trigger_system.check_enter_trigger(
        18, 1, engine.player, "hospital_floor_1", engine.fired_triggers
    )
    engine.fired_triggers.update(r1.fired_ids)
    if not r1.messages:
        errors.append("шёпот не стреляет")
    if engine.player.san >= san_before:
        errors.append("триггер не снял SAN")
    san_mid = engine.player.san
    r2 = engine.trigger_system.check_enter_trigger(
        18, 1, engine.player, "hospital_floor_1", engine.fired_triggers
    )
    if r2.messages or r2.fired_ids or engine.player.san != san_mid:
        errors.append("триггер сработал повторно")

    engine._load_map("hospital_floor_1")
    engine.player.x, engine.player.y = 18, 2
    engine.player.hp = 7
    engine.flags.add("archive_name")
    engine.fired_triggers = {"trigger_whisper"}
    with tempfile.TemporaryDirectory() as tmp:
        slot = Path(tmp) / "last.json"
        if not engine.save_game(slot):
            errors.append("save_game не записал слот")
        else:
            payload = read_save(slot)
            if not payload or payload.get("player", {}).get("hp") != 7:
                errors.append(f"слот без HP: {payload}")
            engine.player.hp = 1
            engine.flags.discard("archive_name")
            engine.fired_triggers.clear()
            engine.player.x, engine.player.y = 16, 4
            if not engine.load_game(slot):
                errors.append("load_game не прочитал слот")
            else:
                if engine.player.hp != 7:
                    errors.append(f"после загрузки HP {engine.player.hp}")
                if "archive_name" not in engine.flags:
                    errors.append("после загрузки потерян флаг")
                if "trigger_whisper" not in engine.fired_triggers:
                    errors.append("после загрузки потерян сработавший триггер")
                if (engine.player.x, engine.player.y) != (18, 2):
                    errors.append(
                        f"после загрузки клетка {(engine.player.x, engine.player.y)}"
                    )
                if engine.current_map_id != "hospital_floor_1":
                    errors.append(f"после загрузки карта {engine.current_map_id}")
            engine.player.hp = 9
            engine.fired_triggers.add("trigger_fog")
            if engine.quit_and_save(slot) is not False:
                errors.append("quit_and_save должен остановить цикл")
            payload_quit = read_save(slot)
            if not payload_quit or payload_quit.get("player", {}).get("hp") != 9:
                errors.append("выход не записал слот")
            elif "trigger_fog" not in (payload_quit.get("fired_triggers") or []):
                errors.append("выход не запомнил триггер")

    from engine.constants import CLASS_GLIMPSES, ENDING_POSTSCRIPTS, ending_text

    if ending_text("flee", "seeker")[0] != ending_text("flee", "rebel")[0]:
        errors.append("заголовок бегства не должен меняться классом")
    if ending_text("flee", "seeker")[1] == ending_text("flee", "rebel")[1]:
        errors.append("бегство искателя и бунтаря одного голоса")
    if ending_text("stay", "mystic")[1] == ending_text("stay", "seeker")[1]:
        errors.append("остаться мистика и искателя одного голоса")
    if ending_text("madness", "rebel")[1] == ending_text("madness", "mystic")[1]:
        errors.append("бред бунтаря и мистика одного голоса")
    if len(ENDING_POSTSCRIPTS) != 9:
        errors.append(f"нужно 9 постскриптумов, есть {len(ENDING_POSTSCRIPTS)}")
    if ("mystic", "f2_study") not in CLASS_GLIMPSES:
        errors.append("мистик не видит кабинет 2-го этажа")
    if not db.get_triggers_at(42, 5, "hospital_floor_2"):
        errors.append("нет черновика в кабинете 2-го этажа")
    if floor2[5][42] not in WALKABLE_TILES:
        errors.append("черновик кабинета на непроходимой клетке")

    from engine.quest_system import QuestSystem as _QuestSystem

    engine.quest_system = engine.quest_system or _QuestSystem(db)
    note = engine.entity_factory.create_item("note_1")
    if note:
        engine.messages = []
        if note.id in engine.quest_system.found_notes:
            engine.quest_system.found_notes.remove(note.id)
        engine._read_note(note)
        joined = " ".join(engine.messages)
        if "===" in joined:
            errors.append(f"записка всё ещё лут-баннер: {joined}")
        if "теряете" in joined or "записок найдено" in joined:
            errors.append(f"записка говорит статами: {joined}")
        if "Показание" not in joined:
            errors.append(f"записка без слова «показание»: {joined}")

    engine._load_map("hospital_floor_2")
    engine.flags.discard("seeker_trace")
    for flag in list(engine.flags):
        if str(flag).startswith("searched:hospital_floor_2:34:5"):
            engine.flags.discard(flag)
    engine.player.x, engine.player.y = 34, 6
    engine.messages = []
    engine._try_interact()
    if "seeker_trace" not in engine.flags:
        errors.append("искатель не оставляет след на бюро")
    desk_text = " ".join(engine.messages)
    if "Пациент вспоминает" not in desk_text:
        errors.append(f"бюро без письма: {desk_text}")
    before = list(engine.messages)
    engine._try_interact()
    extra = engine.messages[len(before) :]
    if any("Пациент вспоминает" in m for m in extra):
        errors.append("бюро кабинета отдаёт письмо дважды")

    engine._load_map("hospital_floor_1")
    for flag in list(engine.flags):
        if str(flag).startswith("searched:hospital_floor_1:1:1"):
            engine.flags.discard(flag)
    engine.player.x, engine.player.y = 2, 1
    engine.messages = []
    engine._try_interact()
    cab = " ".join(engine.messages)
    if "Нащупали" not in cab and "ключ" not in cab.lower() and "дневник" not in cab.lower():
        errors.append(f"шкаф кабинета пуст при обыске: {cab}")

    import engine.rpg_system as rpg

    old_3d6 = rpg.roll_3d6
    try:
        rpg.roll_3d6 = lambda: 3
        if engine.quest_system and "letter_1" in engine.quest_system.found_notes:
            engine.quest_system.found_notes.remove("letter_1")
        engine._load_map("hospital_floor_2")
        for flag in list(engine.flags):
            if str(flag).startswith("searched:hospital_floor_2:34:5"):
                engine.flags.discard(flag)
        engine.messages = []
        engine._search_container(34, 5)
        fumble_letter = " ".join(engine.messages)
        if "Пациент вспоминает" not in fumble_letter:
            errors.append(f"письмо теряется на 18: {fumble_letter}")
        if engine.quest_system and "diary_1" in engine.quest_system.found_notes:
            engine.quest_system.found_notes.remove("diary_1")
        engine._load_map("hospital_floor_1")
        for flag in list(engine.flags):
            if str(flag).startswith("searched:hospital_floor_1:1:1"):
                engine.flags.discard(flag)
        engine.messages = []
        engine._search_container(1, 1)
        fumble_diary = " ".join(engine.messages)
        if "Нащупали" not in fumble_diary and "дневник" not in fumble_diary.lower():
            errors.append(f"дневник теряется на 18: {fumble_diary}")
        for flag in list(engine.flags):
            if str(flag).startswith("searched:hospital_floor_1:42:4"):
                engine.flags.discard(flag)
        potions_before = sum(1 for item in engine.player.inventory if item.id == "potion_heal")
        engine.messages = []
        engine._search_container(42, 4)
        potions_after = sum(1 for item in engine.player.inventory if item.id == "potion_heal")
        potion_text = " ".join(engine.messages)
        if potions_after > potions_before:
            errors.append(f"зелье нашлось на 18: {potion_text}")
        if "searched:hospital_floor_1:42:4" not in engine.flags:
            errors.append("провал обыска не помечает мебель")
        for flag in list(engine.flags):
            if str(flag).startswith("searched:hospital_floor_1:42:4"):
                engine.flags.discard(flag)
        rpg.roll_3d6 = lambda: 18
        engine.messages = []
        engine._search_container(42, 4)
        crit_search = " ".join(engine.messages)
        if "Почерк дрожит" in crit_search:
            errors.append("крит обыска врёт про почерк")
        if "шов" not in crit_search.lower():
            errors.append(f"крит обыска без фразы: {crit_search}")
        rpg.roll_3d6 = lambda: 18
        amount, _phrase = rpg.san_loss_for("note_canal", engine.player)
        if amount != 0:
            errors.append(f"успех воли на канал теряет {amount}")
        engine.flags.discard("san_checked:note_canal")
        san_before = engine.player.san
        engine._apply_san_event("note_canal")
        if engine.player.san != san_before:
            errors.append("успех воли всё равно снял SAN")

        from engine.rpg_system import SAN_EVENTS
        import inspect

        for (paper_id,) in db.conn.execute(
            "SELECT id FROM items WHERE type = 'note' AND IFNULL(sanity_damage, 0) != 0"
        ):
            if paper_id not in SAN_EVENTS:
                errors.append(f"бумага {paper_id} не в таблице CoC")
        for event_id in ("double", "guilt_admitted", "possessed"):
            if event_id not in SAN_EVENTS:
                errors.append(f"нет события {event_id} в таблице CoC")
        if "sanity_damage" in inspect.getsource(GameEngine._read_note):
            errors.append("бумага всё ещё плюсует поле предмета")
        if "change_san" in inspect.getsource(GameEngine._try_attack):
            errors.append("удар по двойнику бьёт SAN вне таблицы")
        if "sanity_damage" not in inspect.getsource(GameEngine._enemy_riposte):
            errors.append("бой потерял SAN удара врага")

        engine.flags.discard("san_checked:diary_1")
        if engine.quest_system and "diary_1" in engine.quest_system.found_notes:
            engine.quest_system.found_notes.remove("diary_1")
        engine.player.san = 80
        diary = engine.entity_factory.create_item("diary_1")
        if diary:
            engine._read_note(diary)
            if engine.player.san == 75:
                errors.append("дневник плюсует поле предмета к таблице")
            if engine.player.san != 80:
                errors.append(f"дневник при успехе воли: {engine.player.san}")

        engine.flags.discard("guilt_admitted")
        engine.flags.discard("san_checked:guilt_admitted")
        engine.player.san = 80
        engine._apply_dialogue_result(
            {
                "sanity_change": -8,
                "flags": ["guilt_admitted"],
                "items_given": [],
                "ending_id": None,
            }
        )
        if engine.player.san == 72:
            errors.append("признание плюсует строку диалога к таблице")
        if engine.player.san != 79:
            errors.append(f"признание при успехе воли: {engine.player.san}")

        engine.flags.discard("spoke_possessed")
        engine.flags.discard("san_checked:possessed")
        engine.player.san = 80
        engine._apply_dialogue_result(
            {
                "sanity_change": -12,
                "flags": ["spoke_possessed"],
                "items_given": [],
                "ending_id": None,
            }
        )
        if engine.player.san != 79:
            errors.append(f"одержимый плюсует реплики: {engine.player.san}")

        de_coc = DialogueEngine(db)
        if de_coc.start_dialogue("dialogue_possessed_intro", flags=set(), san=80):
            de_coc.present()
            de_coc.advance()
            if de_coc.get_choices():
                de_coc.choose(0)
            fin_p = de_coc.finish() or {}
            if (fin_p.get("sanity_change") or 0) != 0:
                errors.append(f"речь одержимого капает SAN: {fin_p}")
    finally:
        rpg.roll_3d6 = old_3d6

    from engine.game_engine import GameState as _GameState

    saved_end, saved_state = engine.ending_id, engine.state
    engine._load_map("street_outside")
    engine.player.san = 80
    engine.player.x, engine.player.y = 51, 10
    engine.flags = {"archive_name"}
    engine.ending_id = None
    engine.state = _GameState.PLAYING
    engine._check_street_ending()
    if engine.ending_id:
        errors.append(f"одно имя дало конец {engine.ending_id}")
    engine.player.x, engine.player.y = 57, 9
    engine._try_transition(58, 9)
    if engine.current_map_id != "street_outside":
        errors.append("одно имя пустило в дом")
    engine.flags.add("guilt_admitted")
    engine.flags.discard("fog_blocked")
    engine.flags.discard("fog_house")
    engine.ending_id = None
    engine.state = _GameState.PLAYING
    engine.player.x, engine.player.y = 51, 10
    engine._check_street_ending()
    if engine.ending_id:
        errors.append(f"имя и долг дали титры в тумане: {engine.ending_id}")
    engine.player.x, engine.player.y = 57, 9
    engine._try_transition(58, 9)
    if engine.current_map_id != "street_tenement":
        errors.append("имя и долг не открывают дом")
    engine._load_map("street_outside")
    engine.player.x, engine.player.y = 57, 9
    engine.ending_id = None
    engine.state = _GameState.PLAYING
    engine.flags = {"class_seeker"}
    old_notes = list(engine.quest_system.found_notes)
    engine.quest_system.found_notes = ["note_1", "note_2", "note_3"]
    engine._check_street_ending()
    if engine.ending_id == "flee":
        errors.append("три записки снова ключ от тумана")
    engine._try_transition(58, 9)
    if engine.current_map_id != "street_outside":
        errors.append("три записки пустили в дом")
    from engine.quest_system import NOTE_TRUTH as _NOTE_TRUTH

    if "note_tenement" in _NOTE_TRUTH:
        errors.append("домовая книга снова ключ тумана")
    de_house = DialogueEngine(db)
    if de_house.start_dialogue(
        "dialogue_praskovya_repeat",
        flags={"archive_name", "guilt_admitted"},
        san=80,
    ):
        de_house.present()
        de_house.advance()
        flee_choices = de_house.get_choices()
        flee_i = next(
            (i for i, text in enumerate(flee_choices) if "довольно" in text.lower()),
            None,
        )
        if flee_i is None:
            errors.append(f"Прасковья не отпускает в город: {flee_choices}")
        else:
            de_house.choose(flee_i)
            de_house.advance()
            fin_house = de_house.finish() or {}
            if fin_house.get("ending_id") != "flee":
                errors.append(f"Прасковья не даёт бегство: {fin_house}")
    else:
        errors.append("не стартует диалог Прасковьи")
    engine.ending_id = saved_end
    engine.state = saved_state
    engine.quest_system.found_notes = old_notes

    old_pid = engine.player.id
    import engine.rpg_system as rpg_hear

    old_hear = rpg_hear.roll_3d6
    try:
        rpg_hear.roll_3d6 = lambda: 18
        engine.player.id = "mystic"
        engine.flags.discard("mystic_trace")
        engine.fired_triggers = set()
        engine._load_map("hospital_floor_1")
        engine.player.x, engine.player.y = 18, 2
        engine._try_move(0, -1)
        if "mystic_trace" not in engine.flags:
            errors.append("мистик не оставляет след у лампы")
        rpg_hear.roll_3d6 = lambda: 3
        engine.flags.discard("mystic_trace")
        engine.fired_triggers = set()
        engine.player.x, engine.player.y = 18, 2
        engine.messages = []
        engine._try_move(0, -1)
        if "mystic_trace" in engine.flags:
            errors.append("провал слуха всё равно дал след")
        if "сбился" not in " ".join(engine.messages).lower():
            errors.append(f"провал слуха без фразы: {engine.messages}")
        de_wh = DialogueEngine(db)
        if not de_wh.start_dialogue(
            "dialogue_watchman_intro",
            flags={"class_mystic", "archive_name", "guilt_admitted"},
            san=70,
            player=players["mystic"],
        ):
            errors.append("не стартует постовой для свистка")
        else:
            de_wh.present()
            de_wh.advance()
            choices = de_wh.get_choices()
            idx = next(
                (i for i, line in enumerate(choices) if "свисток" in line.lower()),
                None,
            )
            if idx is None:
                errors.append(f"нет свистка у постового: {choices}")
            else:
                _kind, text_wh = de_wh.choose(idx)
                if "свисток обычный" not in (text_wh or "").lower():
                    errors.append(f"провал слуха свистка не сменил ответ: {text_wh}")
                state = de_wh.current_dialogue
                if state and (
                    "archive_name" not in state.flags
                    or "guilt_admitted" not in state.flags
                ):
                    errors.append(f"свисток снял правду: {sorted(state.flags)}")
                fin_wh = de_wh.finish()
                gained = set(fin_wh.get("flags") or [])
                if "archive_name" in gained or "guilt_admitted" in gained:
                    errors.append(f"свисток выдал правду: {fin_wh}")
        rpg_hear.roll_3d6 = lambda: 18
        de_wh_ok = DialogueEngine(db)
        if de_wh_ok.start_dialogue(
            "dialogue_watchman_intro",
            flags={"class_mystic"},
            san=70,
            player=players["mystic"],
        ):
            de_wh_ok.present()
            de_wh_ok.advance()
            choices = de_wh_ok.get_choices()
            idx = next(
                (i for i, line in enumerate(choices) if "свисток" in line.lower()),
                0,
            )
            _kind, text_ok = de_wh_ok.choose(idx)
            if "не свищу" not in (text_ok or "").lower():
                errors.append(f"успех свистка сломан: {text_ok}")
            de_wh_ok.finish()
        else:
            errors.append("не стартует постовой для успеха свистка")
        engine.player.id = "seeker"
        engine.player.talents = ["hear_1", "hear_2"]
        engine.flags.discard("mystic_trace")
        engine.fired_triggers = set()
        engine._load_map("hospital_floor_1")
        engine.player.x, engine.player.y = 18, 2
        rpg_hear.roll_3d6 = lambda: 18
        engine._try_move(0, -1)
        if "mystic_trace" not in engine.flags:
            errors.append("талант слуха не работает у лампы без занятия мистика")
        engine.player.talents = []
    finally:
        rpg_hear.roll_3d6 = old_hear
        engine.player.id = old_pid

    import engine.rpg_system as rpg_sneak

    old_sneak = rpg_sneak.roll_3d6
    try:
        engine._load_map("hospital_basement")
        shadow = next(
            (e for e in engine.entities if getattr(e, "id", "") == "shadow_enemy"),
            None,
        )
        if not shadow:
            errors.append("в подвале нет тени для красться")
        else:
            rpg_sneak.roll_3d6 = lambda: 18
            engine.state = _GameState.PLAYING
            engine.current_enemy = None
            engine.player.x, engine.player.y = shadow.x - 1, shadow.y
            engine.messages = []
            engine._try_move(1, 0)
            if engine.state == _GameState.COMBAT:
                errors.append("успех красться всё равно открыл сцену")
            if (engine.player.x, engine.player.y) != (shadow.x + 1, shadow.y):
                errors.append(
                    f"не прошли за тень: {(engine.player.x, engine.player.y)} тень {(shadow.x, shadow.y)}"
                )
            if "мимо" not in " ".join(engine.messages).lower():
                errors.append(f"успех красться без фразы: {engine.messages}")
            rpg_sneak.roll_3d6 = lambda: 3
            engine.state = _GameState.PLAYING
            engine.current_enemy = None
            engine.player.x, engine.player.y = shadow.x - 1, shadow.y
            engine.messages = []
            engine._try_move(1, 0)
            if engine.state != _GameState.COMBAT:
                errors.append("провал красться не открыл бой")
            engine.state = _GameState.PLAYING
            engine.current_enemy = None
        rpg_sneak.roll_3d6 = lambda: 3
        engine._load_map("hospital_floor_1")
        possessed = next(
            (e for e in engine.entities if getattr(e, "id", "") == "possessed_patient"),
            None,
        )
        if not possessed:
            errors.append("нет одержимого, чтобы проверить красться")
        else:
            engine.state = _GameState.PLAYING
            engine.current_enemy = None
            engine.player.x, engine.player.y = possessed.x - 1, possessed.y
            engine._try_move(1, 0)
            if engine.state != _GameState.COMBAT:
                errors.append("одержимого обошли крастьюся")
            engine.state = _GameState.PLAYING
            engine.current_enemy = None
    finally:
        rpg_sneak.roll_3d6 = old_sneak

    import engine.rpg_system as rpg_break

    old_break = rpg_break.roll_3d6
    old_break_id = engine.player.id
    try:
        rpg_break.roll_3d6 = lambda: 18
        engine.player.id = "rebel"
        engine.flags.discard("broke_door")
        engine._load_map("hospital_floor_1")
        engine.current_map[2][12] = "d"
        wall = engine.current_map[3][12]
        engine._try_open_door(12, 2, "d")
        if engine.current_map[2][12] != "'":
            errors.append("бунтарь не выбил дверь кабинета")
        if "broke_door" not in engine.flags:
            errors.append("нет флага сломанной двери")
        if engine.current_map[3][12] != wall or wall == "'":
            errors.append("плечо сломало стену канона")
        rpg_break.roll_3d6 = lambda: 3
        engine.flags.discard("broke_door")
        engine.current_map[2][12] = "d"
        engine._try_open_door(12, 2, "d")
        if engine.current_map[2][12] != "d":
            errors.append("провал лома всё равно открыл кабинет")
        if "broke_door" in engine.flags:
            errors.append("провал лома поставил broke_door")
        rpg_break.roll_3d6 = lambda: 3
        engine._load_map("hospital_basement")
        engine.current_map[3][40] = "d"
        engine._try_open_door(40, 3, "d")
        if engine.current_map[3][40] != "d":
            errors.append("бунтарь выбил дверь лаборатории")
        engine.player.id = "seeker"
        engine._load_map("hospital_floor_1")
        engine.current_map[2][12] = "d"
        engine._try_open_door(12, 2, "d")
        if engine.current_map[2][12] != "d":
            errors.append("искатель выбил дверь плечом")
    finally:
        rpg_break.roll_3d6 = old_break
        engine.player.id = old_break_id

    colors = db.get_tile_colors()
    if "'" not in colors:
        errors.append("нет цвета открытой двери")
    wall_bg = colors.get("#", {}).get("bg", "")
    floor_bg = colors.get(".", {}).get("bg", "")
    door_fg = colors.get("D", {}).get("fg", "")
    if wall_bg and floor_bg and wall_bg.lower() == floor_bg.lower():
        errors.append("стена и пол одного цвета")
    if door_fg.lower() in (wall_bg.lower(), floor_bg.lower()):
        errors.append("дверь сливается со стеной")

    from engine.palette import INKS, TILE_INKS, is_viridian

    if not (12 <= len(INKS) <= 18):
        errors.append(f"палитра не 12–18 чернил: {len(INKS)}")
    allowed = {h.lower() for h in INKS.values()}
    for name, hex_color in INKS.items():
        if is_viridian(hex_color):
            errors.append(f"виридиан в чернилах {name}: {hex_color}")
    extra = set(colors) - set(TILE_INKS)
    if extra:
        errors.append(f"лишние глифы в tile_colors: {sorted(extra)}")
    for symbol, spec in colors.items():
        if symbol not in TILE_INKS:
            continue
        for slot in ("fg", "bg"):
            hx = (spec.get(slot) or "").lower()
            if hx and hx not in allowed:
                errors.append(f"тайл {symbol} {slot} {hx} вне палитры")
    pickup = colors.get("!", {})
    if pickup and is_viridian(pickup.get("fg") or ""):
        errors.append(f"предмет всё ещё зелёный: {pickup}")
    lamp_fg = (colors.get("*", {}).get("fg") or "").lower()
    if lamp_fg and lamp_fg == (floor_bg or "").lower():
        errors.append("лампа сливается с полом")
    if "lamp" not in TILE_INKS["*"] or "frost" not in TILE_INKS["W"]:
        errors.append("лампа или окно не на своих чернилах")

    from engine.fov_system import FOVSystem

    grid = [["."] * 15 for _ in range(15)]
    fov = FOVSystem(15, 15)
    fov.initialize(grid)
    fov.compute_fov(7, 7, grid, [])
    near = fov.get_illumination(7, 7)
    far = fov.get_illumination(7, 13)
    if near <= far:
        errors.append(f"нет градиента зрения: у @ {near:.2f}, вдали {far:.2f}")

    fov_w = FOVSystem(15, 15)
    fov_w.initialize(grid)
    fov_w.compute_fov(
        7,
        7,
        grid,
        [{"x": 2, "y": 7, "radius": 5, "intensity": 0.7, "symbol": "W"}],
    )
    pane = fov_w.get_window_illumination(2, 7)
    pool = fov_w.get_window_illumination(4, 7)
    if pane <= pool:
        errors.append(f"лунный свет без градиента: у стекла {pane:.2f}, вдали {pool:.2f}")
    if fov_w.get_flame_illumination(2, 7) > 0.01:
        errors.append("окно мерцает как лампа")

    engine._load_map("hospital_floor_1")
    engine.current_map[3][52] = "D"
    engine._try_open_door(52, 3, "D")
    if engine.current_map[3][52] != "'":
        errors.append(f"открытая дверь стала {engine.current_map[3][52]!r}, не порог")

    from engine.game_engine import GameState as _LiveState, MOVE_STEP_SECONDS

    ge_src = (ROOT / "engine" / "game_engine.py").read_text(encoding="utf-8")
    if "tcod.event.wait()" in ge_src:
        errors.append("цикл всё ещё ждёт клавишу")
    if "tcod.event.get()" not in ge_src:
        errors.append("нет живого кадра")
    if "_tick_held_walk" not in ge_src or "_ensure_fov" not in ge_src:
        errors.append("нет зажатой ходьбы или кэша FOV")
    if "KeySym.F4" not in ge_src or "_toggle_glyph_mode" not in ge_src:
        errors.append("нет переключателя буквы/картинки")
    if "KeySym.M" not in ge_src or "clinic_music" not in ge_src:
        errors.append("нет mute музыки")
    if "KeySym.T" not in ge_src or "тетрадь" not in (
        ROOT / "engine" / "renderer.py"
    ).read_text(encoding="utf-8"):
        errors.append("нет тетради талантов")
    if "is_character_open" not in ge_src or "НА СЕБЕ" not in (
        ROOT / "engine" / "renderer.py"
    ).read_text(encoding="utf-8"):
        errors.append("нет окна на себе")

    from engine.constants import BRED_MAP_ID
    from engine.music import MAP_TRACKS, resolve_source

    expected_tracks = {
        "hospital_floor_1": "clinic_hall",
        "hospital_floor_2": "clinic_hall",
        "hospital_basement": "basement",
        "street_outside": "street_canal",
        "street_traktir": "traktir",
        "street_tenement": "street_canal",
        BRED_MAP_ID: "bred",
    }
    if MAP_TRACKS != expected_tracks:
        errors.append("MAP_TRACKS не совпадает с картами")
    for stem in sorted(set(MAP_TRACKS.values())):
        if resolve_source(stem) is None:
            errors.append(f"нет петли data/music/{stem}")

    from engine.clinic_tiles import TILE_HEIGHT, TILE_WIDTH
    from engine.portraits import PORTRAIT_COLS, PORTRAIT_FILES, PORTRAIT_ROWS, portrait_path

    box_aspect = (PORTRAIT_COLS * TILE_WIDTH) / (PORTRAIT_ROWS * TILE_HEIGHT)
    if abs(box_aspect - 0.75) > 0.05:
        errors.append("рамка портрета не 3:4")
    for pid, name in PORTRAIT_FILES.items():
        if portrait_path(pid) is None:
            errors.append(f"нет портрета data/portraits/{name}")
    for house_pid in ("shopkeeper_lukin", "landlady_praskovya"):
        if house_pid not in PORTRAIT_FILES:
            errors.append(f"нет портрета {house_pid} в списке")
        elif portrait_path(house_pid) is None:
            errors.append(f"нет файла портрета {PORTRAIT_FILES[house_pid]}")
    if "_fit_portrait_dest" not in (ROOT / "engine" / "renderer.py").read_text(
        encoding="utf-8"
    ):
        errors.append("портрет снова растягивается в клетку")
    if "_wrap_choice" not in (ROOT / "engine" / "renderer.py").read_text(
        encoding="utf-8"
    ):
        errors.append("длинный ответ снова режется троеточием")
    long_talk = (
        "[Говорить: 3d6+0 ≥ 11] [ложь] "
        "Помогите выйти отсюда. Прошу. Выход, слышите? Мне нужно слышать это слово целиком."
    )
    wrapped_talk = engine.renderer._wrap_choice(long_talk, 0, 42)
    talk_blob = " ".join(wrapped_talk)
    if "слышать это слово целиком" not in talk_blob:
        errors.append(f"длинный ответ потерял хвост: {wrapped_talk}")
    if any(row.rstrip().endswith("...") for row in wrapped_talk):
        errors.append(f"длинный ответ снова с троеточием: {wrapped_talk}")
    if "говорить" not in talk_blob.lower() or "ложь" not in talk_blob.lower():
        errors.append(f"метка умения пропала при переносе: {wrapped_talk}")
    if len(wrapped_talk) < 2:
        errors.append(f"длинный ответ не перенёсся на строки: {wrapped_talk}")

    saved_talk = (
        engine.current_map_id,
        engine.player.x,
        engine.player.y,
        engine.state,
        engine.current_dialogue_portrait,
        set(engine.flags),
        list(engine.player.talents),
        list(engine.messages),
        set(engine.visited_regions),
    )
    engine.flags.add("archive_name")
    engine.flags.add("guilt_admitted")
    engine._load_map("street_tenement")
    lukin = next(
        (e for e in engine.entities if getattr(e, "id", "") == "shopkeeper_lukin"),
        None,
    )
    if not lukin:
        errors.append("Лукин не стоит в лавке")
    else:
        engine.state = _LiveState.PLAYING
        engine.player.x, engine.player.y = lukin.x, lukin.y + 1
        engine._try_interact()
        if engine.current_dialogue_portrait != "shopkeeper_lukin":
            errors.append(
                f"разговор с Лукиным без портрета: {engine.current_dialogue_portrait!r}"
            )
    prask = next(
        (e for e in engine.entities if getattr(e, "id", "") == "landlady_praskovya"),
        None,
    )
    if not prask:
        errors.append("Прасковья не стоит в квартире")
    else:
        engine.state = _LiveState.PLAYING
        engine.current_dialogue_portrait = ""
        engine.player.x, engine.player.y = prask.x, prask.y + 1
        engine._try_interact()
        if engine.current_dialogue_portrait != "landlady_praskovya":
            errors.append(
                f"разговор с Прасковьей без портрета: {engine.current_dialogue_portrait!r}"
            )
    engine.player.talents = ["search_1", "trace_1"]
    engine.visited_regions = set()
    engine.messages = []
    engine.flags.discard("talent_trace:ten_shop")
    engine._check_region(10, 4)
    if "овал от ключей" not in " ".join(engine.messages).lower():
        errors.append(f"талант следа молчит в лавке: {engine.messages}")
    (
        map_id,
        px,
        py,
        st,
        portrait,
        flags,
        talents,
        messages,
        visited,
    ) = saved_talk
    engine.flags = flags
    engine.player.talents = talents
    engine.visited_regions = visited
    engine.messages = messages
    engine.current_dialogue_portrait = portrait
    engine.state = st
    if map_id:
        engine._load_map(map_id)
        engine.player.x, engine.player.y = px, py

    engine._load_map("hospital_floor_1")
    engine.player.x, engine.player.y = 18, 2
    engine.state = _LiveState.PLAYING
    engine.showing_help = False
    engine.is_inventory_open = False
    engine.is_talents_open = False
    engine.is_character_open = False
    engine.oil_overlay = None
    engine._reset_realtime()
    engine._compute_fov()
    fov_calls = {"n": 0}
    orig_fov = engine._compute_fov

    def _counted_fov():
        fov_calls["n"] += 1
        orig_fov()

    engine._compute_fov = _counted_fov
    engine._ensure_fov()
    if fov_calls["n"]:
        errors.append("FOV пересчитался без шага")
    engine._mark_fov_dirty()
    engine._ensure_fov()
    if fov_calls["n"] != 1:
        errors.append("грязный FOV не пересчитался")
    engine._compute_fov = orig_fov

    engine._reset_realtime()
    engine.player.x, engine.player.y = 18, 2
    start_x = engine.player.x
    engine._held_dirs = [("right", 1, 0)]
    engine._tick_held_walk(0.0)
    if engine.player.x != start_x + 1:
        errors.append("зажатый шаг не сдвинул")
    engine._tick_held_walk(0.05)
    if engine.player.x != start_x + 1:
        errors.append("шаг быстрее паузы на клетку")
    engine._tick_held_walk(MOVE_STEP_SECONDS)
    if engine.player.x != start_x + 2:
        errors.append("второй шаг зажатой ходьбы не прошёл")
    frozen_x = engine.player.x
    engine.state = _LiveState.DIALOGUE
    engine._move_cooldown = 0.0
    engine._tick_held_walk(1.0)
    if engine.player.x != frozen_x:
        errors.append("диалог не стопает ходьбу")
    engine.state = _LiveState.PLAYING
    engine.is_inventory_open = True
    engine._move_cooldown = 0.0
    engine._tick_held_walk(1.0)
    if engine.player.x != frozen_x:
        errors.append("инвентарь не стопает ходьбу")
    engine.is_inventory_open = False

    from engine.clinic_font import (
        BUNDLED_FONT,
        REQUIRED_CODEPOINTS,
        find_font_path,
        glyph_is_drawn,
        glyph_width_fill,
        load_clinic_tileset,
    )
    from engine import sound as clinic_sound

    if "load_clinic_tileset" not in (ROOT / "main.py").read_text(encoding="utf-8"):
        errors.append("main.py не подключает шрифт клиники")
    if "keep_aspect=True" not in (ROOT / "engine" / "renderer.py").read_text(encoding="utf-8"):
        errors.append("кадр растягивает клетки: нет keep_aspect")
    if not BUNDLED_FONT.is_file():
        errors.append("нет assets/fonts/DejaVuSansMono.ttf")
    font_path = find_font_path()
    if font_path is None:
        errors.append("нет шрифта с кириллицей")
    else:
        tileset = load_clinic_tileset(font_path)
        if tileset is None:
            errors.append("тайлсет не загрузился")
        else:
            for code in REQUIRED_CODEPOINTS:
                if not glyph_is_drawn(tileset, code):
                    errors.append(f"пустой глиф {hex(code)}")
            fill_m = glyph_width_fill(tileset, ord("M"))
            if fill_m < 0.65:
                errors.append(f"глиф M слишком узкий в клетке: {fill_m:.2f}")
            if tileset.tile_width >= tileset.tile_height:
                errors.append(
                    f"клетка {tileset.tile_width}x{tileset.tile_height} не уже высоты"
                )
            if tileset.tile_width != 16 or tileset.tile_height != 24:
                errors.append(
                    f"прототип клетки не 16×24: {tileset.tile_width}x{tileset.tile_height}"
                )
            from engine.clinic_tiles import (
                PROTO_CHARS,
                map_glyph,
                paint_proto_tile,
                sprite_chars,
                sprite_codepoint,
                tile_alpha_sum,
            )
            from engine.constants import TILE_LEGEND

            legend_syms = {row[0] for row in TILE_LEGEND}
            if set(PROTO_CHARS) != legend_syms:
                errors.append(
                    f"спрайты не покрывают легенду: {sorted(legend_syms - set(PROTO_CHARS))}"
                )
            wall_a = tile_alpha_sum(tileset.get_tile(sprite_codepoint("#")))
            floor_a = tile_alpha_sum(tileset.get_tile(sprite_codepoint(".")))
            letter_hash = tile_alpha_sum(tileset.get_tile(ord("#")))
            letter_dot = tile_alpha_sum(tileset.get_tile(ord(".")))
            letter_h = tile_alpha_sum(tileset.get_tile(ord("H")))
            cab_a = tile_alpha_sum(tileset.get_tile(sprite_codepoint("H")))
            if wall_a <= floor_a:
                errors.append(f"стена не плотнее пола: {wall_a} <= {floor_a}")
            if letter_dot >= floor_a:
                errors.append("точка в диалоге стала полом")
            if letter_h >= cab_a:
                errors.append("H в HP стала шкафом")
            if letter_hash >= wall_a:
                errors.append("буква # съедена маской")
            if map_glyph(".", True) == ".":
                errors.append("пол не ушёл в PUA")
            if map_glyph(".", False) != ".":
                errors.append("F4 не возвращает точку")
            if map_glyph("Ж", True) != "Ж":
                errors.append("кириллица ушла в PUA")
            for char in sprite_chars():
                painted = paint_proto_tile(char)
                live = tileset.get_tile(sprite_codepoint(char))
                if tile_alpha_sum(live) != tile_alpha_sum(painted):
                    errors.append(f"глиф {char!r} без спрайта прототипа")
                if tile_alpha_sum(painted) == 0:
                    errors.append(f"пустой спрайт {char!r}")
            if tile_alpha_sum(paint_proto_tile("&")) == tile_alpha_sum(
                paint_proto_tile("@")
            ):
                errors.append("человек неотличим от халата")
            if tile_alpha_sum(paint_proto_tile("B")) <= floor_a:
                errors.append("кровать не плотнее пола")
            if tile_alpha_sum(paint_proto_tile("W")) <= floor_a:
                errors.append("окно не плотнее пола")
            from engine.clinic_font import apply_sprite_mode

            if not getattr(tileset, "_clinic_sprites_ready", False):
                errors.append("маски не легли в PUA")
            else:
                apply_sprite_mode(tileset, False)
                if tile_alpha_sum(tileset.get_tile(ord("."))) != letter_dot:
                    errors.append("F4 трогает точку в шрифте")
                apply_sprite_mode(tileset, True)
                if tile_alpha_sum(tileset.get_tile(sprite_codepoint("#"))) != wall_a:
                    errors.append("F4 снял маску стены с PUA")
            ascii_ts = load_clinic_tileset(font_path, sprites=False)
            if ascii_ts is None:
                errors.append("тайлсет без масок не загрузился")
            elif tile_alpha_sum(ascii_ts.get_tile(ord("#"))) >= wall_a:
                errors.append("sprites=False всё ещё маска на #")
            elif tile_alpha_sum(ascii_ts.get_tile(sprite_codepoint("#"))) != wall_a:
                errors.append("PUA пуста при sprites=False")
            from engine.renderer import Renderer

            probe = Renderer(SCREEN_WIDTH, SCREEN_HEIGHT)

            class _GlyphHost:
                use_sprites = True
                clinic_tileset = tileset

            probe.game_engine = _GlyphHost()
            if probe._tile_glyph(".") == ".":
                errors.append("карта печатает точку вместо маски пола")
            if probe._tile_glyph("Ж") != "Ж":
                errors.append("кириллица на карте ушла в PUA")
            from engine.clinic_tiles import (
                WALL_MASK_BASE,
                paint_wall_mask,
                wall_glyph,
                wall_neighbor_mask,
            )

            pillar = [list("..."), list(".#."), list("...")]
            if wall_neighbor_mask(pillar, 1, 1) != 0:
                errors.append("столб стены стыкуется с полом")
            run = [list("#####")]
            if wall_neighbor_mask(run, 2, 0) != (1 | 2 | 4 | 8):
                # N/S за краем — стена, E/W — стена
                errors.append(f"ряд стен не сплошной: {wall_neighbor_mask(run, 2, 0)}")
            lip = tile_alpha_sum(paint_wall_mask(0))
            solid = tile_alpha_sum(paint_wall_mask(15))
            if lip <= solid:
                errors.append("открытая стена не гуще сплошной")
            if tile_alpha_sum(tileset.get_tile(WALL_MASK_BASE)) != lip:
                errors.append("автотайл столба не в тайлсете")
            if probe._tile_glyph("#", 1, 1, pillar) != wall_glyph(0):
                errors.append("карта не берёт автотайл стены")
            probe.game_engine.use_sprites = False
            if probe._tile_glyph(".") != ".":
                errors.append("F4 не возвращает букву на карте")
    paper = clinic_sound._wav_for("paper")
    door = clinic_sound._wav_for("door")
    if paper[:4] != b"RIFF" or door[:4] != b"RIFF":
        errors.append("клики не WAV")
    clinic_sound.play("paper")

    db.close()
    if errors:
        print("FAIL")
        for e in errors:
            print(" -", e)
        raise SystemExit(1)
    print("OK")
    print("STR по классам:", strs)
    print("спавн 1 этажа:", first_count)
    print("методы:", ", ".join(sorted(methods)[:8]), "...")


if __name__ == "__main__":
    main()
