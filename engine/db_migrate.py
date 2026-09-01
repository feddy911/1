"""Идемпотентные правки схемы и данных фазы 0."""
from typing import List, Tuple


PLACEMENTS: List[Tuple[str, int, int, str, str]] = [
    # Первый этаж — палаты, коридор, кабинет
    ("hospital_floor_1", 19, 3, "character", "patient_nastasya"),
    ("hospital_floor_1", 22, 10, "character", "sanitary_panteleimon"),
    ("hospital_floor_1", 8, 15, "character", "doctor_shpilkin"),
    ("hospital_floor_1", 52, 3, "character", "possessed_patient"),
    ("hospital_floor_1", 11, 3, "item", "note_1"),
    ("hospital_floor_1", 27, 4, "item", "note_2"),
    ("hospital_floor_1", 5, 16, "item", "diary_1"),
    ("hospital_floor_1", 22, 15, "item", "diary_2"),
    ("hospital_floor_1", 43, 5, "item", "diary_3"),
    ("hospital_floor_1", 16, 10, "item", "key_warden"),
    ("hospital_floor_1", 4, 14, "item", "key_doctor"),
    ("hospital_floor_1", 12, 16, "item", "key_basement"),
    ("hospital_floor_1", 5, 4, "item", "potion_heal"),
    ("hospital_floor_1", 44, 5, "item", "potion_sanity"),
    ("hospital_floor_1", 6, 5, "item", "item_knife"),
    # Второй этаж — пока пустой зал, один расходник
    ("hospital_floor_2", 10, 8, "item", "potion_heal"),
    # Подвал
    ("hospital_basement", 15, 8, "character", "shadow_enemy"),
    ("hospital_basement", 40, 10, "character", "shadow_enemy"),
    ("hospital_basement", 10, 10, "item", "document_1"),
]


TILE_COLORS = [
    ("B", "#6a5a4a", "#3a322c", "Кровать"),
    ("T", "#8a6a40", "#4a3828", "Стол"),
    ("C", "#7a6048", "#3a3028", "Стул"),
    ("H", "#5a5048", "#322c28", "Шкаф"),
    ("O", "#6a5840", "#3a3228", "Письменный стол"),
    ("E", "#64dcff", "#3c8ca0", "Выход"),
    ("s", "#5088a0", "#2c5a68", "Лестница вниз"),
    ("W", "#aaccff", "#6688aa", "Окно"),
    ("*", "#fff064", "#b4a032", "Источник света"),
    ("+", "#ff6666", "#803232", "Расходник"),
    ("=", "#1a3048", "#0c1828", "Канал"),
]

TILE_COLORS_EXPLORED = [
    ("B", "#3a322c", "#1e1a16"),
    ("T", "#4a3828", "#241c14"),
    ("C", "#3a3028", "#1e1814"),
    ("H", "#322c28", "#1a1614"),
    ("O", "#3a3228", "#1e1a14"),
    ("E", "#326e82", "#1e4650"),
    ("s", "#284858", "#142830"),
    ("W", "#445566", "#223344"),
    ("*", "#827832", "#5a5019"),
    ("+", "#823232", "#401919"),
    ("=", "#0c1828", "#060c14"),
]

TILE_TRANSPARENCY = [
    ("#", 1, "Стена"),
    (" ", 1, "Пустота"),
    ("d", 1, "Запертая дверь"),
    ("H", 1, "Шкаф"),
    ("O", 1, "Письменный стол"),
    (".", 0, "Пол"),
    ("D", 0, "Дверь"),
    ("W", 0, "Окно"),
    ("S", 0, "Лестница"),
    ("s", 0, "Лестница вниз"),
    ("E", 0, "Выход"),
    ("*", 0, "Свет"),
    ("B", 0, "Кровать"),
    ("T", 0, "Стол"),
    ("C", 0, "Стул"),
    ("=", 1, "Канал"),
]


def apply_migrations(conn) -> None:
    """Применить правки фазы 0. Безопасно вызывать при каждом запуске."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS map_placements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            map_id TEXT NOT NULL,
            x INTEGER NOT NULL,
            y INTEGER NOT NULL,
            spawn_type TEXT NOT NULL CHECK(spawn_type IN ('character', 'item')),
            spawn_id TEXT NOT NULL,
            UNIQUE(map_id, x, y)
        );
        """
    )

    conn.execute("DELETE FROM map_placements")
    conn.executemany(
        """INSERT INTO map_placements (map_id, x, y, spawn_type, spawn_id)
           VALUES (?, ?, ?, ?, ?)""",
        PLACEMENTS,
    )

    conn.execute(
        """UPDATE light_sources
           SET description = 'Лунный свет из окна',
               symbol = 'W',
               color = '#aaccff',
               radius = 5,
               intensity = 0.7,
               flicker = 0
           WHERE id = 'window'"""
    )

    conn.execute(
        "UPDATE characters SET symbol = '&' WHERE id = 'doctor_shpilkin'"
    )
    conn.execute(
        "UPDATE characters SET symbol = '&' WHERE id = 'possessed_patient'"
    )
    conn.execute(
        "UPDATE characters SET symbol = '&' WHERE id = 'sanitary_panteleimon'"
    )
    conn.execute(
        """UPDATE characters
           SET symbol = '&', color = '#8877aa'
           WHERE id = 'shadow_enemy'"""
    )

    def _upsert(table: str, symbol: str, fields: dict) -> None:
        exists = conn.execute(
            f"SELECT 1 FROM {table} WHERE symbol = ?", (symbol,)
        ).fetchone()
        if exists:
            assignments = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE {table} SET {assignments} WHERE symbol = ?",
                (*fields.values(), symbol),
            )
        else:
            cols = ", ".join(["symbol", *fields.keys()])
            placeholders = ", ".join("?" * (1 + len(fields)))
            conn.execute(
                f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
                (symbol, *fields.values()),
            )

    for symbol, fg, bg, desc in TILE_COLORS:
        _upsert(
            "tile_colors",
            symbol,
            {"fg_color": fg, "bg_color": bg, "description": desc},
        )

    for symbol, fg, bg in TILE_COLORS_EXPLORED:
        _upsert(
            "tile_colors_explored",
            symbol,
            {"fg_color": fg, "bg_color": bg},
        )

    for symbol, blocks, desc in TILE_TRANSPARENCY:
        _upsert(
            "tile_transparency",
            symbol,
            {"blocks_light": blocks, "description": desc},
        )

    # Пантелеймон ссылался на несуществующий диалог.
    conn.execute(
        """INSERT INTO dialogues (id, character_id, trigger_condition)
           VALUES ('dialogue_panteleimon_intro', 'sanitary_panteleimon', NULL)
           ON CONFLICT(id) DO NOTHING"""
    )
    existing = conn.execute(
        "SELECT COUNT(*) FROM dialogue_lines WHERE dialogue_id = 'dialogue_panteleimon_intro'"
    ).fetchone()[0]
    if existing == 0:
        conn.executemany(
            """INSERT INTO dialogue_lines
               (dialogue_id, order_num, speaker, text, sanity_change)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (
                    "dialogue_panteleimon_intro",
                    1,
                    "npc",
                    "Ночью не бродите. Тени любят любопытных.",
                    0,
                ),
                (
                    "dialogue_panteleimon_intro",
                    2,
                    "npc",
                    "Ключ от подвала — у доктора. Не говорите, что я сказал.",
                    -2,
                ),
            ],
        )

    # Пустой content у стартовой записки — берём описание.
    conn.execute(
        """UPDATE items SET content = description
           WHERE id = 'note_mysterious' AND (content IS NULL OR content = '')"""
    )

    _apply_phase1(conn)
    conn.commit()


def _ensure_column(conn, table: str, column: str, spec: str) -> None:
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {spec}")


def _apply_phase1(conn) -> None:
    """Карты уже в файлах; здесь — ключи, регионы, ветки диалогов, концовки."""
    for column, spec in (
        ("next_order", "INTEGER"),
        ("choice_group", "INTEGER"),
        ("sets_flag", "TEXT"),
        ("requires_flag", "TEXT"),
        ("requires_min_san", "INTEGER"),
        ("ending_id", "TEXT"),
    ):
        _ensure_column(conn, "dialogue_lines", column, spec)

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS door_locks (
            map_id TEXT NOT NULL,
            x INTEGER NOT NULL,
            y INTEGER NOT NULL,
            required_key_id TEXT NOT NULL,
            PRIMARY KEY (map_id, x, y)
        );
        CREATE TABLE IF NOT EXISTS map_regions (
            id TEXT PRIMARY KEY,
            map_id TEXT NOT NULL,
            x1 INTEGER NOT NULL,
            y1 INTEGER NOT NULL,
            x2 INTEGER NOT NULL,
            y2 INTEGER NOT NULL,
            name TEXT NOT NULL,
            first_visit_text TEXT,
            sanity_effect INTEGER DEFAULT 0
        );
        """
    )

    conn.execute("DELETE FROM door_locks")
    conn.executemany(
        "INSERT INTO door_locks (map_id, x, y, required_key_id) VALUES (?, ?, ?, ?)",
        [
            ("hospital_floor_1", 8, 12, "key_warden"),
            ("hospital_floor_2", 8, 12, "key_doctor"),
            ("hospital_basement", 20, 10, "key_basement"),
        ],
    )

    conn.execute("DELETE FROM map_regions")
    conn.executemany(
        """INSERT INTO map_regions
           (id, map_id, x1, y1, x2, y2, name, first_visit_text, sanity_effect)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            ("f1_ward", "hospital_floor_1", 1, 1, 7, 6, "Палата",
             "Палата. Запах карболки и сырой ваты. Кровать привинчена — значит, здесь не гости.", 0),
            ("f1_hall", "hospital_floor_1", 1, 8, 55, 11, "Коридор",
             "Коридор длиннее, чем здание. Лампы моргают, будто считают шаги.", -1),
            ("f1_office", "hospital_floor_1", 1, 13, 15, 18, "Кабинет",
             "Кабинет. Бумаги, пузырьки, чужой почерк. Здесь решают, кто вы.", 0),
            ("f1_cafe", "hospital_floor_1", 41, 1, 55, 6, "Столовая",
             "Столовая без еды. Стулья ждут тех, кого уже увели.", -2),
            ("f1_stairs", "hospital_floor_1", 42, 13, 55, 18, "Лестница",
             "Лестница пахнет сыростью снизу и одеколоном сверху.", 0),
            ("f2_archive", "hospital_floor_2", 1, 1, 23, 6, "Архив",
             "Закрытое крыло. Полки с историями болезней — или чужими именами.", -2),
            ("f2_study", "hospital_floor_2", 1, 13, 15, 18, "Кабинет главврача",
             "Личный кабинет Шпилькина. Здесь письма не для академии.", -3),
            ("f2_hall", "hospital_floor_2", 1, 8, 47, 11, "Коридор второго этажа",
             "Тише, чем внизу. Тишина здесь платная.", 0),
            ("b_cells", "hospital_basement", 1, 1, 19, 6, "Камеры",
             "Камеры без табличек. Кто-то скреб ногтями по изнанке двери.", -4),
            ("b_lab", "hospital_basement", 1, 10, 19, 18, "Лаборатория",
             "Лаборатория. На столе — следы мела и чего-то темнее мела.", -5),
            ("b_hall", "hospital_basement", 21, 7, 58, 18, "Подвал",
             "Подвал дышит вам в затылок. Свет не доходит до углов — углы доходят сами.", -3),
            ("st_porch", "street_outside", 1, 7, 12, 13, "Крыльцо",
             "Ночь. Петербург. Туман липнет к лицу, как мокрый бинт.", 0),
            ("st_embankment", "street_outside", 1, 14, 58, 16, "Набережная",
             "Канал чёрный, без отражений. Город есть — и города нет.", -2),
            ("st_fog", "street_outside", 45, 1, 58, 15, "Туман",
             "Дальше — вата и фонари, которые не обещают улицы.", 0),
        ],
    )

    conn.execute(
        """INSERT INTO items
           (id, type, name, description, damage_die, healing, sanity_restore,
            sanity_damage, symbol, color, is_quest_item, use_effect, content)
           VALUES (?, 'note', ?, ?, '', 0, 0, -5, '≈', '#c8b48c', 1, 'read_note', ?)
           ON CONFLICT(id) DO UPDATE SET content = excluded.content""",
        (
            "letter_1",
            "Письмо из Петербурга",
            "Конверт с печатью академии.",
            "Уважаемый доктор фон Шпилькин! Новые препараты высланы. "
            "Результаты — к концу месяца. Не подведите нас.",
        ),
    )

    conn.execute(
        """UPDATE map_connections SET target_x = 55
           WHERE source_map_id = 'street_outside' AND target_map_id = 'hospital_floor_1'"""
    )

    conn.execute("DELETE FROM map_placements")
    conn.executemany(
        """INSERT INTO map_placements (map_id, x, y, spawn_type, spawn_id)
           VALUES (?, ?, ?, ?, ?)""",
        PLACEMENTS_PHASE1,
    )

    _seed_dialogues(conn)
    _seed_double(conn)
    _apply_phase3(conn)
    _apply_phase4(conn)
    _apply_phase5(conn)
    _apply_phase6(conn)
    _apply_phase7(conn)
    _apply_phase10(conn)


PLACEMENTS_PHASE1: List[Tuple[str, int, int, str, str]] = [
    ("hospital_floor_1", 19, 3, "character", "patient_nastasya"),
    ("hospital_floor_1", 22, 10, "character", "sanitary_panteleimon"),
    ("hospital_floor_1", 8, 15, "character", "doctor_shpilkin"),
    ("hospital_floor_1", 52, 3, "character", "possessed_patient"),
    ("hospital_floor_1", 11, 3, "item", "note_1"),
    ("hospital_floor_1", 27, 4, "item", "note_2"),
    ("hospital_floor_1", 5, 16, "item", "diary_1"),
    ("hospital_floor_1", 22, 15, "item", "diary_2"),
    ("hospital_floor_1", 43, 5, "item", "diary_3"),
    ("hospital_floor_1", 16, 10, "item", "key_warden"),
    ("hospital_floor_1", 4, 14, "item", "key_doctor"),
    ("hospital_floor_1", 12, 16, "item", "key_basement"),
    ("hospital_floor_1", 5, 4, "item", "potion_heal"),
    ("hospital_floor_1", 44, 5, "item", "potion_sanity"),
    ("hospital_floor_1", 6, 5, "item", "item_knife"),
    ("hospital_floor_2", 10, 8, "item", "potion_heal"),
    ("hospital_floor_2", 6, 16, "item", "letter_1"),
    ("hospital_floor_2", 22, 10, "character", "archivist_klara"),
    ("hospital_floor_2", 4, 3, "item", "note_case"),
    ("hospital_basement", 30, 9, "character", "shadow_enemy"),
    ("hospital_basement", 40, 11, "character", "shadow_enemy"),
    ("hospital_basement", 10, 10, "item", "document_1"),
]


def _seed_dialogues(conn) -> None:
    ids = [
        "dialogue_shpilkin_intro",
        "dialogue_shpilkin_repeat",
        "dialogue_nastasya_intro",
        "dialogue_nastasya_repeat",
        "dialogue_panteleimon_intro",
        "dialogue_panteleimon_repeat",
    ]
    conn.executemany("DELETE FROM dialogue_lines WHERE dialogue_id = ?", [(i,) for i in ids])
    conn.executemany("DELETE FROM dialogues WHERE id = ?", [(i,) for i in ids])
    conn.executemany(
        "INSERT INTO dialogues (id, character_id, trigger_condition) VALUES (?, ?, NULL)",
        [
            ("dialogue_shpilkin_intro", "doctor_shpilkin"),
            ("dialogue_shpilkin_repeat", "doctor_shpilkin"),
            ("dialogue_nastasya_intro", "patient_nastasya"),
            ("dialogue_nastasya_repeat", "patient_nastasya"),
            ("dialogue_panteleimon_intro", "sanitary_panteleimon"),
            ("dialogue_panteleimon_repeat", "sanitary_panteleimon"),
        ],
    )

    # order_num, speaker, text, san, next, group, sets_flag, ending [, requires_flag]
    def rows(dialogue_id, entries):
        out = []
        for entry in entries:
            if len(entry) == 8:
                entry = (*entry, None)
            (
                order_num,
                speaker,
                text,
                san,
                next_order,
                group,
                sets_flag,
                ending,
                requires,
            ) = entry
            out.append(
                (
                    dialogue_id,
                    order_num,
                    speaker,
                    text,
                    san,
                    next_order,
                    group,
                    sets_flag,
                    ending,
                    requires,
                )
            )
        return out

    lines = []
    lines += rows(
        "dialogue_shpilkin_intro",
        [
            (1, "npc", "А, вы проснулись. Интересно...", 0, 2, None, None, None),
            (2, "npc", "Голова? Память? Или уже тени в углах?", 0, 10, None, None, None),
            (10, "player", "Где я? Кто вы?", 0, 20, 1, None, None),
            (11, "player", "Не подходите. Я не болен.", 0, 30, 1, "refuse_doctor", None),
            (12, "player", "Дайте микстуру. Хочу забыть.", -5, 40, 1, "trust_doctor", None),
            (20, "npc", "Клиника. Я доктор фон Шпилькин. Вам здесь безопаснее, чем на улице.", 0, 21, None, "spoke_shpilkin", None),
            (21, "npc", "Ночью коридоры врут. Не верьте зеркалам — и не верьте мне, если я стану слишком добр.", 0, -1, None, None, None),
            (30, "npc", "Страх — хороший признак. Значит, вы ещё не тень.", -3, -1, None, "spoke_shpilkin", None),
            (40, "npc", "Хорошо. Ложитесь. Утром не будет ни клиники, ни вас.", -15, -1, None, "spoke_shpilkin", "stay"),
            (13, "player", "На чернильнице свежий почерк. Это моё дело?", 0, 50, 1, None, None, "class_seeker"),
            (14, "player", "В углу дышат в такт вам. Кто вы?", -2, 51, 1, None, None, "class_mystic"),
            (15, "player", "Откройте дверь. Или открою я.", 0, 52, 1, None, None, "class_rebel"),
            (50, "npc", "Наблюдательный. Дело пока не ваше. Читайте дневники, не зеркала.", 0, -1, None, "spoke_shpilkin", None),
            (51, "npc", "Я доктор. То, что дышит — уже не всегда я. Пейте, если хотите одного ответа.", -4, -1, None, "spoke_shpilkin", None),
            (52, "npc", "Двери здесь отпирают ключом, не плечом. Хотя плечо у вас привычное.", 0, -1, None, "spoke_shpilkin", None),
        ],
    )
    lines += rows(
        "dialogue_shpilkin_repeat",
        [
            (1, "npc", "Имя и долг. Туман сыт. Идите, пока не передумал.", 0, 10, None, None, None, "has_both"),
            (2, "npc", "Вы назвались. Капли от этого не слаще — долг ещё в коридоре.", 0, 10, None, None, None, "has_name"),
            (3, "npc", "Вина есть. Имени нет. Номер в журнале не выпускают.", 0, 10, None, None, None, "has_debt"),
            (4, "npc", "Вы всё ходите. Значит, капли ещё не взяли.", 0, 10, None, None, None),
            (10, "player", "Что в подвале?", 0, 20, 1, None, None),
            (11, "player", "Дайте микстуру. Хочу кончить это.", -8, 30, 1, "trust_doctor", None),
            (12, "player", "Я уйду на улицу.", 0, 40, 1, None, None),
            (13, "player", "Я назвался. Этого мало?", 0, 50, 1, None, None, "has_name"),
            (14, "player", "Я должен. Пустите.", 0, 51, 1, None, None, "has_debt"),
            (20, "npc", "Там кормят тех, кто слишком много видел. Не спускайтесь голодными.", -3, -1, None, None, None),
            (30, "npc", "Хорошо. Ложитесь. Утром не будет ни клиники, ни вас.", -15, -1, None, None, "stay"),
            (40, "npc", "Улица не клиника. Клиника честнее: она хотя бы запирает.", 0, -1, None, None, None),
            (50, "npc", "Мало. Туман ест по отдельности: имя — бумага, долг — кровь.", 0, -1, None, None, None),
            (51, "npc", "Долг без имени — клетка. Назовите себя, хотя бы плохо.", 0, -1, None, None, None),
        ],
    )
    lines += rows(
        "dialogue_nastasya_intro",
        [
            (1, "npc", "Вы тоже видите их? Тени в углах...", 0, 2, None, None, None),
            (2, "npc", "Они шепчут имена. Даже те, которых нет.", -2, 10, None, None, None),
            (10, "player", "Да. Я видел.", -6, 20, 1, "nastasya_warned", None),
            (11, "player", "Это бред. Ваш и мой.", 0, 30, 1, None, None),
            (12, "player", "Помогите выйти отсюда.", 0, 40, 1, "nastasya_escape", None),
            (20, "npc", "Тогда не спите. Пантелеймон носит вниз тех, кто слишком много видел.", -3, 21, None, "spoke_nastasya", None),
            (21, "npc", "Подвал. Там не лечат. Там кормят.", 0, -1, None, None, None),
            (30, "npc", "Как скажете. Бред тоже умеет убивать.", -5, -1, None, "spoke_nastasya", None),
            (40, "npc", "Улица не выпускает безымянных. Соберите бумаги Шпилькина — или туман съест вас.", 0, 41, None, "spoke_nastasya", None),
            (41, "narrator", "Она прячет лицо в ладонях. Платье когда-то было бальным.", 0, -1, None, None, None),
            (13, "player", "Имена на полу стёрты рукавом. Как выйти?", 0, 50, 1, "nastasya_escape", None, "class_seeker"),
            (14, "player", "Они шепчут уменьшительное. Это моё?", -4, 51, 1, None, None, "class_mystic"),
            (15, "player", "Довольно шёпота. Где дверь наружу?", 0, 52, 1, "nastasya_escape", None, "class_rebel"),
            (50, "npc", "След верный. Бумаги немца и имя — иначе вата на востоке съест шаг.", 0, -1, None, "spoke_nastasya", None),
            (51, "npc", "Если шепчут ласково — не отзывайтесь. Это не мать.", -5, -1, None, "spoke_nastasya", None),
            (52, "npc", "Дверь на улице. Туман не плечо: его берут правдой, не ударом.", 0, -1, None, "spoke_nastasya", None),
        ],
    )
    lines += rows(
        "dialogue_nastasya_repeat",
        [
            (1, "npc", "Имя и долг. Вата на востоке уже тонкая. Идите.", 0, 10, None, None, None, "has_both"),
            (2, "npc", "Вы назвались. Долг ещё шепчет в углу.", 0, 10, None, None, None, "has_name"),
            (3, "npc", "Вы просили выход. Без имени вата сытая.", 0, 10, None, None, None, "has_debt"),
            (4, "npc", "Вы вернулись. Значит, ещё не назвали вас вслух.", 0, 10, None, None, None),
            (10, "player", "Как пройти туман?", 0, 20, 1, None, None),
            (11, "player", "Доктор лжёт?", 0, 30, 1, None, None),
            (12, "player", "Мне нельзя спать?", -2, 40, 1, None, None),
            (13, "player", "Я вспомнил имя. Этого хватит?", 0, 50, 1, None, None, "has_name"),
            (14, "player", "Я должен. Пустите.", 0, 51, 1, None, None, "has_debt"),
            (15, "player", "Шёпот у лампы был не мой.", -2, 52, 1, None, None, "mystic_trace"),
            (20, "npc", "Именем и долгом вместе. Иначе вата съест шаг.", 0, -1, None, None, None),
            (30, "npc", "Он лечит так, чтобы некого было выписывать. Не пейте, если хотите улицу.", -3, -1, None, None, None),
            (40, "npc", "Сон здесь — дверь вниз. Пантелеймон ждёт тех, кто закрыл глаза.", -2, -1, None, None, None),
            (50, "npc", "Имени мало. Туман хочет знать, кому вы должны.", 0, -1, None, None, None),
            (51, "npc", "Долга мало. Безымянных вата не считает.", 0, -1, None, None, None),
            (52, "npc", "Значит, он уже звал. Не отвечайте второй раз — даже кивком.", -3, -1, None, None, None),
        ],
    )
    lines += rows(
        "dialogue_panteleimon_intro",
        [
            (1, "npc", "Ночью не бродите. Тени любят любопытных.", 0, 10, None, None, None),
            (10, "player", "Где ключи?", 0, 20, 1, None, None),
            (11, "player", "Что за человек — доктор?", 0, 30, 1, None, None),
            (12, "player", "(признаться) Я кого-то погубил.", -8, 40, 1, "guilt_admitted", None),
            (20, "npc", "От палат — у меня. От кабинета доктора ищите сами. От подвала — только у него.", 0, 21, None, "spoke_panteleimon", None),
            (21, "npc", "Не говорите, что я сказал.", -2, -1, None, None, None),
            (30, "npc", "Немец. Но ночи у него русские. И голодные.", -4, -1, None, "spoke_panteleimon", None),
            (40, "npc", "Тогда вам сюда и дорога. Вина здесь не лечится — её кормят.", -4, -1, None, "spoke_panteleimon", None),
            (13, "player", "Ключ от палат носите на поясе, не в кармане?", 0, 50, 1, None, None, "class_seeker"),
            (14, "player", "За вашей спиной молятся голосом не из горла.", -3, 51, 1, None, None, "class_mystic"),
            (15, "player", "Отдайте ключи. Не просите дважды.", 0, 52, 1, None, None, "class_rebel"),
            (50, "npc", "Царапины у скважины — не мои. Пояс — да. Не говорите.", 0, -1, None, "spoke_panteleimon", None),
            (51, "npc", "Не слушайте. Кто отвечает — того несут вниз.", -4, -1, None, "spoke_panteleimon", None),
            (52, "npc", "Плечо дверь знает. Ключ — тише. Берите от палат, если уже не боитесь шума.", -2, -1, None, "spoke_panteleimon", None),
        ],
    )
    lines += rows(
        "dialogue_panteleimon_repeat",
        [
            (1, "npc", "Я ничего не говорил. Слышите? Ничего.", 0, 10, None, None, None),
            (10, "player", "Ключи. Ещё раз.", 0, 20, 1, None, None),
            (11, "player", "Тени в столовой — ваши?", 0, 30, 1, None, None),
            (12, "player", "(признаться) Я виноват.", -6, 40, 1, "guilt_admitted", None),
            (13, "player", "Замок орёт до сих пор.", 0, 50, 1, None, None, "broke_door"),
            (20, "npc", "Палаты — у меня. Кабинет — ищите. Подвал — у немца. Это уже слишком много.", -2, -1, None, None, None),
            (30, "npc", "Не мои. Мои носят вниз. Те приходят сами, когда смотришь слишком долго.", -3, -1, None, None, None),
            (40, "npc", "Тогда вам сюда. Вину здесь не моют — её ставят на учёт.", -3, -1, None, None, None),
            (50, "npc", "Это были вы. Ключи после такого прячут. Немец не спит.", -2, -1, None, None, None),
        ],
    )

    conn.executemany(
        """INSERT INTO dialogue_lines
           (dialogue_id, order_num, speaker, text, sanity_change, next_order,
            choice_group, sets_flag, ending_id, requires_flag)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        lines,
    )


def _seed_double(conn) -> None:
    """Двойник — живой NPC, не случайный глиф на экране."""
    conn.execute(
        """INSERT INTO characters
           (id, type, name, title, description, hp, armor_class, attack_bonus,
            damage_die, str, dex, con, "int", cha, ai_behavior, sanity_damage,
            faction, symbol, color, dialogue_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             name = excluded.name,
             title = excluded.title,
             description = excluded.description,
             symbol = excluded.symbol,
             color = excluded.color,
             dialogue_id = excluded.dialogue_id,
             type = excluded.type,
             ai_behavior = excluded.ai_behavior,
             faction = excluded.faction""",
        (
            "player_double",
            "npc",
            "Незнакомец",
            "В вашем халате",
            "Стоит слишком прямо. Лицо — как мокрое пятно на стекле.",
            10,
            10,
            0,
            "1d4",
            10,
            10,
            10,
            10,
            14,
            "dialogue",
            0,
            "self",
            "&",
            "#c8c8d2",
            "dialogue_double_intro",
        ),
    )
    for dialogue_id in ("dialogue_double_intro", "dialogue_double_repeat"):
        conn.execute("DELETE FROM dialogue_lines WHERE dialogue_id = ?", (dialogue_id,))
        conn.execute("DELETE FROM dialogues WHERE id = ?", (dialogue_id,))
    conn.executemany(
        "INSERT INTO dialogues (id, character_id, trigger_condition) VALUES (?, ?, NULL)",
        [
            ("dialogue_double_intro", "player_double"),
            ("dialogue_double_repeat", "player_double"),
        ],
    )
    conn.executemany(
        """INSERT INTO dialogue_lines
           (dialogue_id, order_num, speaker, text, sanity_change, next_order,
            choice_group, sets_flag, ending_id, requires_flag)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (*row, None) if len(row) == 9 else row
            for row in [
            ("dialogue_double_intro", 1, "npc",
             "Вы пришли. Я ждал — или это вы ждали меня?", 0, 10, None, None, None),
            ("dialogue_double_intro", 10, "player", "Кто вы?", 0, 20, 1, None, None),
            ("dialogue_double_intro", 11, "player", "Вас нет.", -2, 30, 1, None, None),
            ("dialogue_double_intro", 12, "player", "Простите меня.", -10, 40, 1,
             "guilt_admitted", None),
            ("dialogue_double_intro", 20, "npc",
             "Я — то, что вы оставили в канале. Имя. Лицо. Долг.", -6, -1, None,
             "spoke_double", None),
            ("dialogue_double_intro", 30, "npc",
             "Нет. Есть. Разница вам уже не принадлежит.", -4, -1, None,
             "spoke_double", None),
            ("dialogue_double_intro", 40, "npc",
             "Поздно. Но спасибо, что сказали. Туман это слышит.", -8, -1, None,
             "spoke_double", None),
            ("dialogue_double_intro", 13, "player",
             "На халате тот же шов, что у меня. Откуда?", -2, 50, 1, None, None, "class_seeker"),
            ("dialogue_double_intro", 14, "player",
             "Вы дышите раньше меня. Зачем?", -4, 51, 1, None, None, "class_mystic"),
            ("dialogue_double_intro", 15, "player",
             "Если ты я — отойди. Места мало.", 0, 52, 1, None, None, "class_rebel"),
            ("dialogue_double_intro", 50, "npc",
             "Шов ваш. Нить — нет. Её тянули из канала.", -3, -1, None, "spoke_double", None),
            ("dialogue_double_intro", 51, "npc",
             "Чтобы вы опоздали на свою жизнь. Это уже случилось.", -5, -1, None, "spoke_double", None),
            ("dialogue_double_intro", 52, "npc",
             "Отойду. В зеркале тесно всё равно.", -2, -1, None, "spoke_double", None),
            ("dialogue_double_repeat", 1, "npc",
             "Вы вернулись. Или это я не уходил.", 0, 10, None, None, None),
            ("dialogue_double_repeat", 10, "player", "Что ты взял у меня?", -2, 20, 1, None, None),
            ("dialogue_double_repeat", 11, "player", "Исчезни.", 0, 30, 1, None, None),
            ("dialogue_double_repeat", 12, "player", "Прости. Ещё раз.", -8, 40, 1,
             "guilt_admitted", None),
            ("dialogue_double_repeat", 20, "npc",
             "Имя. Отражение. То место в канале, куда вы не смотрите.", -4, -1, None, None, None),
            ("dialogue_double_repeat", 30, "npc",
             "Исчезну. В зеркале. Тогда вы останетесь один — и это хуже.", -3, -1, None, None, None),
            ("dialogue_double_repeat", 40, "npc",
             "Слышу. Туман тоже. Идите, пока нас двое, а не одно.", -6, -1, None, None, None),
            ]
        ],
    )


def _upsert_npc(conn, row) -> None:
    conn.execute(
        """INSERT INTO characters
           (id, type, name, title, description, hp, armor_class, attack_bonus,
            damage_die, str, dex, con, "int", cha, ai_behavior, sanity_damage,
            faction, symbol, color, dialogue_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             name = excluded.name,
             title = excluded.title,
             description = excluded.description,
             symbol = excluded.symbol,
             dialogue_id = excluded.dialogue_id,
             type = excluded.type,
             ai_behavior = excluded.ai_behavior""",
        row,
    )


def _pad_dialogue_line(line):
    """8 полей контента или 9 с requires_flag."""
    if len(line) == 8:
        return (*line, None)
    return line


def _seed_city_dialogue(conn, dialogue_id, character_id, repeat_id, intro_lines, repeat_lines) -> None:
    for did in (dialogue_id, repeat_id):
        conn.execute("DELETE FROM dialogue_lines WHERE dialogue_id = ?", (did,))
        conn.execute("DELETE FROM dialogues WHERE id = ?", (did,))
    conn.executemany(
        "INSERT INTO dialogues (id, character_id, trigger_condition) VALUES (?, ?, NULL)",
        [(dialogue_id, character_id), (repeat_id, character_id)],
    )
    rows = [(dialogue_id, *_pad_dialogue_line(line)) for line in intro_lines]
    if isinstance(repeat_lines, str):
        repeat_lines = [(1, "npc", repeat_lines, 0, -1, None, None, None)]
    rows += [(repeat_id, *_pad_dialogue_line(line)) for line in repeat_lines]
    conn.executemany(
        """INSERT INTO dialogue_lines
           (dialogue_id, order_num, speaker, text, sanity_change, next_order,
            choice_group, sets_flag, ending_id, requires_flag)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )


def _apply_phase3(conn) -> None:
    """Петербург за воротами и этаж бреда."""
    conn.executemany(
        """INSERT INTO maps (id, name, description, file_path, width, height,
                             min_sanity, max_sanity, is_starting_map)
           VALUES (?, ?, ?, ?, ?, ?, 0, 100, 0)
           ON CONFLICT(id) DO UPDATE SET
             name = excluded.name,
             description = excluded.description,
             file_path = excluded.file_path,
             width = excluded.width,
             height = excluded.height""",
        [
            (
                "street_traktir",
                "Трактир «У канала»",
                "Жар, дешёвый табак, самовар. Здесь ещё называют по имени.",
                "data/maps/traktir.txt",
                36,
                14,
            ),
            (
                "hospital_bred",
                "Коридор, которого нет",
                "План здания не совпадает с шагами. Лестница вела сюда — или вы сами.",
                "data/maps/floor_1.txt",
                57,
                20,
            ),
        ],
    )

    conn.executemany(
        """DELETE FROM map_connections
           WHERE source_map_id = ? AND source_x = ? AND source_y = ?""",
        [
            ("street_outside", 0, 10),
            ("street_outside", 26, 6),
            ("street_traktir", 0, 7),
            ("street_traktir", 0, 8),
        ],
    )
    conn.executemany(
        """INSERT INTO map_connections
           (source_map_id, connection_type, source_x, source_y,
            target_map_id, target_x, target_y, description)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            ("street_outside", "entrance", 0, 10, "hospital_floor_1", 55, 9,
             "Вернуться в клинику"),
            ("street_outside", "entrance", 26, 6, "street_traktir", 1, 7,
             "Войти в трактир"),
            ("street_traktir", "exit", 0, 7, "street_outside", 26, 7,
             "Выйти на набережную"),
            ("street_traktir", "exit", 0, 8, "street_outside", 26, 7,
             "Выйти на набережную"),
        ],
    )

    conn.executemany(
        """INSERT INTO map_regions
           (id, map_id, x1, y1, x2, y2, name, first_visit_text, sanity_effect)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             first_visit_text = excluded.first_visit_text,
             x1 = excluded.x1, y1 = excluded.y1, x2 = excluded.x2, y2 = excluded.y2""",
        [
            ("st_tavern", "street_outside", 18, 1, 34, 6, "Трактир",
             "Вывеска «У канала». Буквы кривые, как после удара.", 0),
            ("tav_room", "street_traktir", 1, 1, 34, 12, "Зал",
             "Самовар шумит, будто держит речь. Здесь ещё пьют за живых.", -1),
            ("bred_hall", "hospital_bred", 1, 8, 55, 11, "Чужой коридор",
             "Лампа горит вчерашним светом. Шаги ваши уже прошли здесь без вас.", -8),
        ],
    )

    conn.execute(
        """INSERT INTO items
           (id, type, name, description, damage_die, healing, sanity_restore,
            sanity_damage, symbol, color, is_quest_item, use_effect, content)
           VALUES (?, 'note', ?, ?, '', 0, 0, -4, '≈', '#c8b48c', 1, 'read_note', ?)
           ON CONFLICT(id) DO UPDATE SET content = excluded.content""",
        (
            "note_canal",
            "Записка с набережной",
            "Мокрый клочок. Чернила расползлись к каналу.",
            "Имени нет — есть долг. Кто вспомнит, того туман пропустит.",
        ),
    )

    conn.executemany(
        """INSERT INTO map_placements (map_id, x, y, spawn_type, spawn_id)
           VALUES (?, ?, ?, ?, ?)""",
        [
            ("street_outside", 8, 12, "character", "watchman_petrov"),
            ("street_outside", 47, 10, "character", "sennaya_beggar"),
            ("street_outside", 15, 16, "item", "note_canal"),
            ("street_traktir", 10, 5, "character", "innkeeper_semyon"),
            ("hospital_bred", 22, 10, "character", "shadow_enemy"),
            ("hospital_bred", 16, 10, "item", "note_canal"),
        ],
    )

    _upsert_npc(conn, (
        "innkeeper_semyon", "npc", "Семён", "Трактирщик",
        "Щёки красные, глаза нет. Полотенце на плече как епитрахиль.",
        8, 10, 0, "1d4", 10, 10, 12, 10, 12, "dialogue", 0, "city",
        "&", "#d2b48c", "dialogue_innkeeper_intro",
    ))
    _upsert_npc(conn, (
        "watchman_petrov", "npc", "Петров", "Городовой",
        "Шинель в снегу, которого нет. Свисток молчит.",
        12, 12, 1, "1d6", 12, 10, 12, 8, 8, "dialogue", 0, "city",
        "&", "#8899aa", "dialogue_watchman_intro",
    ))
    _upsert_npc(conn, (
        "sennaya_beggar", "npc", "Нищий", "На Сенной",
        "Лица не разобрать. Рука протянута не за медью.",
        6, 8, 0, "1d4", 8, 8, 8, 10, 14, "dialogue", 0, "city",
        "&", "#a09080", "dialogue_beggar_intro",
    ))

    _seed_city_dialogue(
        conn,
        "dialogue_innkeeper_intro",
        "innkeeper_semyon",
        "dialogue_innkeeper_repeat",
        [
            (1, "npc", "Клиника? Ночью оттуда возвращаются без лиц. Садитесь — или идите.", 0, 10, None, None, None),
            (10, "player", "Кто я?", -4, 20, 1, None, None),
            (11, "player", "Налейте. Хочу не помнить.", -6, 30, 1, None, None),
            (12, "player", "Мне нужна улица, не стакан.", 0, 40, 1, None, None),
            (13, "player", "На пороге грязь с двух каблуков. Откуда второй?", 0, 50, 1, None, None, "class_seeker"),
            (14, "player", "Самовар поёт не ту ноту. Чьё имя в ней?", -3, 51, 1, None, None, "class_mystic"),
            (15, "player", "Дверь не запирается. Значит, запирают людей.", 0, 52, 1, None, None, "class_rebel"),
            (20, "npc", "Кто — не скажу. Но имя у вас было громче этого самовара.", -3, -1, None, "spoke_innkeeper", None),
            (30, "npc", "Пейте. Забвение здесь дешевле правды — и туже держит.", -5, -1, None, "spoke_innkeeper", None),
            (40, "npc", "Тогда на Сенную. Там ещё просят имена — и иногда отдают.", 0, -1, None, "spoke_innkeeper", None),
            (50, "npc", "Один каблук — клиники, второй — Сенной. Вы уже ходили и не помните.", -2, -1, None, "spoke_innkeeper", None),
            (51, "npc", "Имя, которое вы бросили. Самовар честнее зеркал.", -4, -1, None, "spoke_innkeeper", None),
            (52, "npc", "Верно. Пейте или идите. Запирать будем не дверь.", 0, -1, None, "spoke_innkeeper", None),
        ],
        [
            (1, "npc", "Стакан ещё тёплый. Правда — нет.", 0, 10, None, None, None),
            (10, "player", "Куда идти, если не пить?", 0, 20, 1, None, None),
            (11, "player", "Налейте. Пусть будет тише.", -4, 30, 1, None, None),
            (12, "player", "Клиника зовёт обратно.", 0, 40, 1, None, None),
            (20, "npc", "На Сенную. Там имя дороже водки — и его ещё отдают.", 0, -1, None, None, None),
            (30, "npc", "Тише станет. Вы — нет. Пейте, пока самовар помнит вас живым.", -3, -1, None, None, None),
            (40, "npc", "Она всегда зовёт. Кто возвращается — тот уже номер.", -2, -1, None, None, None),
        ],
    )
    _seed_city_dialogue(
        conn,
        "dialogue_watchman_intro",
        "watchman_petrov",
        "dialogue_watchman_repeat",
        [
            (1, "npc", "Документы. Или ступайте обратно, в номер.", 0, 10, None, None, None),
            (10, "player", "Я болен. Меня выпустили.", 0, 20, 1, None, None),
            (11, "player", "(признаться) Документов нет. И имени — тоже.", -6, 30, 1, "guilt_admitted", None),
            (12, "player", "Не загораживайте.", 0, 40, 1, None, None),
            (13, "player", "Шинель в снегу, которого нет. Откуда вы?", 0, 50, 1, None, None, "class_seeker"),
            (14, "player", "Свисток молчит. Его кто-то держит за горло.", -2, 51, 1, None, None, "class_mystic"),
            (15, "player", "Уберите руку. Не просите дважды.", 0, 52, 1, None, None, "class_rebel"),
            (20, "npc", "Больных не выпускают. Беглецов — тоже. Выберите, кем быть.", -2, -1, None, "spoke_watchman", None),
            (30, "npc", "Честно. Туман любит честных — или съедает. Ступайте к нищему.", -4, -1, None, "spoke_watchman", None),
            (40, "npc", "Смелости у вас больше, чем права. Не попадайтесь второй раз.", 0, -1, None, "spoke_watchman", None),
            (50, "npc", "Снег был. Потом клиника. Потом я здесь без права уйти.", -2, -1, None, "spoke_watchman", None),
            (51, "npc", "Не свищу. Кто свистит ночью — тот уже не городовой.", -3, -1, None, "spoke_watchman", None),
            (52, "npc", "Идите. Плечо ваше я запомню.", 0, -1, None, "spoke_watchman", None),
        ],
        [
            (1, "npc", "Всё те же карманы. Всё те же пустые.", 0, 10, None, None, None),
            (10, "player", "Пропустите к каналу.", 0, 20, 1, None, None),
            (11, "player", "(признаться) Я бежал. И виноват.", -5, 30, 1, "guilt_admitted", None),
            (12, "player", "Где Сенная?", 0, 40, 1, None, None),
            (20, "npc", "Канал никого не пропускает. Он принимает.", -2, -1, None, None, None),
            (30, "npc", "Тогда к нищему. Туман слушает тех, кто не врёт свистку.", -3, -1, None, None, None),
            (40, "npc", "На восток, в вату. Без имени не ходите — фонари врут.", 0, -1, None, None, None),
        ],
    )
    _seed_city_dialogue(
        conn,
        "dialogue_beggar_intro",
        "sennaya_beggar",
        "dialogue_beggar_repeat",
        [
            (1, "npc", "Имя, барин. Без имени туман — стена.", 0, 10, None, None, None),
            (10, "player", "Я не помню.", -2, 20, 1, None, None),
            (11, "player", "(назвать чужое) Иван.", 0, 30, 1, None, None),
            (12, "player", "(отдать своё, какое есть)", -8, 40, 1, "sennaya_name", None),
            (13, "player", "На ладони след печати. Чья?", 0, 50, 1, None, None, "class_seeker"),
            (14, "player", "Туман зовёт уменьшительным. Не берите.", -4, 51, 1, None, None, "class_mystic"),
            (15, "player", "Имя не милостыня. Отойдите.", 0, 52, 1, None, None, "class_rebel"),
            (20, "npc", "Тогда стойте. Стена сытая.", -3, -1, None, "spoke_beggar", None),
            (30, "npc", "Иванов здесь полно. Туман их не считает.", -2, -1, None, "spoke_beggar", None),
            (40, "npc", "Взял. Идите. Мостовая впереди уже не клиника.", -6, -1, None, "spoke_beggar", None),
            (50, "npc", "Академии. Или клиники. Печать одна — руки разные.", -2, -1, None, "spoke_beggar", None),
            (51, "npc", "Правильно. Кто отзовётся — останется здесь без мостовой.", -5, -1, None, "spoke_beggar", None),
            (52, "npc", "Тогда стойте в вате. Стена любит гордых.", 0, -1, None, "spoke_beggar", None),
        ],
        [
            (1, "npc", "Имя взял. Долг слышал. Мостовая ваша.", 0, 10, None, None, None, "has_both"),
            (2, "npc", "Имя есть. Стена ещё хочет, кому вы должны.", 0, 10, None, None, None, "has_name"),
            (3, "npc", "Вы должны — и безымянны. Стена сытая.", 0, 10, None, None, None, "has_debt"),
            (4, "npc", "Ещё раз. Имя или стена.", 0, 10, None, None, None),
            (10, "player", "Я всё так же не помню.", -2, 20, 1, None, None),
            (11, "player", "(отдать то, что есть)", -6, 30, 1, "sennaya_name", None),
            (12, "player", "Я уже отдал.", 0, 40, 1, None, None),
            (13, "player", "Имя ваше. Долг — нет?", 0, 50, 1, None, None, "has_name"),
            (14, "player", "Я должен. Этого мало?", 0, 51, 1, None, None, "has_debt"),
            (20, "npc", "Тогда стойте. Стена терпеливая.", -2, -1, None, None, None),
            (30, "npc", "Теперь идите — если есть, кому должны. Мостовая впереди уже не клиника.", -4, -1, None, None, None),
            (40, "npc", "Тогда зачем пришли? Туман не любит повторных подаяний.", 0, -1, None, None, None),
            (50, "npc", "Мало. Стена слушает два слова. Вы сказали одно.", 0, -1, None, None, None),
            (51, "npc", "Долг без имени — милостыня пустая. Назовите себя.", 0, -1, None, None, None),
        ],
    )


def _apply_phase4(conn) -> None:
    """Архив второго этажа: человек, дело, имя для тумана."""
    conn.execute(
        """INSERT INTO items
           (id, type, name, description, damage_die, healing, sanity_restore,
            sanity_damage, symbol, color, is_quest_item, use_effect, content)
           VALUES (?, 'note', ?, ?, '', 0, 0, -3, '≈', '#c8b48c', 1, 'read_note', ?)
           ON CONFLICT(id) DO UPDATE SET content = excluded.content,
             name = excluded.name, description = excluded.description""",
        (
            "note_case",
            "Дело без обложки",
            "Папка, у которой отодрали картон вместе с фамилией.",
            "Пациент N. Пробуждение без имени. Рекомендация: не выпускать "
            "на Сенную, пока не подпишет себя сам.",
        ),
    )
    _upsert_npc(conn, (
        "archivist_klara", "npc", "Клара", "Архивариус",
        "Перья в волосах, как в чернильнице. Смотрит сквозь вас в карточку.",
        8, 10, 0, "1d4", 8, 10, 10, 14, 10, "dialogue", 0, "clinic",
        "&", "#b8a090", "dialogue_archivist_intro",
    ))
    _seed_city_dialogue(
        conn,
        "dialogue_archivist_intro",
        "archivist_klara",
        "dialogue_archivist_repeat",
        [
            (1, "npc", "Картотека не спит. Вы — номер или имя?", 0, 10, None, None, None),
            (10, "player", "Ищу свою историю.", 0, 20, 1, None, None),
            (11, "player", "Чьи это папки?", -2, 30, 1, None, None),
            (12, "player", "(назвать себя, как получится)", -6, 40, 1, "archive_name", None),
            (13, "player", "На корешке свежая дата и нет фамилии. Это я?", 0, 50, 1, None, None, "class_seeker"),
            (14, "player", "Папка зовёт уменьшительным. Не открывайте.", -3, 51, 1, None, None, "class_mystic"),
            (15, "player", "Шкаф не заперт. Отдайте моё дело.", 0, 52, 1, None, None, "class_rebel"),
            (20, "npc", "История здесь чужая. Свою прячут в кабинете, под ковром.",
             -2, -1, None, "spoke_archivist", None),
            (30, "npc", "Больных. Врачей. И тех, кого выписали в канал.",
             -4, -1, None, "spoke_archivist", None),
            (40, "npc", "Записала. Туман любит бумагу больше лиц.",
             -5, -1, None, "spoke_archivist", None),
            (50, "npc", "Дата ваша. Фамилию отодрали вместе с обложкой. Подпишите — или останетесь номером.",
             0, -1, None, "spoke_archivist", None),
            (51, "npc", "Правильно. Кто откроет — услышит себя с той стороны картона.",
             -4, -1, None, "spoke_archivist", None),
            (52, "npc", "Не заперт, потому что запирают не бумаги. Дело — на столе. Имя — ваше.",
             0, -1, None, "spoke_archivist", None),
        ],
        [
            (1, "npc", "Карточка полная. И долг на полях. Идите.", 0, 10, None, None, None, "has_both"),
            (2, "npc", "Имя в чернилах. Долг — нет. Туман читает оба листа.", 0, 10, None, None, None, "has_name"),
            (3, "npc", "Вина есть. Подписи нет. Номер не выпускают.", 0, 10, None, None, None, "has_debt"),
            (4, "npc", "Карточка открыта. Чернила не высохли.", 0, 10, None, None, None),
            (10, "player", "Где кабинет Шпилькина?", 0, 20, 1, None, None),
            (11, "player", "(подписать себя)", -5, 30, 1, "archive_name", None),
            (12, "player", "Закройте дело.", 0, 40, 1, None, None),
            (13, "player", "Я уже в карточке. Пустите.", 0, 50, 1, None, None, "has_name"),
            (14, "player", "Я должен. Этого хватит?", 0, 51, 1, None, None, "has_debt"),
            (15, "player", "Дата на бюро — моя рука.", 0, 52, 1, None, None, "seeker_trace"),
            (20, "npc", "За запертой дверью. Ключ у него. Под ковром — то, чего нет в картотеке.",
             0, -1, None, None, None),
            (30, "npc", "Есть. Туман это любит больше лиц — если рядом долг.", -4, -1, None, None, None),
            (40, "npc", "Дело без имени не закрывается. Оно ждёт, пока вы совпадёте с бумагой.",
             -2, -1, None, None, None),
            (50, "npc", "Подпись есть. Долг — на другом листе. Туман читает оба.", 0, -1, None, None, None),
            (51, "npc", "Вина без подписи — номер. Назовите себя.", -2, -1, None, None, None),
            (52, "npc", "Видела дату. Это не имя, но след. Клара не врёт картотеке.", 0, -1, None, None, None),
        ],
    )


def _apply_phase5(conn) -> None:
    """Классовый голос в диалоге и речь одержимого. Бой по-прежнему от шага на него."""
    conn.execute(
        """UPDATE characters
           SET dialogue_id = 'dialogue_possessed_intro'
           WHERE id = 'possessed_patient'"""
    )
    _seed_city_dialogue(
        conn,
        "dialogue_possessed_intro",
        "possessed_patient",
        "dialogue_possessed_repeat",
        [
            (1, "npc", "Не подходите. Он ещё здесь. Я — уже нет.", 0, 10, None, None, None),
            (10, "player", "Кто он?", 0, 20, 1, None, None),
            (11, "player", "Вас лечат?", -2, 30, 1, None, None),
            (12, "player", "Отойдите.", 0, 40, 1, None, None),
            (13, "player", "На запястье след верёвки. Кто вязал?", 0, 50, 1, None, None, "class_seeker"),
            (14, "player", "В вас молятся не вашим ртом.", -4, 51, 1, None, None, "class_mystic"),
            (15, "player", "Если он в вас — выйдем оба.", 0, 52, 1, None, None, "class_rebel"),
            (20, "npc", "Доктор. Ночь. То, что остаётся, когда имя снимают как халат.",
             -3, -1, None, "spoke_possessed", None),
            (30, "npc", "Лечат того, кого нет. Меня кормят. Разница — в меню.",
             -4, -1, None, "spoke_possessed", None),
            (40, "npc", "Отойду. Он — нет. Шаг на меня будет шагом на него.",
             0, -1, None, "spoke_possessed", None),
            (50, "npc", "Смотритель. Или вы. Верёвка не помнит рук.",
             -2, -1, None, "spoke_possessed", None),
            (51, "npc", "Не отвечайте. Кто отвечает — остаётся вместо меня.",
             -5, -1, None, "spoke_possessed", None),
            (52, "npc", "Плечо не выгоняет беса. Бес любит шум. Идите, пока я ещё прошу.",
             -2, -1, None, "spoke_possessed", None),
        ],
        [
            (1, "npc", "Он ближе. Говорите тише.", 0, 10, None, None, None),
            (10, "player", "Как вас звали?", 0, 20, 1, None, None),
            (11, "player", "Я уйду.", 0, 30, 1, None, None),
            (12, "player", "Держитесь.", -2, 40, 1, None, None),
            (20, "npc", "Как вас. Почти. Не произносите.", -3, -1, None, None, None),
            (30, "npc", "Идите. Шаг на клетку — уже не разговор.", 0, -1, None, None, None),
            (40, "npc", "Держусь чужим зубом. Это не милость.", -2, -1, None, None, None),
        ],
    )


def _apply_phase6(conn) -> None:
    """Живые одноразовые триггеры на проходимых клетках; квест без счёта лута."""
    for column, spec in (
        ("map_id", "TEXT"),
        ("x", "INTEGER"),
        ("y", "INTEGER"),
    ):
        _ensure_column(conn, "triggers", column, spec)

    conn.execute("DELETE FROM triggers")
    rows = [
        (
            "trigger_whisper",
            "hospital_floor_1",
            12,
            9,
            "Шёпот за лампой. Не ваш. И не живой.",
            -2,
        ),
        (
            "trigger_cafe",
            "hospital_floor_1",
            48,
            5,
            "Стул ждёт того, кого уже увели. Рядом ещё один — занят.",
            -2,
        ),
        (
            "trigger_archive",
            "hospital_floor_2",
            6,
            4,
            "Папка без корешка. Дата — сегодняшняя. Имени нет.",
            -2,
        ),
        (
            "trigger_cell",
            "hospital_basement",
            10,
            8,
            "За дверью камеры скребут ногтем. Ногтя нет.",
            -3,
        ),
        (
            "trigger_canal",
            "street_outside",
            10,
            15,
            "Канал чёрный. Отражения нет — или оно смотрит с другой стороны.",
            -2,
        ),
        (
            "trigger_fog",
            "street_outside",
            48,
            10,
            "Туман густеет без имени. Дальше — только если есть, что сказать.",
            -1,
        ),
    ]
    conn.executemany(
        """INSERT INTO triggers
           (id, type, target_id, text, sanity_change,
            spawn_character_id, spawn_item_id, damage, heal, map_id, x, y)
           VALUES (?, 'on_enter', ?, ?, ?, NULL, NULL, 0, 0, ?, ?, ?)""",
        [
            (tid, f"{map_id}:{x},{y}", text, san, map_id, x, y)
            for tid, map_id, x, y, text, san in rows
        ],
    )

    conn.execute(
        """UPDATE quests
           SET title = ?, description = ?
           WHERE id = 'find_notes'""",
        (
            "Имя или долг",
            "Бумаги помогают вспомнить. Туман слушает имя, не счёт листков.",
        ),
    )


def _apply_phase7(conn) -> None:
    """Кабинет 2-го этажа: черновик на полу. Письмо — показание. Карту не двигаем."""
    conn.execute("DELETE FROM triggers WHERE id = 'trigger_study'")
    conn.execute(
        """INSERT INTO triggers
           (id, type, target_id, text, sanity_change,
            spawn_character_id, spawn_item_id, damage, heal, map_id, x, y)
           VALUES (?, 'on_enter', ?, ?, ?, NULL, NULL, 0, 0, ?, ?, ?)""",
        (
            "trigger_study",
            "hospital_floor_2:8,15",
            "Под ковром щель. В ней клочок: «Не имя. Номер. Так спокойнее.»",
            -2,
            "hospital_floor_2",
            8,
            15,
        ),
    )
    conn.execute(
        """UPDATE items SET content = ? WHERE id = 'letter_1'""",
        (
            "Уважаемый доктор фон Шпилькин! Новые препараты высланы. "
            "Результаты — к концу месяца. Не подведите нас. "
            "На полях его рука: «Пациент вспоминает. Нельзя.»",
        ),
    )


def _apply_phase10(conn) -> None:
    """Имя и долг — две правды. Туман слушает оба."""
    conn.execute(
        """UPDATE quests
           SET title = ?, description = ?
           WHERE id = 'find_notes'""",
        (
            "Имя и долг",
            "Туман на востоке слышит только оба: кем были и кому должны.",
        ),
    )
    conn.execute(
        """UPDATE triggers SET text = ?
           WHERE id = 'trigger_fog'""",
        (
            "Туман густеет. Дальше — только если есть имя и долг, не одно из двух.",
        ),
    )

