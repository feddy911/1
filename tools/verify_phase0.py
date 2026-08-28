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
    src = (ROOT / "engine" / "game_engine.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    methods = {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "GameEngine"
        for node in node.body
        if isinstance(node, ast.FunctionDef)
    }
    for name in ("_try_attack", "_try_read", "_try_interact", "_maybe_spawn_double"):
        if name not in methods:
            errors.append(f"нет метода {name}")
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
    if floor[12][8] != "d":
        errors.append("запертая дверь кабинета не на месте")
    if floor[12][48] != "D":
        errors.append("дверь к лестнице должна быть открываемой")
    if floor[9][12] != "*" or floor[9][36] != "*":
        errors.append("лампы в коридоре не на месте")
    if floor[2][3] != "@":
        errors.append("игрок съехал со старта")
    if floor[14][0] != "#" or floor[13][16] != "#":
        errors.append("сломан каркас кабинета на 1 этаже")

    assert_map_walkable(errors, "floor_1", floor, (3, 2), 57)

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
    if db.get_door_lock("hospital_floor_1", 8, 12) != "key_warden":
        errors.append("кабинет должен открываться ключом смотрителя")
    if db.get_door_lock("hospital_basement", 20, 10) != "key_basement":
        errors.append("лаборатория должна открываться ключом от подвала")
    if not db.get_region_at("street_outside", 8, 10):
        errors.append("у улицы нет описания крыльца")
    floor2 = load_map(ROOT / "data" / "maps" / "floor_2.txt")
    if floor2[15][55] != "s":
        errors.append("лестница 2 этажа съехала")
    assert_map_walkable(errors, "floor_2", floor2, (55, 15), 57)
    basement = load_map(ROOT / "data" / "maps" / "basement.txt")
    if basement[10][20] != "d":
        errors.append("дверь лаборатории съехала")
    if basement[10][10] not in WALKABLE_TILES:
        errors.append("документ в лаборатории на стене")
    if basement[7][3] not in WALKABLE_TILES:
        errors.append("дверь камеры в подвале снова упирается в стену")
    assert_map_walkable(errors, "basement", basement, (55, 16), 60)
    street = load_map(ROOT / "data" / "maps" / "street.txt")
    if street[9][0] != "E" or street[17][10] != "=":
        errors.append("улица: нет выхода или канала")
    if street[6][26] != "E":
        errors.append("вход в трактир съехал")
    if street[7][26] not in WALKABLE_TILES or street[5][26] not in WALKABLE_TILES:
        errors.append("дверь трактира не открывается с улицы и изнутри")
    assert_map_walkable(errors, "street", street, (1, 9), 60)
    traktir = load_map(ROOT / "data" / "maps" / "traktir.txt")
    if traktir[7][0] != "E" or traktir[7][1] not in WALKABLE_TILES:
        errors.append("трактир: нет выхода")
    assert_map_walkable(errors, "traktir", traktir, (1, 7), 36)
    if db.get_connection_at_position("street_outside", 26, 6) is None:
        errors.append("нет связи улица → трактир")
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
    assert_map_walkable(errors, "bred", bred, (46, 15), 57)
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
            if "sennaya_name" not in (fin3.get("flags") or []):
                errors.append(f"нищий не отдаёт имя: {fin3}")
        else:
            errors.append("у нищего нет выбора")
    else:
        errors.append("не стартует диалог нищего")

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
