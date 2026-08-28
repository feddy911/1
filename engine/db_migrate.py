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

    # order_num, speaker, text, san, next, group, sets_flag, ending
    def rows(dialogue_id, entries):
        out = []
        for entry in entries:
            (
                order_num,
                speaker,
                text,
                san,
                next_order,
                group,
                sets_flag,
                ending,
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
        ],
    )
    lines += rows(
        "dialogue_shpilkin_repeat",
        [
            (1, "npc", "Идите. Коридоры длиннее, чем кажутся.", 0, -1, None, None, None),
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
        ],
    )
    lines += rows(
        "dialogue_nastasya_repeat",
        [
            (1, "npc", "Не слушайте, если назовут по имени.", 0, -1, None, None, None),
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
        ],
    )
    lines += rows(
        "dialogue_panteleimon_repeat",
        [
            (1, "npc", "Я ничего не говорил.", 0, -1, None, None, None),
        ],
    )

    conn.executemany(
        """INSERT INTO dialogue_lines
           (dialogue_id, order_num, speaker, text, sanity_change, next_order,
            choice_group, sets_flag, ending_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            choice_group, sets_flag, ending_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
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
            ("dialogue_double_repeat", 1, "npc",
             "Мы ещё встретимся. В зеркале — или на дне.", 0, -1, None, None, None),
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


def _seed_city_dialogue(conn, dialogue_id, character_id, repeat_id, intro_lines, repeat_text) -> None:
    for did in (dialogue_id, repeat_id):
        conn.execute("DELETE FROM dialogue_lines WHERE dialogue_id = ?", (did,))
        conn.execute("DELETE FROM dialogues WHERE id = ?", (did,))
    conn.executemany(
        "INSERT INTO dialogues (id, character_id, trigger_condition) VALUES (?, ?, NULL)",
        [(dialogue_id, character_id), (repeat_id, character_id)],
    )
    rows = [(dialogue_id, *line) for line in intro_lines]
    rows.append((repeat_id, 1, "npc", repeat_text, 0, -1, None, None, None))
    conn.executemany(
        """INSERT INTO dialogue_lines
           (dialogue_id, order_num, speaker, text, sanity_change, next_order,
            choice_group, sets_flag, ending_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            (20, "npc", "Кто — не скажу. Но имя у вас было громче этого самовара.", -3, -1, None, "spoke_innkeeper", None),
            (30, "npc", "Пейте. Забвение здесь дешевле правды — и туже держит.", -5, -1, None, "spoke_innkeeper", None),
            (40, "npc", "Тогда на Сенную. Там ещё просят имена — и иногда отдают.", 0, -1, None, "spoke_innkeeper", None),
        ],
        "Самовар не кончится. Вы — можете.",
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
            (20, "npc", "Больных не выпускают. Беглецов — тоже. Выберите, кем быть.", -2, -1, None, "spoke_watchman", None),
            (30, "npc", "Честно. Туман любит честных — или съедает. Ступайте к нищему.", -4, -1, None, "spoke_watchman", None),
            (40, "npc", "Смелости у вас больше, чем права. Не попадайтесь второй раз.", 0, -1, None, "spoke_watchman", None),
        ],
        "Я вас не видел.",
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
            (20, "npc", "Тогда стойте. Стена сытая.", -3, -1, None, "spoke_beggar", None),
            (30, "npc", "Иванов здесь полно. Туман их не считает.", -2, -1, None, "spoke_beggar", None),
            (40, "npc", "Взял. Идите. Мостовая впереди уже не клиника.", -6, -1, None, "spoke_beggar", None),
        ],
        "Имя уже не ваше. Идите, пока помнит мостовая.",
    )

