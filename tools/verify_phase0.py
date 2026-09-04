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
        "_handle_combat",
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
    from engine.entity_factory import EntityFactory
    shadow = EntityFactory(db).create_character("shadow_enemy")
    if not shadow:
        errors.append("нет тени для боя")
    else:
        hit, dmg, msg = ge_mod.perform_attack(players["seeker"], shadow)
        if not isinstance(msg, str) or not msg:
            errors.append(f"удар без сообщения: {hit} {dmg} {msg}")

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
    engine.showing_help = False
    engine.is_inventory_open = False
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
    }
    for map_id, expect_w, expect_h in (
        ("hospital_floor_1", 57, 12),
        ("hospital_floor_2", 57, 12),
        ("hospital_basement", 57, 12),
        ("street_outside", 60, 20),
        ("street_traktir", 36, 14),
        ("hospital_bred", 57, 12),
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

    from engine.dialogue_engine import DialogueEngine
    de = DialogueEngine(db)
    if not de.start_dialogue("dialogue_nastasya_intro", flags=set(), san=80):
        errors.append("не стартует диалог Настасьи")
    de.present()
    de.advance()
    kind, _text = de.advance()
    if kind != "choices" or len(de.get_choices()) != 3:
        errors.append(f"выбор Настасьи: {kind} / {de.get_choices()}")
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
        if kind != "choices" or len(de_r.get_choices()) != 3:
            errors.append(f"повтор без выбора: {repeat_id} {kind} / {de_r.get_choices()}")

    stay_repeat = DialogueEngine(db)
    if stay_repeat.start_dialogue("dialogue_shpilkin_repeat", flags=set(), san=70):
        stay_repeat.present()
        stay_repeat.advance()
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
        if not any("выход" in c.lower() for c in de_nface.get_choices()):
            errors.append(f"нет реплики про выход Настасье: {de_nface.get_choices()}")
    else:
        errors.append("не стартует повтор Настасьи с долгом выхода")

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
    engine.flags.add("guilt_admitted")
    engine.flags.discard("fog_blocked")
    engine.ending_id = None
    engine.state = _GameState.PLAYING
    engine._check_street_ending()
    if engine.ending_id != "flee":
        errors.append("имя и долг не открывают бегство")
    engine.ending_id = None
    engine.state = _GameState.PLAYING
    engine.flags = {"class_seeker"}
    old_notes = list(engine.quest_system.found_notes)
    engine.quest_system.found_notes = ["note_1", "note_2", "note_3"]
    engine._check_street_ending()
    if engine.ending_id == "flee":
        errors.append("три записки снова ключ от тумана")
    engine.ending_id = saved_end
    engine.state = saved_state
    engine.quest_system.found_notes = old_notes

    old_pid = engine.player.id
    engine.player.id = "mystic"
    engine.flags.discard("mystic_trace")
    engine.fired_triggers = set()
    engine._load_map("hospital_floor_1")
    engine.player.x, engine.player.y = 18, 2
    engine._try_move(0, -1)
    if "mystic_trace" not in engine.flags:
        errors.append("мистик не оставляет след у лампы")
    engine.player.id = old_pid

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

    from engine.constants import BRED_MAP_ID
    from engine.music import MAP_TRACKS, resolve_source

    expected_tracks = {
        "hospital_floor_1": "clinic_hall",
        "hospital_floor_2": "clinic_hall",
        "hospital_basement": "basement",
        "street_outside": "street_canal",
        "street_traktir": "traktir",
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
    if "_fit_portrait_dest" not in (ROOT / "engine" / "renderer.py").read_text(
        encoding="utf-8"
    ):
        errors.append("портрет снова растягивается в клетку")

    engine._load_map("hospital_floor_1")
    engine.player.x, engine.player.y = 18, 2
    engine.state = _LiveState.PLAYING
    engine.showing_help = False
    engine.is_inventory_open = False
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
