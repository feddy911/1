"""Идемпотентные правки схемы и данных фазы 0."""
import json
from typing import List, Tuple

from engine.palette import INKS, TILE_INKS, iter_explored_colors, iter_tile_colors


PLACEMENTS: List[Tuple[str, int, int, str, str]] = [
    ("hospital_floor_1", 24, 6, "character", "patient_nastasya"),
    ("hospital_floor_1", 30, 2, "character", "sanitary_panteleimon"),
    ("hospital_floor_1", 5, 6, "character", "doctor_shpilkin"),
    ("hospital_floor_1", 36, 6, "character", "possessed_patient"),
    ("hospital_basement", 28, 2, "character", "shadow_enemy"),
    ("hospital_basement", 44, 2, "character", "shadow_enemy"),
]


TILE_COLORS = iter_tile_colors()
TILE_COLORS_EXPLORED = iter_explored_colors()

TILE_TRANSPARENCY = [
    ("#", 1, "Стена"),
    (" ", 1, "Пустота"),
    ("d", 1, "Запертая дверь"),
    ("H", 1, "Шкаф"),
    ("O", 1, "Письменный стол"),
    (".", 0, "Пол"),
    ("'", 0, "Открытая дверь"),
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
    ('"', 1, "Картина"),
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
               color = ?,
               radius = 5,
               intensity = 0.7,
               flicker = 0
           WHERE id = 'window'""",
        (INKS["frost"],),
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
           SET symbol = '&', color = ?
           WHERE id = 'shadow_enemy'""",
        (INKS["ice"],),
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
            ("hospital_floor_1", 12, 2, "key_warden"),
            ("hospital_floor_2", 37, 3, "key_doctor"),
            ("hospital_basement", 40, 3, "key_basement"),
        ],
    )

    conn.execute("DELETE FROM map_regions")
    conn.executemany(
        """INSERT INTO map_regions
           (id, map_id, x1, y1, x2, y2, name, first_visit_text, sanity_effect)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            ("f1_ward", "hospital_floor_1", 14, 4, 20, 7, "Палата",
             "Палата. Железо кровати холоднее пола. Окно одно — во двор. Во двор, не на волю.", 0),
            ("f1_hall", "hospital_floor_1", 13, 1, 55, 2, "Коридор",
             "Коридор вдоль улицы. Лампы есть, двора отсюда не видно. Не видно — и лучше не видеть.", -1),
            ("f1_office", "hospital_floor_1", 1, 1, 11, 7, "Кабинет",
             "Кабинет. Анфилада от коридора. Бумаги, пузырьки, чужой почерк. Почерк увереннее вашего.", 0),
            ("f1_cafe", "hospital_floor_1", 40, 4, 49, 7, "Столовая",
             "Столовая без еды. Стулья ждут тех, кого уже увели. Ждут кротко. Кротость их хуже голода.", -2),
            ("f1_stairs", "hospital_floor_1", 51, 4, 55, 7, "Лестница",
             "Лестничная клетка. Сырость снизу, одеколон сверху. Оба врут по-своему.", 0),
            ("f2_archive", "hospital_floor_2", 1, 1, 15, 7, "Архив",
             "Закрытое крыло. Полки с историями болезней — или чужими именами. Имена здесь дешевле болезней.", -2),
            ("f2_study", "hospital_floor_2", 32, 4, 48, 7, "Кабинет главврача",
             "Личный кабинет Шпилькина. Здесь письма не для академии. Академия таких писем стыдится.", -3),
            ("f2_hall", "hospital_floor_2", 17, 1, 55, 2, "Коридор второго этажа",
             "Тише, чем внизу. Тишина здесь платная. Кто не платит — того слышат.", 0),
            ("b_cells", "hospital_basement", 1, 1, 24, 7, "Камеры",
             "Камеры без табличек. Кто-то скреб ногтями по изнанке двери. Ногтя нет. Скрежета — полно.", -4),
            ("b_lab", "hospital_basement", 37, 4, 48, 7, "Лаборатория",
             "Лаборатория. На столе — следы мела и чего-то темнее мела. Темнее — и честнее.", -5),
            ("b_hall", "hospital_basement", 25, 1, 55, 7, "Подвал",
             "Подвал дышит вам в затылок. Свет не доходит до углов — углы доходят сами. Сами, без спроса.", -3),
            ("st_porch", "street_outside", 1, 7, 12, 13, "Крыльцо",
             "Ночь. Петербург. Туман липнет к лицу, как мокрый бинт. Бинт, впрочем, честнее тумана.", 0),
            ("st_embankment", "street_outside", 1, 14, 44, 15, "Набережная",
             "Канал чёрный, без отражений. Город есть — и города нет. Оба утверждения верны.", -2),
            ("st_fog", "street_outside", 45, 7, 58, 15, "Туман",
             "Дальше — вата и фонари, которые не обещают улицы. Не обещают — и не лгут.", 0),
        ],
    )

    conn.execute(
        """INSERT INTO items
           (id, type, name, description, damage_die, healing, sanity_restore,
            sanity_damage, symbol, color, is_quest_item, use_effect, content)
           VALUES (?, 'note', ?, ?, '', 0, 0, -5, '≈', ?, 1, 'read_note', ?)
           ON CONFLICT(id) DO UPDATE SET content = excluded.content""",
        (
            "letter_1",
            "Письмо из Петербурга",
            "Конверт с печатью академии.",
            INKS["paper"],
            "Уважаемый доктор фон Шпилькин! Новые препараты высланы. "
            "Результаты — к концу месяца. Не подведите нас.",
        ),
    )

    conn.execute(
        """UPDATE map_connections SET target_x = 54, target_y = 1
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
    _apply_phase11(conn)
    _apply_phase12(conn)
    _apply_phase13(conn)
    _apply_phase14(conn)
    _apply_phase15(conn)
    _apply_phase16(conn)
    _apply_palette(conn)
    _apply_map_links(conn)
    _apply_phase17(conn)
    _apply_phase18(conn)
    _apply_phase19(conn)
    _apply_phase20(conn)
    _apply_phase21(conn)
    _apply_phase22(conn)
    _apply_phase23(conn)
    _apply_phase24(conn)
    _apply_phase25(conn)
    _apply_phase26(conn)


PLACEMENTS_PHASE1: List[Tuple[str, int, int, str, str]] = [
    ("hospital_floor_1", 24, 6, "character", "patient_nastasya"),
    ("hospital_floor_1", 30, 2, "character", "sanitary_panteleimon"),
    ("hospital_floor_1", 5, 6, "character", "doctor_shpilkin"),
    ("hospital_floor_1", 36, 6, "character", "possessed_patient"),
    ("hospital_floor_2", 8, 6, "character", "archivist_klara"),
    ("hospital_basement", 28, 2, "character", "shadow_enemy"),
    ("hospital_basement", 44, 2, "character", "shadow_enemy"),
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
            (1, "npc", "А, проснулись. Это даже хорошо-с. Голова? Память? Или уже тени? Впрочем, не торопитесь: я и сам не всегда знаю, с кем говорю.", 0, 2, None, None, None),
            (2, "npc", "Ну-с, отвечайте. Или молчите. Молчание здесь тоже диагноз, и довольно честный.", 0, 10, None, None, None),
            (10, "player", "Где я? И кто вы такой, наконец?", 0, 20, 1, None, None),
            (11, "player", "Не подходите. Я не болен. Слышите? Не болен.", 0, 30, 1, "refuse_doctor", None),
            (12, "player", "Дайте микстуру. Хочу забыть. Даже это желание — забыть.", -5, 40, 1, "trust_doctor", None),
            (20, "npc", "Клиника, сударь. Я доктор фон Шпилькин. Здесь безопаснее, чем на улице... хотя безопасность у нас особого рода.", 0, 21, None, "spoke_shpilkin", None),
            (21, "npc", "Ночью коридоры врут, это уж как пить дать. Зеркалам не верьте. И мне не верьте, если стану слишком добр.", 0, -1, None, None, None),
            (30, "npc", "Не болен? Тогда капель не берите. Улица вас ещё не списала. Запишу отказ. Отказ тоже история.", 0, -1, None, "spoke_shpilkin", None),
            (31, "npc", "Все так говорят в первую ночь. Все. Потом просят капли. Страх — хороший признак: значит, ещё не тень.", -3, -1, None, "spoke_shpilkin", None),
            (40, "npc", "Хорошо. Ложитесь. Утром не будет ни клиники, ни вас. И это, поверьте, самое гуманное, что я умею.", -15, -1, None, "spoke_shpilkin", "stay"),
            (13, "player", "На чернильнице свежий почерк. Скажите, это моё дело?", 0, 50, 1, None, None, "class_seeker"),
            (14, "player", "В углу кто-то дышит в такт вам. Кто вы, доктор? Вы — или уже не вы?", -2, 51, 1, None, None, "class_mystic"),
            (15, "player", "Откройте дверь. Или открою я. Мне всё равно.", 0, 52, 1, None, None, "class_rebel"),
            (50, "npc", "Наблюдательный. Дело пока не ваше, увы. Читайте дневники, не зеркала. Зеркала здесь бессовестны.", 0, -1, None, "spoke_shpilkin", None),
            (51, "npc", "Я доктор. То, что дышит, — уже не всегда я. Пейте, если хотите одного ответа. Двух я вам не дам.", -4, -1, None, "spoke_shpilkin", None),
            (52, "npc", "Двери здесь отпирают ключом, не плечом. Хотя плечо у вас, вижу, привычное. Привычка — тоже диагноз.", 0, -1, None, "spoke_shpilkin", None),
        ],
    )
    lines += rows(
        "dialogue_shpilkin_repeat",
        [
            (1, "npc", "Имя и долг. Туман сыт, даже слишком. Идите, пока не передумали. Передумать здесь легче, чем вы думаете.", 0, 10, None, None, None, "has_both"),
            (2, "npc", "Вы назвались. Капли от этого не слаще. Долг ещё в коридоре, ходит, как сиделка.", 0, 10, None, None, None, "has_name"),
            (3, "npc", "Лизавете должны — это я слышал. Имени нет. Номер в журнале не выпускают, и правильно делают.", 0, 10, None, None, None, "guilt_admitted"),
            (4, "npc", "Настасье должны выход. Имени нет. Вата сытая, улица сытее.", 0, 10, None, None, None, "nastasya_escape"),
            (5, "npc", "Вы всё ходите. Значит, капли ещё не взяли. Ходите, ходите... ноги умнее головы.", 0, 10, None, None, None),
            (10, "player", "Что в подвале? Скажите прямо.", 0, 20, 1, None, None),
            (11, "player", "Дайте микстуру. Хочу кончить это. Кончить — и всё.", -8, 30, 1, "trust_doctor", None),
            (12, "player", "Я уйду на улицу. Довольно вашей клиники.", 0, 40, 1, None, None),
            (13, "player", "Я назвался. Этого мало? Скажите, что мало, если мало.", 0, 50, 1, None, None, "has_name"),
            (14, "player", "Лизавете. В канале. Пустите же.", 0, 51, 1, None, None, "guilt_admitted"),
            (15, "player", "Настасье. Я просил выход. Это долг, да?", 0, 52, 1, None, None, "nastasya_escape"),
            (20, "npc", "Там кормят тех, кто слишком много видел. Не спускайтесь голодными. Голод там — не ваш.", -3, -1, None, None, None),
            (30, "npc", "Хорошо. Ложитесь. Утром не будет ни клиники, ни вас. Я уже говорил? Говорил. Повтор — тоже лекарство.", -15, -1, None, None, "stay"),
            (40, "npc", "Улица не клиника. Клиника честнее: она хотя бы запирает. Улица притворяется, будто открыта.", 0, -1, None, None, None),
            (50, "npc", "Мало. Туман ест по отдельности: имя — бумага, долг — кровь. Одного листа ему мало, как и мне.", 0, -1, None, None, None),
            (51, "npc", "Лизавете мало без вашего имени. Канал знает её. Туман вас ещё не знает — и в этом вся беда.", 0, -1, None, None, None),
            (52, "npc", "Настасье вы должны выход. Безымянных вата не считает. Она, видите ли, брезглива.", 0, -1, None, None, None),
        ],
    )
    lines += rows(
        "dialogue_nastasya_intro",
        [
            (1, "npc", "Вы тоже их видите? Ну да, видите. Не притворяйтесь. Тени в углах — и в вас тоже.", 0, 2, None, None, None),
            (2, "npc", "Они шепчут имена. Даже те, которых нет. Особенно те, которых нет. Это больнее, понимаете?", -2, 10, None, None, None),
            (10, "player", "Да. Я видел. И не хочу больше видеть — а всё вижу.", -6, 20, 1, "nastasya_warned", None),
            (11, "player", "Это бред. Ваш и мой. Чей больше — не знаю.", 0, 30, 1, None, None),
            (12, "player", "Помогите выйти отсюда. Прошу. Выход, слышите?", 0, 40, 1, "nastasya_escape", None),
            (20, "npc", "Тогда не спите. Пантелеймон носит вниз тех, кто слишком много видел. Он добрый. Добрые здесь страшнее.", -3, 21, None, "spoke_nastasya", None),
            (21, "npc", "Подвал. Там не лечат. Там кормят. Разница, если вдуматься, невелика.", 0, -1, None, None, None),
            (30, "npc", "Как скажете. Назовём бредом — они тише, ненадолго. Ненадолго, слышите? Потом снова шепчут.", 0, -1, None, "spoke_nastasya", None),
            (31, "npc", "Это не бред. Бред не знает имён. Они знают. Даже те, которых нет. Особенно те.", -5, -1, None, "spoke_nastasya", None),
            (40, "npc", "Вы уже должны мне этот вопрос. Улица не выпускает безымянных. Бумаги Шпилькина — или туман съест вас, как съел меня.", 0, 41, None, "spoke_nastasya", None),
            (41, "narrator", "Она прячет лицо в ладонях. Платье когда-то было бальным. Когда-то — это уже почти ложь.", 0, -1, None, None, None),
            (13, "player", "Имена на полу стёрты рукавом. Как выйти? Скажите, пока не стёрли и это.", 0, 50, 1, "nastasya_escape", None, "class_seeker"),
            (14, "player", "Они зовут не тем именем, которым крестили. Это меня? Не отвечайте, если не хотите.", -4, 51, 1, None, None, "class_mystic"),
            (15, "player", "Довольно шёпота. Где дверь наружу? Говорите.", 0, 52, 1, "nastasya_escape", None, "class_rebel"),
            (50, "npc", "След верный. Бумаги немца и имя — иначе вата на востоке съест шаг. Она сытая, эта вата.", 0, -1, None, "spoke_nastasya", None),
            (51, "npc", "Если шепчут ласково — не отзывайтесь. Это не мать. Мать так не зовёт, поверьте. Я знаю.", -5, -1, None, "spoke_nastasya", None),
            (52, "npc", "Дверь на улице. Туман не плечо: его берут правдой, не ударом. Правдой, слышите? Не кулаком.", 0, -1, None, "spoke_nastasya", None),
        ],
    )
    lines += rows(
        "dialogue_nastasya_repeat",
        [
            (1, "npc", "Имя и долг. Вата на востоке уже тонкая, тонкая... Идите. Пока идёт.", 0, 10, None, None, None, "has_both"),
            (2, "npc", "Вы назвались. Долг ещё шепчет в углу. Шепчет, и я слышу. Не притворяйтесь, что нет.", 0, 10, None, None, None, "has_name"),
            (3, "npc", "Лизавете должны. Без имени вата сытая. Сытая и глухая.", 0, 10, None, None, None, "guilt_admitted"),
            (4, "npc", "Вы просили у меня выход. Долг — мне. Без имени вата сытая, и я тоже...", 0, 10, None, None, None, "nastasya_escape"),
            (5, "npc", "Вы вернулись. Значит, ещё не назвали вас вслух. Не назвали — и хорошо. Или худо. Я уже путаю.", 0, 10, None, None, None),
            (10, "player", "Как пройти туман? Скажите просто.", 0, 20, 1, None, None),
            (11, "player", "Доктор лжёт? Или я уже не умею слышать правду?", 0, 30, 1, None, None),
            (12, "player", "Мне нельзя спать? Я спрашиваю, потому что боюсь ответа.", -2, 40, 1, None, None),
            (13, "player", "Я вспомнил имя. Этого хватит? Скажите, что нет, если нет.", 0, 50, 1, None, None, "has_name"),
            (14, "player", "Лизавете. Этого мало? Я знаю, что мало.", 0, 51, 1, None, None, "guilt_admitted"),
            (15, "player", "Шёпот у лампы был не мой. Чей же?", -2, 52, 1, None, None, "mystic_trace"),
            (16, "player", "Помогите выйти. Это долг вам? Мне нужно слышать это слово.", 0, 53, 1, "nastasya_escape", None),
            (20, "npc", "Именем и долгом вместе. Иначе вата съест шаг. Вместе, слышите? Не по одному, как милостыню.", 0, -1, None, None, None),
            (30, "npc", "Он лечит так, чтобы некого было выписывать. Не пейте, если хотите улицу. Хотите ли вы улицу? Я уже не знаю, хочу ли я.", -3, -1, None, None, None),
            (40, "npc", "Сон здесь — дверь вниз. Пантелеймон ждёт тех, кто закрыл глаза. Он ждёт кротко. Кротость его хуже злобы.", -2, -1, None, None, None),
            (50, "npc", "Имени мало. Туман хочет знать, кому вы должны. Хочет — и будет хотеть, пока не скажете.", 0, -1, None, None, None),
            (51, "npc", "Лизавете мало. Туман хочет имя, не только воду. Вода уже сыта. Имя — нет.", 0, -1, None, None, None),
            (52, "npc", "Значит, он уже звал. Не отвечайте второй раз — даже кивком. Кивок здесь громче крика.", -3, -1, None, None, None),
            (53, "npc", "Да. Мне. И имени, которого у вас нет. Жестоко, да? А я всё равно жду.", 0, -1, None, None, None),
        ],
    )
    lines += rows(
        "dialogue_panteleimon_intro",
        [
            (1, "npc", "Ночью-то не бродите, барин... Тени, известно, любят любопытных. Я ничего. Я так, к слову.", 0, 10, None, None, None),
            (10, "player", "Где ключи? Скажите, Пантелеймон.", 0, 20, 1, None, None),
            (11, "player", "Что за человек — доктор? Немец, да?", 0, 30, 1, None, None),
            (12, "player", "(признаться) Я кого-то погубил. Лизавету, кажется. Кажется — и не кажется.", -8, 40, 1, "guilt_admitted", None),
            (20, "npc", "От палат — у меня. От кабинета доктора ищите сами. От подвала — только у него. Не говорите, что я сказал. Слышите? Не говорите.", 0, 21, None, "spoke_panteleimon", None),
            (21, "npc", "Не говорите, что я сказал. Я и сам не говорил. Ничего не говорил-с.", -2, -1, None, None, None),
            (30, "npc", "Немец. Но ночи у него русские. И голодные. Голодные ночи, барин, страшнее голодных людей.", -4, -1, None, "spoke_panteleimon", None),
            (40, "npc", "Лизавету канал держит. Вас — тоже. Вина здесь не моется. Водой не смоется, слезами — тоже.", -4, -1, None, "spoke_panteleimon", None),
            (13, "player", "Ключ от палат носите на поясе, не в кармане? Я видел царапины.", 0, 50, 1, None, None, "class_seeker"),
            (14, "player", "За вашей спиной молятся голосом не из горла. Вы слышите?", -3, 51, 1, None, None, "class_mystic"),
            (15, "player", "Отдайте ключи. Не просите дважды. Не буду просить дважды.", 0, 52, 1, None, None, "class_rebel"),
            (50, "npc", "Царапины у скважины — не мои. Пояс — да. Не говорите. Ради Христа, не говорите.", 0, -1, None, "spoke_panteleimon", None),
            (51, "npc", "Не слушайте. Кто отвечает — того несут вниз. Вниз, барин. Там тихо. Слишком тихо.", -4, -1, None, "spoke_panteleimon", None),
            (52, "npc", "Плечо дверь знает. Ключ — тише. Берите от палат, если уже не боитесь шума. Шум здесь будят не двери, а люди.", -2, -1, None, "spoke_panteleimon", None),
        ],
    )
    lines += rows(
        "dialogue_panteleimon_repeat",
        [
            (1, "npc", "Имя и долг. Я ничего не слышал, ничего-с. Идите, пока ключи ещё у меня. Пока — это ненадолго.", 0, 10, None, None, None, "has_both"),
            (2, "npc", "Вы назвались. Ключи от этого не легче. Долг ещё в коридоре ходит, как сиделка, тихий такой.", 0, 10, None, None, None, "has_name"),
            (3, "npc", "Лизавете должны. Безымянных ночью носят вниз. Носят кротко. Кротость, барин, хуже злобы.", 0, 10, None, None, None, "guilt_admitted"),
            (4, "npc", "Настасье должны выход. Безымянных ночью носят вниз. Я ничего. Я так.", 0, 10, None, None, None, "nastasya_escape"),
            (5, "npc", "Я ничего не говорил. Слышите? Ничего. Если слышали — не слышали.", 0, 10, None, None, None),
            (10, "player", "Ключи. Ещё раз. Пантелеймон.", 0, 20, 1, None, None),
            (11, "player", "Тени в столовой — ваши? Скажите правду, хотя бы раз.", 0, 30, 1, None, None),
            (12, "player", "(признаться) Я виноват. Лизавете. Виноват, да.", -6, 40, 1, "guilt_admitted", None),
            (13, "player", "Замок орёт до сих пор. Это я. Я знаю.", 0, 50, 1, None, None, "broke_door"),
            (14, "player", "Я назвался. Отдайте ключи. Хватит прятать.", 0, 51, 1, None, None, "has_name"),
            (15, "player", "Лизавете. Пустите. Ради неё.", 0, 52, 1, None, None, "guilt_admitted"),
            (16, "player", "Настасье выход. Этого мало? Скажите.", 0, 53, 1, None, None, "nastasya_escape"),
            (20, "npc", "Палаты — у меня. Кабинет — ищите. Подвал — у немца. Это уже слишком много. Я много сказал. Слишком.", -2, -1, None, None, None),
            (30, "npc", "Не мои. Мои носят вниз. Те приходят сами, когда смотришь слишком долго. Не смотрите, барин. Не смотрите.", -3, -1, None, None, None),
            (40, "npc", "Лизавете — учёт в воде. Вам сюда. Вину здесь не моют. Не моют, сколько ни три.", -3, -1, None, None, None),
            (50, "npc", "Это были вы. Ключи после такого прячут. Немец не спит. Он и не спал, кажется.", -2, -1, None, None, None),
            (51, "npc", "Мало. Ключ слушает два слова. Вы сказали одно. Одно, барин. Ключ обижается.", -2, -1, None, None, None),
            (52, "npc", "Лизавете мало без имени. Ночью таких несут вниз. Несут и не спрашивают.", -3, -1, None, None, None),
            (53, "npc", "Настасье — дверь. Вам — имя. Иначе подвал. Иначе — тишина. Тишина сытая.", -2, -1, None, None, None),
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
            INKS["ash"],
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
             "Вы пришли. Я ждал — или это вы ждали меня? Впрочем, какая разница. Мы оба ждали. Это стыдно.", 0, 10, None, None, None),
            ("dialogue_double_intro", 10, "player", "Кто вы? Скажите. Хоть раз скажите прямо.", 0, 20, 1, None, None),
            ("dialogue_double_intro", 11, "player", "Вас нет. Нет. Слышите? Нет.", -2, 30, 1, None, None),
            ("dialogue_double_intro", 12, "player", "Простите меня. Лизавете. И себе. Особенно себе.", -10, 40, 1,
             "guilt_admitted", None),
            ("dialogue_double_intro", 20, "npc",
             "Я — то, что вы оставили в канале вместо Лизаветы. Имя. Долг. Всё, что вам стыдно носить днём.", -6, -1, None,
             "spoke_double", None),
            ("dialogue_double_intro", 30, "npc",
             "Нет. Есть. Разница вам уже не принадлежит.", -4, -1, None,
             "spoke_double", None),
            ("dialogue_double_intro", 40, "npc",
             "Поздно для Лизаветы. Туман слышит имя в воде.", -8, -1, None,
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
             "Имя и долг. Мы оба сыты. Идите, пока нас двое.", 0, 10, None, None, None, "has_both"),
            ("dialogue_double_repeat", 2, "npc",
             "Вы назвались. Я всё ещё держу долг — в канале, где Лизавета.", 0, 10, None, None, None, "has_name"),
            ("dialogue_double_repeat", 3, "npc",
             "Лизавете должны. Безымянным я не отдаю отражение.", 0, 10, None, None, None, "guilt_admitted"),
            ("dialogue_double_repeat", 4, "npc",
             "Настасье — дверь. Мне — канал. Безымянным не отдают ни то ни другое.", 0, 10, None, None, None, "nastasya_escape"),
            ("dialogue_double_repeat", 5, "npc",
             "Вы вернулись. Или это я не уходил.", 0, 10, None, None, None),
            ("dialogue_double_repeat", 10, "player", "Что ты взял у меня?", -2, 20, 1, None, None),
            ("dialogue_double_repeat", 11, "player", "Исчезни.", 0, 30, 1, None, None),
            ("dialogue_double_repeat", 12, "player", "Прости. Ещё раз.", -8, 40, 1,
             "guilt_admitted", None),
            ("dialogue_double_repeat", 13, "player", "Я назвался. Отдай лицо.", 0, 50, 1, None, None, "has_name"),
            ("dialogue_double_repeat", 14, "player", "Лизавете. Отдай лицо.", 0, 51, 1, None, None, "guilt_admitted"),
            ("dialogue_double_repeat", 15, "player", "Настасье выход. Этого мало?", 0, 52, 1, None, None, "nastasya_escape"),
            ("dialogue_double_repeat", 20, "npc",
             "Лизавету. Отражение. То место в канале, куда вы не смотрите.", -4, -1, None, None, None),
            ("dialogue_double_repeat", 30, "npc",
             "Исчезну. В зеркале. Тогда вы останетесь один — и это хуже.", -3, -1, None, None, None),
            ("dialogue_double_repeat", 40, "npc",
             "Слышу. Лизавета тоже. Идите, пока нас двое, а не одно.", -6, -1, None, None, None),
            ("dialogue_double_repeat", 50, "npc",
             "Мало. Я взял оба: имя в бумаге, Лизавету в воде. Верните второе.", -2, -1, None, None, None),
            ("dialogue_double_repeat", 51, "npc",
             "Лизавета в воде. Имя — на берегу. Верните оба.", -3, -1, None, None, None),
            ("dialogue_double_repeat", 52, "npc",
             "Настасье — дверь. Мне — канал. Безымянным не отдают ни то ни другое.", -3, -1, None, None, None),
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
                12,
            ),
        ],
    )
    conn.execute(
        "UPDATE maps SET width = 57, height = 12 WHERE id = 'hospital_floor_1'"
    )

    conn.executemany(
        """DELETE FROM map_connections
           WHERE source_map_id = ? AND source_x = ? AND source_y = ?""",
        [
            ("street_outside", 0, 9),
            ("street_outside", 0, 10),
            ("street_outside", 26, 3),
            ("street_outside", 26, 6),
            ("street_outside", 32, 6),
            ("street_outside", 33, 6),
            ("street_traktir", 0, 7),
            ("street_traktir", 0, 8),
            ("street_traktir", 35, 7),
            ("street_traktir", 35, 8),
        ],
    )
    conn.executemany(
        """INSERT INTO map_connections
           (source_map_id, connection_type, source_x, source_y,
            target_map_id, target_x, target_y, description)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            ("street_outside", "entrance", 0, 9, "hospital_floor_1", 54, 1,
             "Вернуться в клинику"),
            ("street_outside", "entrance", 0, 10, "hospital_floor_1", 54, 1,
             "Вернуться в клинику"),
            ("street_outside", "entrance", 32, 6, "street_traktir", 1, 7,
             "Войти в трактир"),
            ("street_outside", "entrance", 33, 6, "street_traktir", 1, 7,
             "Войти в трактир"),
            ("street_outside", "entrance", 26, 3, "street_traktir", 34, 7,
             "Чёрный ход в трактир"),
            ("street_traktir", "exit", 0, 7, "street_outside", 32, 7,
             "Выйти на набережную"),
            ("street_traktir", "exit", 0, 8, "street_outside", 32, 7,
             "Выйти на набережную"),
            ("street_traktir", "exit", 35, 7, "street_outside", 25, 3,
             "Выйти во двор"),
            ("street_traktir", "exit", 35, 8, "street_outside", 25, 3,
             "Выйти во двор"),
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
            ("st_tavern", "street_outside", 26, 6, 40, 7, "Трактир",
             "Вывеска «У канала». Буквы кривые, как после удара.", 0),
            ("st_yard", "street_outside", 12, 1, 25, 5, "Двор",
             "Колодец двора. Окна чужих кухонь смотрят в одно небо.", -1),
            ("tav_seni", "street_traktir", 1, 1, 5, 12, "Сени",
             "Сени. С улицы ещё пахнет каналом, из зала — самоваром.", 0),
            ("tav_room", "street_traktir", 6, 1, 25, 12, "Зал",
             "Самовар шумит, будто держит речь. Здесь ещё пьют за живых.", -1),
            ("tav_kitchen", "street_traktir", 26, 1, 34, 12, "Кухня",
             "Печь и чёрный ход. Двор ближе, чем вывеска.", -1),
            ("bred_hall", "hospital_bred", 13, 1, 55, 2, "Чужой коридор",
             "Лампа горит вчерашним светом. Шаги ваши уже прошли здесь без вас.", -8),
        ],
    )

    conn.execute(
        """INSERT INTO items
           (id, type, name, description, damage_die, healing, sanity_restore,
            sanity_damage, symbol, color, is_quest_item, use_effect, content)
           VALUES (?, 'note', ?, ?, '', 0, 0, -4, '≈', ?, 1, 'read_note', ?)
           ON CONFLICT(id) DO UPDATE SET content = excluded.content""",
        (
            "note_canal",
            "Записка с набережной",
            "Мокрый клочок. Чернила расползлись к каналу.",
            INKS["paper"],
            "Лизавете. Канал взял имя, которым её звали в детстве. "
            "Кто вспомнит долг по имени — того туман ещё может пропустить. "
            "Может. Не обещает.",
        ),
    )

    conn.executemany(
        """INSERT INTO map_placements (map_id, x, y, spawn_type, spawn_id)
           VALUES (?, ?, ?, ?, ?)""",
        [
            ("street_outside", 8, 12, "character", "watchman_petrov"),
            ("street_outside", 47, 10, "character", "sennaya_beggar"),
            ("street_traktir", 8, 4, "character", "innkeeper_semyon"),
            ("hospital_bred", 22, 10, "character", "shadow_enemy"),
        ],
    )

    _upsert_npc(conn, (
        "innkeeper_semyon", "npc", "Семён", "Трактирщик",
        "Щёки красные, глаза нет. Полотенце на плече как епитрахиль.",
        8, 10, 0, "1d4", 10, 10, 12, 10, 12, "dialogue", 0, "city",
        "&", INKS["ochre"], "dialogue_innkeeper_intro",
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
            (1, "npc", "Клиника? Ночью оттуда возвращаются без лиц. Садитесь — или идите. Мне всё равно, ей-богу, всё равно... нет, не всё равно.", 0, 10, None, None, None),
            (10, "player", "Кто я? Вы, кажется, знаете. Скажите.", -4, 20, 1, None, None),
            (11, "player", "Налейте. Хочу не помнить. Не помнить — и пить.", -6, 30, 1, None, None),
            (12, "player", "Мне нужна улица, не стакан. Улица, Семён.", 0, 40, 1, None, None),
            (13, "player", "На пороге грязь с двух каблуков. Откуда второй?", 0, 50, 1, None, None, "class_seeker"),
            (14, "player", "Самовар поёт не ту ноту. Чьё имя в ней?", -3, 51, 1, None, None, "class_mystic"),
            (15, "player", "Дверь не запирается. Значит, запирают людей.", 0, 52, 1, None, None, "class_rebel"),
            (20, "npc", "Кто — не скажу. Но имя у вас было громче этого самовара. Громче, сударь. Самовар обижается.", -3, -1, None, "spoke_innkeeper", None),
            (30, "npc", "Пейте. Забвение здесь дешевле правды — и туже держит. Держит, как долг. Я знаю, да-с.", -5, -1, None, "spoke_innkeeper", None),
            (40, "npc", "Тогда на Сенную. Там ещё просят имена — и иногда отдают. Иногда. Не надейтесь слишком.", 0, -1, None, "spoke_innkeeper", None),
            (50, "npc", "Один каблук — клиники, второй — Сенной. Вы уже ходили и не помните.", -2, -1, None, "spoke_innkeeper", None),
            (51, "npc", "Имя, которое вы бросили. Самовар честнее зеркал.", -4, -1, None, "spoke_innkeeper", None),
            (52, "npc", "Верно. Пейте или идите. Запирать будем не дверь.", 0, -1, None, "spoke_innkeeper", None),
        ],
        [
            (1, "npc", "Имя и долг. Самовар вас уже не держит. Идите.", 0, 10, None, None, None, "has_both"),
            (2, "npc", "Вы назвались. Стакан от этого не трезвее — долг ещё в чашке.", 0, 10, None, None, None, "has_name"),
            (3, "npc", "Лизавете должны. Пьяных без имени здесь не считают.", 0, 10, None, None, None, "guilt_admitted"),
            (4, "npc", "Настасье должны выход. Пьяных без имени здесь не считают.", 0, 10, None, None, None, "nastasya_escape"),
            (5, "npc", "Стакан ещё тёплый. Правда — нет.", 0, 10, None, None, None),
            (10, "player", "Куда идти, если не пить?", 0, 20, 1, None, None),
            (11, "player", "Налейте. Пусть будет тише.", -4, 30, 1, None, None),
            (12, "player", "Клиника зовёт обратно.", 0, 40, 1, None, None),
            (13, "player", "Я назвался. Пустите к каналу.", 0, 50, 1, None, None, "has_name"),
            (14, "player", "Лизавете. Этого мало для улицы?", 0, 51, 1, None, None, "guilt_admitted"),
            (15, "player", "Настасье выход. Этого мало?", 0, 52, 1, None, None, "nastasya_escape"),
            (20, "npc", "На Сенную. Там имя дороже водки — и его ещё отдают.", 0, -1, None, None, None),
            (30, "npc", "Тише станет. Вы — нет. Пейте, пока самовар помнит вас живым.", -3, -1, None, None, None),
            (40, "npc", "Она всегда зовёт. Кто возвращается — тот уже номер.", -2, -1, None, None, None),
            (50, "npc", "Мало. Туман пьёт два слова. Вы сказали одно.", 0, -1, None, None, None),
            (51, "npc", "Лизавете мало без имени. Канал не принимает кредит.", 0, -1, None, None, None),
            (52, "npc", "Настасье — дверь. Вам — имя. Иначе самовар вас забудет.", 0, -1, None, None, None),
        ],
    )
    _seed_city_dialogue(
        conn,
        "dialogue_watchman_intro",
        "watchman_petrov",
        "dialogue_watchman_repeat",
        [
            (1, "npc", "Документы. Аль ступайте обратно, в номер. Халат я вижу. Документа — нет.", 0, 10, None, None, None),
            (10, "player", "Я болен. Меня выпустили. Честное слово, выпустили.", 0, 20, 1, None, None),
            (11, "player", "(признаться) Документов нет. И имени — тоже. Пусто, вот что.", -6, 30, 1, None, None),
            (12, "player", "Не загораживайте. Пожалуйста... нет, не пожалуйста. Прочь.", 0, 40, 1, None, None),
            (13, "player", "Шинель в снегу, которого нет. Откуда вы, Петров? Скажите.", 0, 50, 1, None, None, "class_seeker"),
            (14, "player", "Свисток молчит. Его кто-то держит за горло. Вы слышите?", -2, 51, 1, None, None, "class_mystic"),
            (15, "player", "Уберите руку. Не просите дважды. Не буду просить.", 0, 52, 1, None, None, "class_rebel"),
            (16, "player", "Лизавете. Я прочёл это имя. Прочёл — и не могу забыть.", -4, 53, 1, "guilt_admitted", None, "knows_lizaveta"),
            (20, "npc", "Халат вижу. Болезнь — как скажете. Ступайте. Свисток пока молчит. В журнал не внесу: нет фамилии — нет строки.", 0, -1, None, "spoke_watchman", None),
            (30, "npc", "Пустые карманы — не протокол. Имя в архиве. Долг — в бумаге или в воде. Вода, сударь, памятливее бумаги.", -4, -1, None, "spoke_watchman", None),
            (40, "npc", "Смелости у вас больше, чем права. Не попадайтесь второй раз. Второй раз я уже не городовой.", 0, -1, None, "spoke_watchman", None),
            (50, "npc", "Снег был. Потом клиника. Потом я здесь без права уйти. Без права, слышите? Как и вы.", -2, -1, None, "spoke_watchman", None),
            (51, "npc", "Не свищу. Кто свистит ночью — тот уже не городовой. Тот — другой чин. Худший.", -3, -1, None, "spoke_watchman", None),
            (52, "npc", "Идите. Плечо ваше я запомню. Запомню и не прощу, если придётся.", 0, -1, None, "spoke_watchman", None),
            (53, "npc", "Теперь в протоколе лицо. Фамилии вашей всё ещё нет. Лицо без фамилии — пятно, не человек.", -2, -1, None, "spoke_watchman", None),
        ],
        [
            (1, "npc", "Имя и долг. Свисток молчит. Проходите.", 0, 10, None, None, None, "has_both"),
            (2, "npc", "Документ есть — имя. Долг ещё не в протоколе.", 0, 10, None, None, None, "has_name"),
            (3, "npc", "Лизавете записаны. Фамилии нет. Беглецов без имени возвращают.", 0, 10, None, None, None, "guilt_admitted"),
            (4, "npc", "Настасье должны выход. Фамилии нет. Беглецов без имени возвращают.", 0, 10, None, None, None, "nastasya_escape"),
            (5, "npc", "Всё те же карманы. Всё те же пустые.", 0, 10, None, None, None),
            (10, "player", "Пропустите к каналу.", 0, 20, 1, None, None),
            (11, "player", "(признаться) Я бежал. И виноват.", -5, 30, 1, None, None),
            (12, "player", "Где Сенная?", 0, 40, 1, None, None),
            (13, "player", "Я назвался. Пропустите.", 0, 50, 1, None, None, "has_name"),
            (14, "player", "Лизавете. Этого мало?", 0, 51, 1, None, None, "guilt_admitted"),
            (15, "player", "Настасье выход. Пропустите.", 0, 52, 1, None, None, "nastasya_escape"),
            (16, "player", "Лизавете. Я прочёл это имя.", -4, 53, 1, "guilt_admitted", None, "knows_lizaveta"),
            (20, "npc", "Канал никого не пропускает. Он принимает.", -2, -1, None, None, None),
            (30, "npc", "Вина без лица — не протокол. Ищите бумагу. Или воду.", -3, -1, None, None, None),
            (40, "npc", "На восток, в вату. Без имени не ходите — фонари врут.", 0, -1, None, None, None),
            (50, "npc", "Мало. Свисток слушает два пункта. Вы назвали один.", 0, -1, None, None, None),
            (51, "npc", "Лизавете мало без имени. Побег в никуда.", 0, -1, None, None, None),
            (52, "npc", "Настасье — дверь. Вам — фамилия. Иначе номер.", 0, -1, None, None, None),
            (53, "npc", "Лицо записано. Имени нет. Беглецов без фамилии возвращают.", 0, -1, None, None, None),
        ],
    )
    _seed_city_dialogue(
        conn,
        "dialogue_beggar_intro",
        "sennaya_beggar",
        "dialogue_beggar_repeat",
        [
            (1, "npc", "Имя, барин. Без имени туман — стена, да-с. Стена сытая. Сытая и терпеливая.", 0, 10, None, None, None),
            (10, "player", "Я не помню. Вот что скверно: не помню и стыдно.", -2, 20, 1, None, None),
            (11, "player", "(назвать чужое) Иван. Пусть будет Иван, если вам так надо.", 0, 30, 1, None, None),
            (12, "player", "(отдать своё, какое есть)", -8, 40, 1, None, None),
            (13, "player", "На ладони след печати. Чья печать? Скажите.", 0, 50, 1, None, None, "class_seeker"),
            (14, "player", "Туман зовёт ласково, как звали в детстве. Не берите. Ради Христа, не берите.", -4, 51, 1, None, None, "class_mystic"),
            (15, "player", "Имя не милостыня. Отойдите. Отойдите же.", 0, 52, 1, None, None, "class_rebel"),
            (16, "player", "Лизавете. Канал взял её имя. Взял — и не отдаёт.", -4, 53, 1, "guilt_admitted", None, "knows_lizaveta"),
            (20, "npc", "Тогда стойте. Стена сытая. Сытая, да-с. И я сыт вашим «не помню».", -3, -1, None, "spoke_beggar", None),
            (30, "npc", "Иван так Иван. Стена сыта любым именем. На восток — лавка, если жилец. Архив я не держу. Не держу, да-с.", 0, -1, None, "spoke_beggar", None),
            (40, "npc", "Пустая ладонь. Имя без бумаги туман не считает. Архив — на втором. На втором, барин, не здесь. Здесь только просят.", -6, -1, None, "spoke_beggar", None),
            (53, "npc", "Долг услышал. Имени нет. Стена ещё хочет подпись. Хочет — и будет хотеть.", -3, -1, None, "spoke_beggar", None),
            (50, "npc", "Академии. Или клиники. Печать одна — руки разные. Руки, сударь, врут чаще печатей.", -2, -1, None, "spoke_beggar", None),
            (51, "npc", "Правильно. Кто отзовётся — останется здесь без мостовой. Без мостовой, да-с. А я уж остался.", -5, -1, None, "spoke_beggar", None),
            (52, "npc", "Тогда стойте в вате. Стена любит гордых. Любит и ест, хе-хе... не смеюсь. Смеюсь.", 0, -1, None, "spoke_beggar", None),
        ],
        [
            (1, "npc", "Имя взял. Долг слышал. Мостовая ваша.", 0, 10, None, None, None, "has_both"),
            (2, "npc", "Имя есть. Стена ещё хочет, кому вы должны.", 0, 10, None, None, None, "has_name"),
            (3, "npc", "Лизавете должны — и безымянны. Стена сытая.", 0, 10, None, None, None, "guilt_admitted"),
            (4, "npc", "Настасье должны выход — и безымянны. Стена сытая.", 0, 10, None, None, None, "nastasya_escape"),
            (5, "npc", "Ещё раз. Имя или стена.", 0, 10, None, None, None),
            (10, "player", "Я всё так же не помню.", -2, 20, 1, None, None),
            (11, "player", "(отдать то, что есть)", -6, 30, 1, None, None),
            (12, "player", "Я уже отдал.", 0, 40, 1, None, None),
            (13, "player", "Имя ваше. Долг — нет?", 0, 50, 1, None, None, "has_name"),
            (14, "player", "Лизавете. Этого мало?", 0, 51, 1, None, None, "guilt_admitted"),
            (15, "player", "Настасье выход. Этого мало?", 0, 52, 1, None, None, "nastasya_escape"),
            (16, "player", "Лизавете. Я прочёл это имя.", -4, 53, 1, "guilt_admitted", None, "knows_lizaveta"),
            (20, "npc", "Тогда стойте. Стена терпеливая.", -2, -1, None, None, None),
            (30, "npc", "Без бумаги это Иван. Стена сытая.", -4, -1, None, None, None),
            (53, "npc", "Долг услышал. Имени нет. Стена ещё хочет подпись.", -3, -1, None, None, None),
            (40, "npc", "Тогда зачем пришли? Туман не любит повторных подаяний.", 0, -1, None, None, None),
            (50, "npc", "Мало. Стена слушает два слова. Вы сказали одно.", 0, -1, None, None, None),
            (51, "npc", "Лизавете мало без имени. Милостыня пустая.", 0, -1, None, None, None),
            (52, "npc", "Настасье — дверь. Стена хочет ещё ваше имя.", 0, -1, None, None, None),
        ],
    )


def _apply_phase4(conn) -> None:
    """Архив второго этажа: человек, дело, имя для тумана."""
    conn.execute(
        """INSERT INTO items
           (id, type, name, description, damage_die, healing, sanity_restore,
            sanity_damage, symbol, color, is_quest_item, use_effect, content)
           VALUES (?, 'note', ?, ?, '', 0, 0, -3, '≈', ?, 1, 'read_note', ?)
           ON CONFLICT(id) DO UPDATE SET content = excluded.content,
             name = excluded.name, description = excluded.description""",
        (
            "note_case",
            "Дело без обложки",
            "Папка, у которой отодрали картон вместе с фамилией.",
            INKS["paper"],
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
            (1, "npc", "Картотека не спит. Вы — номер или имя? Не молчите: молчание я записываю как номер.", 0, 10, None, None, None),
            (10, "player", "Ищу свою историю. Хоть клочок.", 0, 20, 1, None, None),
            (11, "player", "Чьи это папки? Скажите прямо, Клара.", -2, 30, 1, None, None),
            (12, "player", "(назвать себя, как получится)", -6, 40, 1, "archive_name", None),
            (13, "player", "На корешке свежая дата и нет фамилии. Это я?", 0, 50, 1, None, None, "class_seeker"),
            (14, "player", "Папка зовёт по имени, которого я здесь не называл. Не открывайте.", -3, 51, 1, None, None, "class_mystic"),
            (15, "player", "Шкаф не заперт. Отдайте моё дело.", 0, 52, 1, None, None, "class_rebel"),
            (20, "npc", "История здесь чужая. Свою прячут в кабинете, под ковром.",
             -2, -1, None, "spoke_archivist", None),
            (30, "npc", "Больных. Врачей. И тех, кого выписали в канал.",
             -4, -1, None, "spoke_archivist", None),
            (40, "npc", "Записала. Туман любит бумагу больше лиц. Больше, чем нас с вами. Это даже честно.",
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
            (3, "npc", "Лизавете на полях. Подписи нет. Номер не выпускают.", 0, 10, None, None, None, "guilt_admitted"),
            (4, "npc", "Настасье должны выход. Подписи нет. Номер не выпускают.", 0, 10, None, None, None, "nastasya_escape"),
            (5, "npc", "Карточка открыта. Чернила не высохли.", 0, 10, None, None, None),
            (10, "player", "Где кабинет Шпилькина?", 0, 20, 1, None, None),
            (11, "player", "(подписать себя)", -5, 30, 1, "archive_name", None),
            (12, "player", "Закройте дело.", 0, 40, 1, None, None),
            (13, "player", "Я уже в карточке. Пустите.", 0, 50, 1, None, None, "has_name"),
            (14, "player", "Лизавете. Этого хватит?", 0, 51, 1, None, None, "guilt_admitted"),
            (15, "player", "Дата на бюро — моя рука.", 0, 52, 1, None, None, "seeker_trace"),
            (16, "player", "Настасье выход. Этого хватит?", 0, 53, 1, None, None, "nastasya_escape"),
            (20, "npc", "За запертой дверью. Ключ у него. Под ковром — то, чего нет в картотеке.",
             0, -1, None, None, None),
            (30, "npc", "Есть. Туман это любит больше лиц — если рядом долг.", -4, -1, None, None, None),
            (40, "npc", "Дело без имени не закрывается. Оно ждёт, пока вы совпадёте с бумагой.",
             -2, -1, None, None, None),
            (50, "npc", "Подпись есть. Долг — на другом листе. Туман читает оба.", 0, -1, None, None, None),
            (51, "npc", "Лизавете без подписи — номер. Назовите себя.", -2, -1, None, None, None),
            (52, "npc", "Видела дату. Это не имя, но след. Клара не врёт картотеке.", 0, -1, None, None, None),
            (53, "npc", "Настасье — дверь. Карточке — фамилия. Иначе номер.", -2, -1, None, None, None),
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
            (1, "npc", "Не подходите. Он ещё здесь. Я — уже нет. Впрочем, кто из нас говорит? Не спрашивайте.", 0, 10, None, None, None),
            (10, "player", "Кто он? Скажите, пока можете.", 0, 20, 1, None, None),
            (11, "player", "Вас лечат? Или уже не вас?", -2, 30, 1, None, None),
            (12, "player", "Отойдите. Прошу. Отойдите.", 0, 40, 1, None, None),
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
            (1, "npc", "Имя и долг. Он сыт. Говорите тише — или не говорите.", 0, 10, None, None, None, "has_both"),
            (2, "npc", "Вы назвались. Долг ещё в зубах. Он не отпускает.", 0, 10, None, None, None, "has_name"),
            (3, "npc", "Лизавете должны. Безымянных он надевает как халат.", 0, 10, None, None, None, "guilt_admitted"),
            (4, "npc", "Настасье — дверь. Он держит имя. Безымянных надевает.", 0, 10, None, None, None, "nastasya_escape"),
            (5, "npc", "Он ближе. Говорите тише.", 0, 10, None, None, None),
            (10, "player", "Как вас звали?", 0, 20, 1, None, None),
            (11, "player", "Я уйду.", 0, 30, 1, None, None),
            (12, "player", "Держитесь.", -2, 40, 1, None, None),
            (13, "player", "Я назвался. Отпусти.", 0, 50, 1, None, None, "has_name"),
            (14, "player", "Лизавете. Этого мало?", 0, 51, 1, None, None, "guilt_admitted"),
            (15, "player", "Настасье выход. Отпусти.", 0, 52, 1, None, None, "nastasya_escape"),
            (20, "npc", "Как вас. Почти. Не произносите.", -3, -1, None, None, None),
            (30, "npc", "Идите. Шаг на клетку — уже не разговор.", 0, -1, None, None, None),
            (40, "npc", "Держусь чужим зубом. Это не милость.", -2, -1, None, None, None),
            (50, "npc", "Мало. Он слушает два слова. Вы сказали одно.", -3, -1, None, None, None),
            (51, "npc", "Лизавете мало без имени. Халат без подписи.", -4, -1, None, None, None),
            (52, "npc", "Настасье — дверь. Ему — ваше имя. Иначе останетесь вместо меня.", -3, -1, None, None, None),
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
            18,
            1,
            "Шёпот за лампой. Не ваш. И не живой.",
            -2,
        ),
        (
            "trigger_cafe",
            "hospital_floor_1",
            45,
            6,
            "Стул ждёт того, кого уже увели. Рядом ещё один — занят.",
            -2,
        ),
        (
            "trigger_archive",
            "hospital_floor_2",
            10,
            5,
            "Папка без корешка. Дата — сегодняшняя. Имени нет.",
            -2,
        ),
        (
            "trigger_cell",
            "hospital_basement",
            11,
            2,
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
            "hospital_floor_2:42,5",
            "Под ковром щель. В ней клочок: «Не имя. Номер. Так спокойнее.»",
            -2,
            "hospital_floor_2",
            42,
            5,
        ),
    )
    conn.execute(
        """UPDATE items SET content = ? WHERE id = 'letter_1'""",
        (
            "Уважаемый доктор фон Шпилькин! Новые препараты высланы. "
            "Результаты — к концу месяца. Не подведите нас. "
            "На полях его рука, дрожащая: «Пациент вспоминает. Нельзя. Нельзя, слышите?»",
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


def _apply_phase11(conn) -> None:
    """Долг имеет лицо: Лизавете в канале, Настасье — выход."""
    conn.execute(
        """UPDATE quests
           SET title = ?, description = ?
           WHERE id = 'find_notes'""",
        (
            "Имя и долг",
            "Туман слышит имя и то, кому должны: Лизавете в канале, "
            "Настасье — выход, который просили.",
        ),
    )
    conn.execute(
        """UPDATE items SET content = ?
           WHERE id = 'note_canal'""",
        (
            "Лизавете. Канал взял имя, которым её звали в детстве. "
            "Кто вспомнит долг по имени — того туман ещё может пропустить. "
            "Может. Не обещает.",
        ),
    )
    conn.execute(
        """UPDATE items SET content = ?
           WHERE id = 'note_case'""",
        (
            "Пациент N. Пробуждение без имени. На полях чужое: Лизавета. "
            "Не выпускать на Сенную, пока не подпишет себя и не вспомнит, кому должен. "
            "Пока не вспомнит — кормить. Кормить и не слушать.",
        ),
    )


CONTAINER_LOOT: List[Tuple[str, int, int, str]] = [
    ("hospital_floor_1", 1, 1, "diary_1"),
    ("hospital_floor_1", 3, 1, "key_doctor"),
    ("hospital_floor_1", 12, 1, "note_1"),
    ("hospital_floor_1", 1, 5, "diary_2"),
    ("hospital_floor_1", 14, 5, "key_warden"),
    ("hospital_floor_1", 1, 7, "key_basement"),
    ("hospital_floor_1", 41, 4, "diary_3"),
    ("hospital_floor_1", 42, 4, "potion_heal"),
    ("hospital_floor_1", 38, 5, "item_knife"),
    ("hospital_floor_1", 40, 7, "potion_sanity"),
    ("hospital_floor_2", 1, 1, "note_case"),
    ("hospital_floor_2", 3, 1, "potion_heal"),
    ("hospital_floor_2", 34, 5, "letter_1"),
    ("hospital_floor_2", 16, 1, "note_2"),
    ("hospital_basement", 39, 5, "document_1"),
    ("street_outside", 18, 15, "note_canal"),
    ("street_tenement", 24, 3, "key_tenement"),
    ("street_tenement", 44, 2, "note_tenement"),
    ("street_tenement", 44, 3, "item_coat"),
]


def _apply_phase12(conn) -> None:
    """Лут в мебели. Записки снова правда. С пола — вон."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS container_loot (
            map_id TEXT NOT NULL,
            x INTEGER NOT NULL,
            y INTEGER NOT NULL,
            item_id TEXT NOT NULL,
            PRIMARY KEY (map_id, x, y)
        );
        """
    )
    conn.execute("DELETE FROM container_loot")
    conn.executemany(
        "INSERT INTO container_loot (map_id, x, y, item_id) VALUES (?, ?, ?, ?)",
        CONTAINER_LOOT,
    )
    conn.execute("DELETE FROM map_placements WHERE spawn_type = 'item'")
    conn.executemany(
        "UPDATE items SET content = ? WHERE id = ?",
        [
            (
                "Портрет без глаз. На раме ногтем: Лизавета. Не академия писала. Академия так не пишет: у академии нет ногтей.",
                "note_1",
            ),
            (
                "Подвал кормит тех, кто закрыл глаза. Ключ от палат носят на поясе. На поясе, не в кармане. Карман врёт.",
                "note_2",
            ),
            (
                "Ключ от кабинета кладут в стол, не в карман. Немец пишет ночами. Пишет — и, кажется, сам себя боится.",
                "diary_1",
            ),
            (
                "В архиве на втором папка без обложки. Подпишите — или останетесь номером. Номер не зовут. Номер кормят.",
                "diary_2",
            ),
            (
                "На Сенной просят имя. Туман слушает бумагу, не крик. Крик ему противен. Бумага — нет.",
                "diary_3",
            ),
            (
                "Препарат не лечит. Он стирает. На полях: не выпускать к каналу. К каналу — особенно. Особенно.",
                "document_1",
            ),
        ],
    )


def _apply_phase13(conn) -> None:
    """Восемь навыков × три занятия. Коридор — 3d6, не дерево."""
    from engine.rpg_system import CLASS_SKILL_TABLE, SKILL_IDS

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS class_skills (
            class_id TEXT NOT NULL,
            skill_id TEXT NOT NULL,
            threshold INTEGER NOT NULL,
            PRIMARY KEY (class_id, skill_id)
        );
        """
    )
    conn.execute("DELETE FROM class_skills")
    rows = []
    for class_id, skills in CLASS_SKILL_TABLE.items():
        for skill_id in SKILL_IDS:
            rows.append((class_id, skill_id, int(skills[skill_id])))
    conn.executemany(
        "INSERT INTO class_skills (class_id, skill_id, threshold) VALUES (?, ?, ?)",
        rows,
    )


def _apply_phase14(conn) -> None:
    """Говорить: 3d6 на две уличные лжи. Правды тумана не трогаем."""
    _ensure_column(conn, "dialogue_lines", "skill_id", "TEXT")
    _ensure_column(conn, "dialogue_lines", "fail_next_order", "INTEGER")
    conn.execute(
        """UPDATE dialogue_lines
           SET skill_id = 'talk', fail_next_order = 21
           WHERE dialogue_id = 'dialogue_watchman_intro' AND order_num = 10"""
    )
    conn.execute(
        """UPDATE dialogue_lines
           SET skill_id = 'talk', fail_next_order = 31
           WHERE dialogue_id = 'dialogue_beggar_intro' AND order_num = 11"""
    )
    conn.execute(
        """DELETE FROM dialogue_lines
           WHERE (dialogue_id = 'dialogue_watchman_intro' AND order_num = 21)
              OR (dialogue_id = 'dialogue_beggar_intro' AND order_num = 31)"""
    )
    conn.executemany(
        """INSERT INTO dialogue_lines
           (dialogue_id, order_num, speaker, text, sanity_change, next_order,
            choice_group, sets_flag, ending_id, requires_flag)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                "dialogue_watchman_intro",
                21,
                "npc",
                "Халат не документ. Ступайте в номер. Халат, сударь, носят и мёртвые.",
                -2,
                -1,
                None,
                "spoke_watchman",
                None,
                None,
            ),
            (
                "dialogue_beggar_intro",
                31,
                "npc",
                "Чужое имя слышно сразу. Стена сытая. Иванов здесь полно, туман их не считает.",
                -2,
                -1,
                None,
                "spoke_beggar",
                None,
                None,
            ),
        ],
    )


def _apply_phase15(conn) -> None:
    """Слышать: свисток постового. Лампа — в движке. Не новый этаж."""
    _ensure_column(conn, "dialogue_lines", "skill_id", "TEXT")
    _ensure_column(conn, "dialogue_lines", "fail_next_order", "INTEGER")
    conn.execute(
        """UPDATE dialogue_lines
           SET skill_id = 'hear', fail_next_order = 54
           WHERE dialogue_id = 'dialogue_watchman_intro' AND order_num = 14"""
    )
    conn.execute(
        """DELETE FROM dialogue_lines
           WHERE dialogue_id = 'dialogue_watchman_intro' AND order_num = 54"""
    )
    conn.execute(
        """INSERT INTO dialogue_lines
           (dialogue_id, order_num, speaker, text, sanity_change, next_order,
            choice_group, sets_flag, ending_id, requires_flag)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "dialogue_watchman_intro",
            54,
            "npc",
            "Свисток обычный. Горло — ваше. Не моё. Я и не свищу, когда горло не моё.",
            -2,
            -1,
            None,
            "spoke_watchman",
            None,
            None,
        ),
    )


def _apply_phase16(conn) -> None:
    """Речь и двойник идут в таблицу CoC, не капают SAN поверх бумаги."""
    conn.execute(
        """UPDATE dialogue_lines
           SET sanity_change = 0
           WHERE sets_flag = 'guilt_admitted'
              OR dialogue_id LIKE 'dialogue_possessed_%'
              OR dialogue_id LIKE 'dialogue_double_%'"""
    )


def _apply_map_links(conn) -> None:
    """Лестницы и выходы садятся на живые S/s/E, не на старый кроссворд 20 клеток в высоту."""
    conn.executemany(
        "UPDATE maps SET width = ?, height = ? WHERE id = ?",
        [
            (57, 12, "hospital_floor_1"),
            (57, 12, "hospital_floor_2"),
            (57, 12, "hospital_basement"),
            (60, 20, "street_outside"),
            (36, 14, "street_traktir"),
            (57, 12, "hospital_bred"),
            (48, 14, "street_tenement"),
        ],
    )
    conn.execute(
        """DELETE FROM map_connections
           WHERE source_map_id IN (
             'hospital_floor_1', 'hospital_floor_2', 'hospital_basement'
           )"""
    )

    floor1_up = (53, 6)
    floor1_down = (53, 6)
    to_floor1 = (53, 6)
    to_street = (1, 9)
    rows = []
    for x, y in ((51, 4), (51, 5)):
        rows.append(
            (
                "hospital_floor_1",
                "stairs_up",
                x,
                y,
                "hospital_floor_2",
                floor1_up[0],
                floor1_up[1],
                "Лестница на второй этаж",
            )
        )
    for x, y in ((53, 4), (53, 5)):
        rows.append(
            (
                "hospital_floor_1",
                "stairs_down",
                x,
                y,
                "hospital_basement",
                floor1_down[0],
                floor1_down[1],
                "Лестница в подвал",
            )
        )
    for x, y in ((56, 1), (56, 2)):
        rows.append(
            (
                "hospital_floor_1",
                "exit",
                x,
                y,
                "street_outside",
                to_street[0],
                to_street[1],
                "Выход на улицу",
            )
        )
    for x, y in ((51, 4), (51, 5), (53, 4), (53, 5)):
        rows.append(
            (
                "hospital_floor_2",
                "stairs_down",
                x,
                y,
                "hospital_floor_1",
                to_floor1[0],
                to_floor1[1],
                "Лестница вниз на первый этаж",
            )
        )
    for x, y in ((51, 4), (51, 5), (53, 4), (53, 5)):
        rows.append(
            (
                "hospital_basement",
                "stairs_up",
                x,
                y,
                "hospital_floor_1",
                to_floor1[0],
                to_floor1[1],
                "Лестница вверх на первый этаж",
            )
        )
    conn.executemany(
        """INSERT INTO map_connections
           (source_map_id, connection_type, source_x, source_y,
            target_map_id, target_x, target_y, description)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )


def _apply_palette(conn) -> None:
    """Предметы садятся на 18 чернил. Лишние глифы из старой таблицы — вон."""
    allowed = tuple(TILE_INKS.keys())
    holes = ",".join("?" * len(allowed))
    conn.execute(
        f"DELETE FROM tile_colors WHERE symbol NOT IN ({holes})",
        allowed,
    )
    conn.execute(
        f"DELETE FROM tile_colors_explored WHERE symbol NOT IN ({holes})",
        allowed,
    )
    conn.execute(
        "UPDATE items SET color = ? WHERE symbol IN ('≈', '~')",
        (INKS["paper"],),
    )
    conn.execute(
        "UPDATE items SET color = ? WHERE symbol IN ('!', ')')",
        (INKS["ochre"],),
    )
    conn.execute(
        "UPDATE items SET color = ? WHERE symbol = '+'",
        (INKS["rust"],),
    )
    _apply_class_voices(conn)


def _apply_class_voices(conn) -> None:
    """Занятия говорят по-человечески. Цифры кости не трогаем."""
    voices = {
        "rebel": (
            "Бунтарь",
            "Студент, или был студентом. Кулаки помнят больше, чем лекции, и стыдятся этого меньше.",
            {
                "name": "Ярость отчаяния",
                "description": "Удар тяжелеет на миг. Воля платит. Платит — и не спрашивает, стоило ли.",
                "san_cost": 5,
                "damage_bonus": 3,
                "duration": 1,
                "type": "combat_buff",
            },
        ),
        "seeker": (
            "Искатель",
            "Сыщик, или называл себя сыщиком. Видит шов, который прятали, и не умеет не видеть.",
            {
                "name": "Острый взгляд",
                "description": "Следующий удар идёт насквозь. Взгляд у вас злой. Злой — и точный.",
                "san_cost": 0,
                "crit_chance": 1.0,
                "duration": 1,
                "type": "critical_strike",
            },
        ),
        "mystic": (
            "Мистик",
            "Священник, или был. Слышит те голоса, от которых другие затыкают уши платком.",
            {
                "name": "Мистическое прозрение",
                "description": "Воля возвращается на миг. Бред не берёт, пока держитесь. Держитесь.",
                "san_restore": 10,
                "madness_immunity": True,
                "duration": 1,
                "type": "sanity_restore",
            },
        ),
    }
    for class_id, (name, description, ability) in voices.items():
        conn.execute(
            """UPDATE player_classes
               SET name = ?, description = ?, class_ability = ?
               WHERE id = ?""",
            (name, description, json.dumps(ability, ensure_ascii=False), class_id),
        )


def _apply_phase17(conn) -> None:
    """Доходный дом: туман ведёт сюда, не в титры."""
    conn.execute(
        """INSERT INTO maps (id, name, description, file_path, width, height,
                             min_sanity, max_sanity, is_starting_map)
           VALUES (?, ?, ?, ?, ?, ?, 0, 100, 0)
           ON CONFLICT(id) DO UPDATE SET
             name = excluded.name,
             description = excluded.description,
             file_path = excluded.file_path,
             width = excluded.width,
             height = excluded.height""",
        (
            "street_tenement",
            "Доходный дом",
            "Лавка под ночной лампой и квартира при ней. Здесь считают жильцов по долгам; ступени халат не любят.",
            "data/maps/tenement.txt",
            48,
            14,
        ),
    )
    conn.executemany(
        """DELETE FROM map_connections
           WHERE source_map_id = ? AND source_x = ? AND source_y = ?""",
        [
            ("street_outside", 58, 9),
            ("street_outside", 58, 10),
            ("street_tenement", 0, 6),
            ("street_tenement", 0, 7),
        ],
    )
    conn.executemany(
        """INSERT INTO map_connections
           (source_map_id, connection_type, source_x, source_y,
            target_map_id, target_x, target_y, description)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            ("street_outside", "entrance", 58, 9, "street_tenement", 1, 6,
             "Войти в доходный дом"),
            ("street_outside", "entrance", 58, 10, "street_tenement", 1, 7,
             "Войти в доходный дом"),
            ("street_tenement", "exit", 0, 6, "street_outside", 57, 9,
             "Выйти в туман"),
            ("street_tenement", "exit", 0, 7, "street_outside", 57, 10,
             "Выйти в туман"),
        ],
    )
    conn.executemany(
        """INSERT INTO map_regions
           (id, map_id, x1, y1, x2, y2, name, first_visit_text, sanity_effect)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             first_visit_text = excluded.first_visit_text,
             x1 = excluded.x1, y1 = excluded.y1, x2 = excluded.x2, y2 = excluded.y2,
             name = excluded.name, sanity_effect = excluded.sanity_effect""",
        [
            ("ten_seni", "street_tenement", 1, 1, 5, 12, "Сени",
             "Сени. С улицы — туман, из лавки — лампа и счёты.", 0),
            ("ten_shop", "street_tenement", 6, 1, 26, 12, "Лавка",
             "Прилавок. Лукин шепчет столбцам, как молитву.", 0),
            ("ten_apt", "street_tenement", 27, 1, 46, 4, "Квартира",
             "Квартира при лавке. Бюро помнит жильцов лучше хозяев.", -1),
            ("ten_kitchen", "street_tenement", 27, 6, 46, 8, "Кухня",
             "Кухня. Щи остыли на того, кого взяли на ночь.", -1),
            ("ten_stairs", "street_tenement", 27, 10, 46, 12, "Лестница",
             "Ступени чужие. Хозяин халат наверх не пускает — и правильно.", -1),
        ],
    )
    conn.execute(
        """UPDATE map_regions SET first_visit_text = ?
           WHERE id = 'st_fog'""",
        (
            "Дальше — каменный дом в вате. Без имени и долга вата сытая. Сытая — и не врёт.",
        ),
    )
    conn.execute(
        """UPDATE triggers SET text = ?
           WHERE id = 'trigger_fog'""",
        (
            "Туман густеет. Дальше дом — если есть имя и долг, не одно из двух.",
        ),
    )
    conn.execute(
        """INSERT INTO door_locks (map_id, x, y, required_key_id)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(map_id, x, y) DO UPDATE SET
             required_key_id = excluded.required_key_id""",
        ("street_tenement", 27, 2, "key_tenement"),
    )
    conn.execute(
        """INSERT INTO items
           (id, type, name, description, damage_die, healing, sanity_restore,
            sanity_damage, symbol, color, is_quest_item, use_effect, content)
           VALUES (?, 'note', ?, ?, '', 0, 0, -3, '≈', ?, 1, 'read_note', ?)
           ON CONFLICT(id) DO UPDATE SET
             content = excluded.content,
             name = excluded.name,
             description = excluded.description""",
        (
            "note_tenement",
            "Домовая книга",
            "Список жильцов. Клеёнка, запах щей, графы стыдятся гласных.",
            INKS["paper"],
            "Иванов выехал. Кто-то «взят в заведение на ночь» — имя смазали пальцем, до дыры, нарочно. "
            "На полях мелко, стыдно: лизаветка, будто не для управы. Вашей графы нет. "
            "Книжка не архив и не канал: она считает, кого нет.",
        ),
    )
    conn.execute(
        """INSERT INTO items
           (id, type, name, description, damage_die, healing, sanity_restore,
            sanity_damage, symbol, color, is_quest_item, use_effect, content)
           VALUES (?, 'key', ?, ?, '', 0, 0, 0, ')', ?, 1, NULL, NULL)
           ON CONFLICT(id) DO UPDATE SET
             name = excluded.name,
             description = excluded.description""",
        (
            "key_tenement",
            "Ключ от квартиры",
            "На бечёвке, от квартиры при лавке. Носили в шкафу, не в кармане халата.",
            INKS["ochre"],
        ),
    )
    conn.executemany(
        """INSERT INTO map_placements (map_id, x, y, spawn_type, spawn_id)
           VALUES (?, ?, ?, ?, ?)""",
        [
            ("street_tenement", 10, 4, "character", "shopkeeper_lukin"),
            ("street_tenement", 32, 3, "character", "landlady_praskovya"),
        ],
    )
    _upsert_npc(conn, (
        "shopkeeper_lukin", "npc", "Лукин", "Лавочник",
        "Лампа в лице, счёты в пальцах. Жильцов считает громче крупы.",
        8, 10, 0, "1d4", 10, 10, 12, 10, 12, "dialogue", 0, "city",
        "&", INKS["brass"], "dialogue_lukin_intro",
    ))
    _upsert_npc(conn, (
        "landlady_praskovya", "npc", "Прасковья", "Хозяйка при лавке",
        "Платок накрест. Ключей на поясе нет — держит взглядом.",
        8, 10, 0, "1d4", 10, 10, 10, 10, 12, "dialogue", 0, "city",
        "&", "#b09080", "dialogue_praskovya_intro",
    ))
    _seed_city_dialogue(
        conn,
        "dialogue_lukin_intro",
        "shopkeeper_lukin",
        "dialogue_lukin_repeat",
        [
            (1, "npc", "Ночь, лампа, жильцы. Жильцы и должники — одно лицо, да-с. Халат вижу. Графы вашей нет. Нет — и я не подскажу. Лавка не архив.", 0, 10, None, None, None),
            (10, "player", "Вы меня знаете? Имя, Лукин. Хоть клочок.", 0, 20, 1, None, None),
            (11, "player", "Квартира при лавке. Кто там живёт? Скажите.", 0, 30, 1, None, None),
            (12, "player", "Я жилец. Ключ дома, вот что. Отдайте — или скажите, где лежит.", 0, 40, 1, None, None),
            (13, "player", "На прилавке протёрто, куда кладут ключи. Не в карман. Куда?", 0, 50, 1, None, None, "class_seeker"),
            (14, "player", "Счёты щёлкают имя, и ласковое. Чьё? Вслух не называйте.", -2, 51, 1, None, None, "class_mystic"),
            (15, "player", "Ящик открыт. Отдайте ключ. Не просите дважды.", 0, 52, 1, None, None, "class_rebel"),
            (20, "npc", "Лица знаю. Имена — по книжке, а книжка не ваша. Не ваша, слышите? Я лавочник, не архивариус. Архивариус имена выдаёт. Я — счёты. Счёты, сударь.", 0, -1, None, "spoke_lukin", None),
            (30, "npc", "При лавке квартира, да. Прасковья держит. Ключик-то жильцы в шкафу кладут, не в карман — карман врёт, шкаф тише. Я не сторож шкафа. Я считаю. Считаю, и всё.", 0, -1, None, "spoke_lukin", None),
            (40, "npc", "Жилец... ну жилец. Ключ в шкафу при квартире, не в халате. Берите, коли ваш. Я графы считаю, не карманы.", 0, -1, None, "spoke_lukin", None),
            (41, "npc", "Не верю-с. Жилец ключ носит, а не выпрашивает. Халат ваш ключей не держал: пустота в нём ночевала, не правда. Ступайте. Лавка лжи не меняет.", -2, -1, None, "spoke_lukin", None),
            (50, "npc", "Верно, не в карман. В шкаф. Шкаф молчит лучше жильцов. Лучше, да-с. Фамилии на прилавке нет — и не будет. Не спрашивайте.", 0, -1, None, "spoke_lukin", None),
            (51, "npc", "Не берите. Кто отзовётся на дробь — того в графу, как должника. Как должника, сударь. Я уж занёс многих. Многих.", -3, -1, None, "spoke_lukin", None),
            (52, "npc", "Открыт, потому что запирают не ящик. Ключ — не вам. Плечо шкаф знает, да. Знает — и стыдится. Стыдится, вот что.", 0, -1, None, "spoke_lukin", None),
        ],
        [
            (1, "npc", "Имя и долг. Счёты сыты, даже слишком. Идите к Прасковье — она двери считает, я — графы. Графы, сударь.", 0, 10, None, None, None, "has_both"),
            (2, "npc", "Назвались. Долг ещё в столбце. Столбец, видите ли, упрямый.", 0, 10, None, None, None, "has_name"),
            (3, "npc", "Лизавете должны. Безымянных в книжку не ставят. Не ставят — и правильно.", 0, 10, None, None, None, "guilt_admitted"),
            (4, "npc", "Настасье должны выход. Безымянных в книжку не ставят. Книжка брезглива, да-с.", 0, 10, None, None, None, "nastasya_escape"),
            (5, "npc", "Лампа всё та же. Графа — тоже. Вы — нет. Нет, и хорошо ли это? Не знаю.", 0, 10, None, None, None),
            (10, "player", "Где ключ от квартиры?", 0, 20, 1, None, None),
            (11, "player", "Кто в графе должников?", 0, 30, 1, None, None),
            (12, "player", "Пустите наверх.", 0, 40, 1, None, None),
            (13, "player", "Я назвался. Ключ, Лукин.", 0, 50, 1, None, None, "has_name"),
            (14, "player", "Лизавете. Этого мало для лавки?", 0, 51, 1, None, None, "guilt_admitted"),
            (15, "player", "Настасье выход. Пустите к хозяйке.", 0, 52, 1, None, None, "nastasya_escape"),
            (20, "npc", "В шкафу, где кладут жильцы. Не в кармане. Я ключ не выдаю — я считаю. Считаю, и всё.", 0, -1, None, None, None),
            (30, "npc", "Кто не платит. И кто взят в заведение на ночь. Имя смазали. Смазали, нарочно. Я не архив. Не спрашивайте.", 0, -1, None, None, None),
            (40, "npc", "Ступени чужие. Халат наверх не пускаю. Не пускаю, и совесть тут ни при чём — или как раз при чём. Как раз, да-с.", 0, -1, None, None, None),
            (50, "npc", "Мало. Счёты слушают два слова. Вы сказали одно. Одно, и лампа обижается.", 0, -1, None, None, None),
            (51, "npc", "Лизавете мало без имени. Лавка кредита не даёт. Не даёт, ей-богу.", 0, -1, None, None, None),
            (52, "npc", "Настасье — дверь. Счётам — фамилия. Иначе халат. Халат, сударь, не жилец.", 0, -1, None, None, None),
        ],
    )
    _seed_city_dialogue(
        conn,
        "dialogue_praskovya_intro",
        "landlady_praskovya",
        "dialogue_praskovya_repeat",
        [
            (1, "npc", "Батюшка... халат в моей квартире? Я лиц держу, не ткани. Вашего в книжке нет. Нет — и на улицу не пущу. Пустых не выпускаю. Пустых город не берёт — и я тоже.", 0, 10, None, None, None),
            (10, "player", "Кто я? Вы же видите лица. Скажите.", 0, 20, 1, None, None),
            (11, "player", "Пустите на улицу. Прошу. Улица, слышите?", 0, 30, 1, None, None),
            (12, "player", "Кого взяли в заведение? В книжке крест. Чей?", -2, 40, 1, None, None),
            (13, "player", "Чернила свежие там, где вычеркивают. Это я? Скажите.", 0, 50, 1, None, None, "class_seeker"),
            (14, "player", "Книжка зовёт по-домашнему, как своя. Не вас — или вас? Не отвечайте, если нельзя.", -2, 51, 1, None, None, "class_mystic"),
            (15, "player", "Дверь на чести. Честь я не спрашиваю. Пустите.", 0, 52, 1, None, None, "class_rebel"),
            (20, "npc", "Вижу. Знать — не скажу. Имя в архиве, не у хозяйки. Хозяйка держит комнату, не душу. Душу, сударь, вы сами засидели. Сами.", -2, -1, None, "spoke_praskovya", None),
            (30, "npc", "Без имени и без долга — никак. Никак, голубчик. Туман сытый, я сытее. Сытее, потому что кормлю жильцов и не выпускаю пустых. Пустых — обратно в халат.", 0, -1, None, "spoke_praskovya", None),
            (40, "npc", "Взяли на ночь. Имя смазали пальцем — нарочно, стыдно писать вслух. Я лиц долга знаю: кто Лизавете, кто Настасье. Вашего креста вслух не будет. Не будет, пока сами не совпадёте с бумагой.", -2, -1, None, "spoke_praskovya", None),
            (50, "npc", "Дата свежая. Фамилия — дыра. Дыра, батюшка. Подпишите себя не у меня: я книжку веду, не архив. Здесь щи и долги. Щи, сударь.", 0, -1, None, "spoke_praskovya", None),
            (51, "npc", "Правильно, что боитесь. Кто отзовётся — того в графу, как того, кого взяли на ночь. На ночь, слышите? Ласковым именем в дом не входят.", -3, -1, None, "spoke_praskovya", None),
            (52, "npc", "Честь дешевле плеча, да. Плечо дверь знает. Я всё равно держу. Держу безымянных. Безымянных и без долга. Ключик — не свобода. Свобода — два слова, вместе.", 0, -1, None, "spoke_praskovya", None),
        ],
        [
            (1, "npc", "Имя и долг. Книжка сыта. Идите, пока я ещё хозяйка, а не вата. Пока — это ненадолго, батюшка.", 0, 10, None, None, None, "has_both"),
            (2, "npc", "Назвались. Долг ещё в сенях ходит. Ходит, как жилец, которому стыдно стучать.", 0, 10, None, None, None, "has_name"),
            (3, "npc", "Лизавете должны. Безымянных я в город не пускаю. Не пускаю — и крещусь.", 0, 10, None, None, None, "guilt_admitted"),
            (4, "npc", "Настасье должны выход. Безымянных я в город не пускаю. Город, видите ли, брезглив.", 0, 10, None, None, None, "nastasya_escape"),
            (5, "npc", "Опять халат. Книжка не сдвинулась. Не сдвинулась — и я тоже.", 0, 10, None, None, None),
            (10, "player", "Куда теперь, если не в квартиру?", 0, 20, 1, None, None),
            (11, "player", "Кто в книжке с крестом?", 0, 30, 1, None, None),
            (12, "player", "Лукин считает. Вы — держите. Зачем?", 0, 40, 1, None, None),
            (13, "player", "Я назвался. Пустите в город.", 0, 50, 1, None, None, "has_name"),
            (14, "player", "Лизавете. Этого мало, Прасковья?", 0, 51, 1, None, None, "guilt_admitted"),
            (15, "player", "Настасье выход. Пустите.", 0, 52, 1, None, None, "nastasya_escape"),
            (16, "player", "Пустите. Имя есть, долг есть. В город. Довольно вашей книжки.", 0, 53, 1, None, None, "has_both"),
            (20, "npc", "На улицу — коли имя и долг при вас. Нет — сидите. Сидеть, батюшка, тоже честно. Честнее побега в халате.", 0, -1, None, None, None),
            (30, "npc", "Крест на ночь. Имя смазали. Я не скажу. Сказать — всё равно что выпустить без книжки. Без книжки, голубчик.", 0, -1, None, None, None),
            (40, "npc", "Он считает копейки. Я — лица. Лица, которые должны. Халат без лица — не жилец. Не жилец — и не город.", 0, -1, None, None, None),
            (50, "npc", "Мало. Книжка слушает два слова. Вы сказали одно. Одно, и ступени чужие.", 0, -1, None, None, None),
            (51, "npc", "Лизавете мало без имени. Канал знает её. Я вас ещё не знаю — и в этом вся квартира.", 0, -1, None, None, None),
            (52, "npc", "Настасье — дверь. Книжке — фамилия. Иначе халат. Халат, батюшка, не паспорт.", 0, -1, None, None, None),
            (53, "npc", "Идите же. Мостовая. Я держала — теперь сами. Сами, батюшка. Город не добрее квартиры. Только честнее, да-с. Честнее — и холоднее.", 0, -1, None, None, "flee"),
        ],
    )
    conn.execute(
        """UPDATE dialogue_lines
           SET skill_id = 'talk', fail_next_order = 41
           WHERE dialogue_id = 'dialogue_lukin_intro' AND order_num = 12"""
    )


def _apply_phase18(conn) -> None:
    """В выборе видно умение и ложь, как в диалоге с проверкой."""
    _ensure_column(conn, "dialogue_lines", "is_lie", "INTEGER")
    conn.executemany(
        """UPDATE dialogue_lines SET is_lie = 1
           WHERE dialogue_id = ? AND order_num = ?""",
        (
            ("dialogue_watchman_intro", 10),
            ("dialogue_beggar_intro", 11),
            ("dialogue_lukin_intro", 12),
            ("dialogue_shpilkin_intro", 11),
        ),
    )


def _apply_phase19(conn) -> None:
    """Успех кости даёт другой ответ, не тот же отказ."""
    conn.executemany(
        """UPDATE dialogue_lines SET text = ?
           WHERE dialogue_id = ? AND order_num = ? AND speaker = 'npc'""",
        (
            (
                "Халат вижу. Болезнь — как скажете. Ступайте. Свисток пока молчит. "
                "В журнал не внесу: нет фамилии — нет строки.",
                "dialogue_watchman_intro",
                20,
            ),
            (
                "Иван так Иван. Стена сыта любым именем. На восток — лавка, если жилец. "
                "Архив я не держу. Не держу, да-с.",
                "dialogue_beggar_intro",
                30,
            ),
            (
                "Жилец... ну жилец. Ключ в шкафу при квартире, не в халате. "
                "Берите, коли ваш. Я графы считаю, не карманы.",
                "dialogue_lukin_intro",
                40,
            ),
            (
                "Не болен? Тогда капель не берите. Улица вас ещё не списала. "
                "Запишу отказ. Отказ тоже история.",
                "dialogue_shpilkin_intro",
                30,
            ),
            (
                "Как скажете. Назовём бредом — они тише, ненадолго. "
                "Ненадолго, слышите? Потом снова шепчут.",
                "dialogue_nastasya_intro",
                30,
            ),
        ),
    )
    conn.execute(
        """DELETE FROM dialogue_lines
           WHERE (dialogue_id = 'dialogue_shpilkin_intro' AND order_num = 31)
              OR (dialogue_id = 'dialogue_nastasya_intro' AND order_num = 31)"""
    )
    conn.executemany(
        """INSERT INTO dialogue_lines
           (dialogue_id, order_num, speaker, text, sanity_change, next_order,
            choice_group, sets_flag, ending_id, requires_flag)
           VALUES (?, ?, 'npc', ?, ?, -1, NULL, ?, NULL, NULL)""",
        (
            (
                "dialogue_shpilkin_intro",
                31,
                "Все так говорят в первую ночь. Все. Потом просят капли. "
                "Страх — хороший признак: значит, ещё не тень.",
                -3,
                "spoke_shpilkin",
            ),
            (
                "dialogue_nastasya_intro",
                31,
                "Это не бред. Бред не знает имён. Они знают. Даже те, которых нет. Особенно те.",
                -5,
                "spoke_nastasya",
            ),
        ),
    )
    conn.execute(
        """UPDATE dialogue_lines
           SET skill_id = 'talk', fail_next_order = 31, is_lie = 1
           WHERE dialogue_id = 'dialogue_shpilkin_intro' AND order_num = 11"""
    )
    conn.execute(
        """UPDATE dialogue_lines
           SET skill_id = 'talk', fail_next_order = 31
           WHERE dialogue_id = 'dialogue_nastasya_intro' AND order_num = 11"""
    )


def _ensure_items_clothing(conn) -> None:
    """Одежда в CHECK и слот на вещи. Без rebuild INSERT халата падает."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='items'"
    ).fetchone()
    sql = (row[0] if row else "") or ""
    cols = [entry[1] for entry in conn.execute("PRAGMA table_info(items)")]
    if "clothing" not in sql:
        conn.execute(
            """
            CREATE TABLE items_new (
                id TEXT PRIMARY KEY,
                type TEXT CHECK(type IN (
                    'weapon', 'consumable', 'quest', 'note', 'key', 'clothing'
                )),
                name TEXT NOT NULL,
                description TEXT,
                damage_die TEXT,
                healing INTEGER DEFAULT 0,
                sanity_restore INTEGER DEFAULT 0,
                sanity_damage INTEGER DEFAULT 0,
                symbol TEXT DEFAULT '?',
                color TEXT DEFAULT '#FFFFFF',
                is_quest_item INTEGER DEFAULT 0,
                use_effect TEXT,
                content TEXT DEFAULT '',
                equip_slot TEXT,
                look TEXT
            )
            """
        )
        shared = [col for col in cols if col != "equip_slot"]
        listed = ", ".join(shared)
        conn.execute(f"INSERT INTO items_new ({listed}) SELECT {listed} FROM items")
        conn.execute("DROP TABLE items")
        conn.execute("ALTER TABLE items_new RENAME TO items")
        cols = [entry[1] for entry in conn.execute("PRAGMA table_info(items)")]
    if "equip_slot" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN equip_slot TEXT")
    if "look" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN look TEXT")


def _apply_phase20(conn) -> None:
    """Халат — вещь на тело. Сюртук в шкафу квартиры. Слоты как в ролевой."""
    _ensure_items_clothing(conn)
    conn.execute(
        """INSERT INTO items
           (id, type, name, description, damage_die, healing, sanity_restore,
            sanity_damage, symbol, color, is_quest_item, use_effect, content,
            equip_slot)
           VALUES (?, 'clothing', ?, ?, '', 0, 0, 0, '~', ?, 0, NULL, NULL, 'body')
           ON CONFLICT(id) DO UPDATE SET
             type = excluded.type,
             name = excluded.name,
             description = excluded.description,
             color = excluded.color,
             equip_slot = excluded.equip_slot""",
        (
            "item_robe",
            "Халат клиники",
            "Казённый. Снимают, когда есть своё.",
            INKS["linen"],
        ),
    )
    conn.execute(
        """INSERT INTO items
           (id, type, name, description, damage_die, healing, sanity_restore,
            sanity_damage, symbol, color, is_quest_item, use_effect, content,
            equip_slot)
           VALUES (?, 'clothing', ?, ?, '', 0, 0, 0, '~', ?, 1, NULL, NULL, 'body')
           ON CONFLICT(id) DO UPDATE SET
             type = excluded.type,
             name = excluded.name,
             description = excluded.description,
             color = excluded.color,
             is_quest_item = excluded.is_quest_item,
             equip_slot = excluded.equip_slot""",
        (
            "item_coat",
            "Сюртук",
            "Ваш, с гвоздя в шкафу квартиры. Не халат.",
            INKS["ash"],
        ),
    )
    conn.execute(
        "UPDATE items SET equip_slot = 'main_hand' WHERE id = 'item_knife'"
    )
    for class_id, raw in conn.execute("SELECT id, starting_items FROM player_classes"):
        try:
            items = json.loads(raw) if raw else []
        except (TypeError, json.JSONDecodeError):
            items = []
        if not isinstance(items, list):
            items = []
        if "item_robe" in items:
            continue
        items.insert(0, "item_robe")
        conn.execute(
            "UPDATE player_classes SET starting_items = ? WHERE id = ?",
            (json.dumps(items, ensure_ascii=False), class_id),
        )


def _apply_phase21(conn) -> None:
    """Вид одежды читается. Память — тёплый флаг, не метр."""
    _ensure_column(conn, "items", "look", "TEXT")
    conn.execute("UPDATE items SET look = 'clinic' WHERE id = 'item_robe'")
    conn.execute("UPDATE items SET look = 'tenant' WHERE id = 'item_coat'")
    conn.executemany(
        """UPDATE dialogue_lines SET requires_flag = ?
           WHERE dialogue_id = ? AND order_num = ? AND speaker = 'npc'""",
        (
            ("look_clinic", "dialogue_watchman_intro", 1),
            ("look_clinic", "dialogue_lukin_intro", 1),
            ("look_clinic", "dialogue_praskovya_intro", 1),
            ("look_clinic", "dialogue_watchman_repeat", 5),
            ("look_clinic", "dialogue_lukin_repeat", 5),
            ("look_clinic", "dialogue_praskovya_repeat", 5),
        ),
    )
    conn.executemany(
        """DELETE FROM dialogue_lines
           WHERE dialogue_id = ? AND order_num = ?""",
        (
            ("dialogue_watchman_intro", 2),
            ("dialogue_watchman_intro", 3),
            ("dialogue_lukin_intro", 2),
            ("dialogue_lukin_intro", 3),
            ("dialogue_praskovya_intro", 2),
            ("dialogue_praskovya_intro", 3),
            ("dialogue_watchman_repeat", 0),
            ("dialogue_watchman_repeat", 6),
            ("dialogue_watchman_repeat", 7),
            ("dialogue_lukin_repeat", 0),
            ("dialogue_lukin_repeat", 6),
            ("dialogue_lukin_repeat", 7),
            ("dialogue_praskovya_repeat", 0),
            ("dialogue_praskovya_repeat", 6),
            ("dialogue_praskovya_repeat", 7),
        ),
    )
    conn.executemany(
        """INSERT INTO dialogue_lines
           (dialogue_id, order_num, speaker, text, sanity_change, next_order,
            choice_group, sets_flag, ending_id, requires_flag)
           VALUES (?, ?, 'npc', ?, 0, ?, NULL, NULL, NULL, ?)""",
        (
            (
                "dialogue_watchman_intro",
                2,
                "Сюртук вижу. Фамилии вашей не слышу, а без фамилии мне и "
                "записать нечего. Ступайте.",
                10,
                "look_tenant",
            ),
            (
                "dialogue_watchman_intro",
                3,
                "Голый, сударь: ни больной, ни жилец. Оденьтесь, покуда я добрый.",
                10,
                "look_bare",
            ),
            (
                "dialogue_lukin_intro",
                2,
                "Сюртук — стало быть, жилец-с. Только в книге моей вас нет, "
                "и подсказать мне нечего.",
                10,
                "look_tenant",
            ),
            (
                "dialogue_lukin_intro",
                3,
                "Ни халата, ни сюртука. Нагишом в лавку не ходят, сударь, — "
                "оденьтесь и приходите.",
                10,
                "look_bare",
            ),
            (
                "dialogue_praskovya_intro",
                2,
                "Сюртук из моей квартиры, ткань знаю. А имени вашего в книжке нет — "
                "без имени и без долгу на улицу не пущу.",
                10,
                "look_tenant",
            ),
            (
                "dialogue_praskovya_intro",
                3,
                "Батюшка, прикройтесь. Голого я в город не выпущу — накиньте хоть казённое.",
                10,
                "look_bare",
            ),
            (
                "dialogue_watchman_repeat",
                0,
                "Вас я уже видел: лицо помню, фамилию — нет. Ступайте, Петров нынче добрый.",
                10,
                "warm_watchman_petrov",
            ),
            (
                "dialogue_watchman_repeat",
                6,
                "Сюртук тот же, фамилии всё нет. Ступайте.",
                10,
                "look_tenant",
            ),
            (
                "dialogue_watchman_repeat",
                7,
                "Опять без ткани. Оденьтесь, сударь: свисток недолго молчит.",
                10,
                "look_bare",
            ),
            (
                "dialogue_lukin_repeat",
                0,
                "Шаг ваш узнаю. Имени так и не знаю, а шаг узнаю.",
                10,
                "warm_shopkeeper_lukin",
            ),
            (
                "dialogue_lukin_repeat",
                6,
                "Сюртук тот же. Вы чуть меньше чужой, да-с.",
                10,
                "look_tenant",
            ),
            (
                "dialogue_lukin_repeat",
                7,
                "Опять нагишом. Прикройтесь, тут за крупой ходят.",
                10,
                "look_bare",
            ),
            (
                "dialogue_praskovya_repeat",
                0,
                "Вас я держала и держу. Имя да про долг — тогда и поговорим.",
                10,
                "warm_landlady_praskovya",
            ),
            (
                "dialogue_praskovya_repeat",
                6,
                "Опять сюртук, а в книжке всё то же. Сидите, батюшка.",
                10,
                "look_tenant",
            ),
            (
                "dialogue_praskovya_repeat",
                7,
                "Опять без ткани. У меня жильцы, батюшка, оденьтесь.",
                10,
                "look_bare",
            ),
        ),
    )


def _apply_phase22(conn) -> None:
    """Нож виден. Лукин отказывает речью, не новым замком."""
    conn.execute(
        """UPDATE dialogue_lines SET requires_flag = 'look_tenant'
           WHERE dialogue_id = 'dialogue_lukin_repeat'
             AND order_num = 20 AND speaker = 'npc'"""
    )
    conn.execute(
        """UPDATE dialogue_lines SET requires_flag = 'look_clinic'
           WHERE dialogue_id = 'dialogue_lukin_repeat'
             AND order_num = 40 AND speaker = 'npc'"""
    )
    conn.executemany(
        """DELETE FROM dialogue_lines
           WHERE dialogue_id = ? AND order_num = ?""",
        (
            ("dialogue_watchman_intro", 0),
            ("dialogue_lukin_intro", 0),
            ("dialogue_praskovya_intro", 0),
            ("dialogue_panteleimon_intro", 0),
            ("dialogue_panteleimon_repeat", 0),
            ("dialogue_watchman_repeat", 8),
            ("dialogue_lukin_repeat", 8),
            ("dialogue_praskovya_repeat", 8),
            ("dialogue_lukin_repeat", 21),
            ("dialogue_lukin_repeat", 22),
            ("dialogue_lukin_repeat", 23),
            ("dialogue_lukin_repeat", 24),
            ("dialogue_lukin_repeat", 25),
            ("dialogue_lukin_repeat", 41),
            ("dialogue_lukin_repeat", 42),
            ("dialogue_lukin_repeat", 43),
            ("dialogue_lukin_repeat", 44),
            ("dialogue_lukin_repeat", 45),
        ),
    )
    conn.executemany(
        """INSERT INTO dialogue_lines
           (dialogue_id, order_num, speaker, text, sanity_change, next_order,
            choice_group, sets_flag, ending_id, requires_flag)
           VALUES (?, ?, 'npc', ?, 0, ?, NULL, NULL, NULL, ?)""",
        (
            (
                "dialogue_watchman_intro",
                0,
                "Нож вижу прежде всякой ткани. Спрячьте, покуда свисток молчит.",
                10,
                "armed",
            ),
            (
                "dialogue_lukin_intro",
                0,
                "Нож вижу раньше сюртука. Спрячьте, сударь, у меня тут крупу берут.",
                10,
                "armed",
            ),
            (
                "dialogue_praskovya_intro",
                0,
                "Нож в моей квартире? Спрячьте сейчас же, батюшка, у меня жильцы.",
                10,
                "armed",
            ),
            (
                "dialogue_panteleimon_intro",
                0,
                "Нож, барин... Уберите, Христа ради. Я ничего не видел.",
                10,
                "armed",
            ),
            (
                "dialogue_panteleimon_repeat",
                0,
                "Опять нож, барин. Я ничего не говорил — уберите.",
                10,
                "armed",
            ),
            (
                "dialogue_watchman_repeat",
                8,
                "Опять нож. Лицо я помню, а руку вашу помнить не хочу. Спрячьте.",
                10,
                "armed",
            ),
            (
                "dialogue_lukin_repeat",
                8,
                "Опять железо. Шаг ваш помню, а нож мне ни к чему.",
                10,
                "armed",
            ),
            (
                "dialogue_praskovya_repeat",
                8,
                "Опять нож. Спрячьте, батюшка, или сидите как сидели.",
                10,
                "armed",
            ),
            (
                "dialogue_lukin_repeat",
                21,
                "Халату не торгую-с. Ключ не товар, батюшка, — унесите, откуда взяли.",
                -1,
                "look_clinic",
            ),
            (
                "dialogue_lukin_repeat",
                22,
                "Нагишом ключа не дам. Оденьтесь, тогда и говорите.",
                -1,
                "look_bare",
            ),
            (
                "dialogue_lukin_repeat",
                23,
                "Ключ в шкафу, куда жильцы кладут. Только железо сперва спрячьте.",
                -1,
                "look_tenant_armed",
            ),
            (
                "dialogue_lukin_repeat",
                24,
                "Халату с ножом не торгую-с. Ступайте, батюшка.",
                -1,
                "look_clinic_armed",
            ),
            (
                "dialogue_lukin_repeat",
                25,
                "Голый, да ещё с ножом. Ступайте, сударь, покуда я молчу.",
                -1,
                "look_bare_armed",
            ),
            (
                "dialogue_lukin_repeat",
                41,
                "Сюртук ваш — ступайте наверх, ключ в шкафу. Я вам не провожатый-с.",
                -1,
                "look_tenant",
            ),
            (
                "dialogue_lukin_repeat",
                42,
                "Голым на чужую лестницу? Оденьтесь хоть в казённое, тогда и наверх.",
                -1,
                "look_bare",
            ),
            (
                "dialogue_lukin_repeat",
                43,
                "Халат да нож. С железом наверх не пущу, и не просите.",
                -1,
                "look_clinic_armed",
            ),
            (
                "dialogue_lukin_repeat",
                44,
                "Сюртук ваш, а нож уберите. Тогда и к шкафу — не ко мне.",
                -1,
                "look_tenant_armed",
            ),
            (
                "dialogue_lukin_repeat",
                45,
                "Голый и с ножом. Прикройтесь, железо спрячьте — после поговорим.",
                -1,
                "look_bare_armed",
            ),
        ),
    )


def _apply_phase23(conn) -> None:
    """Нож, ключ, записка — ветка в разговоре, не бонус к говорить."""
    conn.executemany(
        """DELETE FROM dialogue_lines
           WHERE dialogue_id = ? AND order_num = ?""",
        (
            ("dialogue_lukin_intro", 16),
            ("dialogue_lukin_intro", 17),
            ("dialogue_lukin_intro", 18),
            ("dialogue_lukin_intro", 60),
            ("dialogue_lukin_intro", 61),
            ("dialogue_lukin_intro", 62),
            ("dialogue_lukin_repeat", 16),
            ("dialogue_lukin_repeat", 17),
            ("dialogue_lukin_repeat", 18),
            ("dialogue_lukin_repeat", 60),
            ("dialogue_lukin_repeat", 61),
            ("dialogue_lukin_repeat", 62),
            ("dialogue_praskovya_intro", 16),
            ("dialogue_praskovya_intro", 17),
            ("dialogue_praskovya_intro", 60),
            ("dialogue_praskovya_intro", 61),
            ("dialogue_praskovya_repeat", 17),
            ("dialogue_praskovya_repeat", 18),
            ("dialogue_praskovya_repeat", 60),
            ("dialogue_praskovya_repeat", 61),
            ("dialogue_panteleimon_intro", 16),
            ("dialogue_panteleimon_intro", 17),
            ("dialogue_panteleimon_intro", 60),
            ("dialogue_panteleimon_intro", 61),
            ("dialogue_panteleimon_repeat", 17),
            ("dialogue_panteleimon_repeat", 18),
            ("dialogue_panteleimon_repeat", 60),
            ("dialogue_panteleimon_repeat", 61),
        ),
    )
    conn.executemany(
        """INSERT INTO dialogue_lines
           (dialogue_id, order_num, speaker, text, sanity_change, next_order,
            choice_group, sets_flag, ending_id, requires_flag)
           VALUES (?, ?, ?, ?, 0, ?, ?, ?, NULL, ?)""",
        (
            (
                "dialogue_lukin_intro",
                16,
                "player",
                "Кладу нож на прилавок. Не в вас, Лукин, — на дерево.",
                60,
                1,
                None,
                "have_item_knife",
            ),
            (
                "dialogue_lukin_intro",
                17,
                "player",
                "Вот ключ от квартиры. Из шкафа, как сказали.",
                61,
                1,
                None,
                "have_key_tenement",
            ),
            (
                "dialogue_lukin_intro",
                18,
                "player",
                "Бумага с канала. Лизавета. Это долг, Лукин.",
                62,
                1,
                None,
                "have_note_canal",
            ),
            (
                "dialogue_lukin_intro",
                60,
                "npc",
                "Уберите железо, сударь. Халату за нож не плачу-с.",
                -1,
                None,
                "spoke_lukin",
                None,
            ),
            (
                "dialogue_lukin_intro",
                61,
                "npc",
                "Ключ вижу-с, а вас в книге моей нет. Несите Прасковье, ключ её.",
                -1,
                None,
                "spoke_lukin",
                None,
            ),
            (
                "dialogue_lukin_intro",
                62,
                "npc",
                "Канал мне не лавка-с. Долг этот Лизаветин, батюшка, — с ним не ко мне.",
                -1,
                None,
                "spoke_lukin",
                None,
            ),
            (
                "dialogue_lukin_repeat",
                16,
                "player",
                "Кладу нож на прилавок. Опять. Смотрите.",
                60,
                1,
                None,
                "have_item_knife",
            ),
            (
                "dialogue_lukin_repeat",
                17,
                "player",
                "Вот ключ от квартиры. Из шкафа.",
                61,
                1,
                None,
                "have_key_tenement",
            ),
            (
                "dialogue_lukin_repeat",
                18,
                "player",
                "Бумага с канала. Лизавета. Долг.",
                62,
                1,
                None,
                "have_note_canal",
            ),
            (
                "dialogue_lukin_repeat",
                60,
                "npc",
                "Опять нож. Уберите, сударь, не куплю-с.",
                -1,
                None,
                None,
                None,
            ),
            (
                "dialogue_lukin_repeat",
                61,
                "npc",
                "Ключ тот же. Я его не выдавал — несите Прасковье.",
                -1,
                None,
                None,
                None,
            ),
            (
                "dialogue_lukin_repeat",
                62,
                "npc",
                "Опять бумага. В долг не даю-с, и чужого долга не беру.",
                -1,
                None,
                None,
                None,
            ),
            (
                "dialogue_praskovya_intro",
                16,
                "player",
                "Ключ квартиры. Вот он. Пустите — или скажите, кто я.",
                60,
                1,
                None,
                "have_key_tenement",
            ),
            (
                "dialogue_praskovya_intro",
                17,
                "player",
                "Записка с канала. Лизавете. Долг на бумаге, не в книжке.",
                61,
                1,
                None,
                "have_note_canal",
            ),
            (
                "dialogue_praskovya_intro",
                60,
                "npc",
                "Ключ без лица, батюшка. Мне имя надобно: имени нет — сидите.",
                -1,
                None,
                "spoke_praskovya",
                None,
            ),
            (
                "dialogue_praskovya_intro",
                61,
                "npc",
                "Бумага — не имя, батюшка. Долг свой скажите сами, а канал не моя забота.",
                -1,
                None,
                "spoke_praskovya",
                None,
            ),
            (
                "dialogue_praskovya_repeat",
                17,
                "player",
                "Ключ квартиры. Вот он опять.",
                60,
                1,
                None,
                "have_key_tenement",
            ),
            (
                "dialogue_praskovya_repeat",
                18,
                "player",
                "Записка с канала. Лизавете. Опять.",
                61,
                1,
                None,
                "have_note_canal",
            ),
            (
                "dialogue_praskovya_repeat",
                60,
                "npc",
                "Опять ключ. В книжке всё то же, батюшка.",
                -1,
                None,
                None,
                None,
            ),
            (
                "dialogue_praskovya_repeat",
                61,
                "npc",
                "Опять бумага. Сперва имя, потом улица.",
                -1,
                None,
                None,
                None,
            ),
            (
                "dialogue_panteleimon_intro",
                16,
                "player",
                "Бумага. С канала. Лизавета. Вы знаете.",
                60,
                1,
                None,
                "have_note_canal",
            ),
            (
                "dialogue_panteleimon_intro",
                17,
                "player",
                "Кладу нож. Не вас резать. Видите.",
                61,
                1,
                None,
                "have_item_knife",
            ),
            (
                "dialogue_panteleimon_intro",
                60,
                "npc",
                "Бумагу видел, барин. Только я вам ничего не говорил — ни про канал, "
                "ни про Лизавету.",
                -1,
                None,
                "spoke_panteleimon",
                None,
            ),
            (
                "dialogue_panteleimon_intro",
                61,
                "npc",
                "Не доставайте его при мне, барин. После железа тут ключи прячут.",
                -1,
                None,
                "spoke_panteleimon",
                None,
            ),
            (
                "dialogue_panteleimon_repeat",
                17,
                "player",
                "Бумага с канала. Опять. Лизавета.",
                60,
                1,
                None,
                "have_note_canal",
            ),
            (
                "dialogue_panteleimon_repeat",
                18,
                "player",
                "Кладу нож. Опять. Не вас.",
                61,
                1,
                None,
                "have_item_knife",
            ),
            (
                "dialogue_panteleimon_repeat",
                60,
                "npc",
                "Бумагу знаю, барин. Я ничего не говорил.",
                -1,
                None,
                None,
                None,
            ),
            (
                "dialogue_panteleimon_repeat",
                61,
                "npc",
                "Опять нож, барин. Я ничего не видел.",
                -1,
                None,
                None,
                None,
            ),
        ),
    )


def _apply_phase24(conn) -> None:
    """Три занятия — три ночи. Те же люди, вторая строка до выбора."""
    conn.executemany(
        """UPDATE dialogue_lines SET next_order = 4
           WHERE dialogue_id = ? AND order_num = ? AND speaker = 'npc'""",
        (
            ("dialogue_watchman_intro", 0),
            ("dialogue_watchman_intro", 1),
            ("dialogue_watchman_intro", 2),
            ("dialogue_watchman_intro", 3),
            ("dialogue_lukin_intro", 0),
            ("dialogue_lukin_intro", 1),
            ("dialogue_lukin_intro", 2),
            ("dialogue_lukin_intro", 3),
            ("dialogue_praskovya_intro", 0),
            ("dialogue_praskovya_intro", 1),
            ("dialogue_praskovya_intro", 2),
            ("dialogue_praskovya_intro", 3),
            ("dialogue_panteleimon_intro", 0),
            ("dialogue_panteleimon_intro", 1),
            ("dialogue_shpilkin_intro", 2),
            ("dialogue_nastasya_intro", 2),
        ),
    )
    conn.executemany(
        """DELETE FROM dialogue_lines
           WHERE dialogue_id = ? AND order_num = ?""",
        tuple(
            (did, n)
            for did in (
                "dialogue_watchman_intro",
                "dialogue_lukin_intro",
                "dialogue_praskovya_intro",
                "dialogue_panteleimon_intro",
                "dialogue_shpilkin_intro",
                "dialogue_nastasya_intro",
            )
            for n in (4, 5, 6)
        ),
    )
    conn.executemany(
        """INSERT INTO dialogue_lines
           (dialogue_id, order_num, speaker, text, sanity_change, next_order,
            choice_group, sets_flag, ending_id, requires_flag)
           VALUES (?, ?, 'npc', ?, 0, 10, NULL, NULL, NULL, ?)""",
        (
            (
                "dialogue_watchman_intro",
                4,
                "Глядите, будто протокол читаете. Записать всё равно нечего — ступайте.",
                "class_seeker",
            ),
            (
                "dialogue_watchman_intro",
                5,
                "Стоите, будто слушаете кого за спиной. Не оборачивайтесь, сударь.",
                "class_mystic",
            ),
            (
                "dialogue_watchman_intro",
                6,
                "Плечо у вас привычное к дверям. Его я запомню раньше фамилии.",
                "class_rebel",
            ),
            (
                "dialogue_lukin_intro",
                4,
                "Пыль на прилавке разглядываете, не товар. Ключ всё равно в шкафу, сударь.",
                "class_seeker",
            ),
            (
                "dialogue_lukin_intro",
                5,
                "Счёты щёлкнули — вы вздрогнули. Не отвечайте им, сударь.",
                "class_mystic",
            ),
            (
                "dialogue_lukin_intro",
                6,
                "На ящик смотрите, не на меня. Он для людей открыт, не для вас.",
                "class_rebel",
            ),
            (
                "dialogue_praskovya_intro",
                4,
                "Чернила ещё свежие, и вы это заметили. Вычеркнуто не ваше имя, батюшка.",
                "class_seeker",
            ),
            (
                "dialogue_praskovya_intro",
                5,
                "Вы к тишине прислушиваетесь. Не отзывайтесь, коли позовут ласково.",
                "class_mystic",
            ),
            (
                "dialogue_praskovya_intro",
                6,
                "Дверь у меня на честном слове держится. Плечом её не проверяйте.",
                "class_rebel",
            ),
            (
                "dialogue_panteleimon_intro",
                4,
                "Царапины заметили. От пояса, барин. Только не говорите никому.",
                "class_seeker",
            ),
            (
                "dialogue_panteleimon_intro",
                5,
                "Вы слышите, как за стеной шепчут. Не отвечайте, барин, Христа ради.",
                "class_mystic",
            ),
            (
                "dialogue_panteleimon_intro",
                6,
                "Вы бы дверь плечом взяли, вижу. Кто так берёт, того вниз сносят.",
                "class_rebel",
            ),
            (
                "dialogue_shpilkin_intro",
                4,
                "Глаза у вас как у следователя. Читайте бумаги, не меня.",
                "class_seeker",
            ),
            (
                "dialogue_shpilkin_intro",
                5,
                "Вы вслушиваетесь в угол. Я тоже, и капель поэтому не пью.",
                "class_mystic",
            ),
            (
                "dialogue_shpilkin_intro",
                6,
                "Плечо у вас привычное. Здесь двери ключом, не плечом.",
                "class_rebel",
            ),
            (
                "dialogue_nastasya_intro",
                4,
                "Имена на полу — вы правильно смотрите. Бумаги у немца, прочее вата.",
                "class_seeker",
            ),
            (
                "dialogue_nastasya_intro",
                5,
                "Они зовут вас, как мать звала. Это не мать. Не отзывайтесь.",
                "class_mystic",
            ),
            (
                "dialogue_nastasya_intro",
                6,
                "Дверь на улицу есть. Только туман плечом не выломать — правдой.",
                "class_rebel",
            ),
        ),
    )


def _apply_phase25(conn) -> None:
    """Прилавок Лукина: цена в реплике. Не витрина и не десятый ответ."""
    _ensure_column(conn, "items", "value", "INTEGER DEFAULT 0")
    _ensure_column(conn, "dialogue_lines", "takes_item_id", "TEXT")
    conn.executemany(
        "UPDATE items SET value = ? WHERE id = ?",
        (
            (3, "item_knife"),
            (4, "potion_heal"),
            (5, "potion_sanity"),
        ),
    )
    conn.execute(
        """UPDATE items SET value = 0
           WHERE type IN ('key', 'note') OR is_quest_item = 1"""
    )
    conn.executemany(
        "UPDATE items SET value = ? WHERE id = ?",
        (
            (3, "item_knife"),
            (4, "potion_heal"),
            (5, "potion_sanity"),
        ),
    )
    conn.executemany(
        """DELETE FROM dialogue_lines
           WHERE dialogue_id = ? AND order_num = ?""",
        tuple(
            (did, n)
            for did in ("dialogue_lukin_intro", "dialogue_lukin_repeat")
            for n in (70, 71, 72, 73, 74, 75)
        ),
    )
    conn.executemany(
        """UPDATE dialogue_lines SET next_order = 70
           WHERE dialogue_id = ? AND order_num = 16 AND speaker = 'player'""",
        (("dialogue_lukin_intro",), ("dialogue_lukin_repeat",)),
    )
    conn.executemany(
        """INSERT INTO dialogue_lines
           (dialogue_id, order_num, speaker, text, sanity_change, next_order,
            choice_group, sets_flag, ending_id, requires_flag, takes_item_id)
           VALUES (?, ?, 'npc', ?, 0, ?, NULL, ?, NULL, ?, ?)""",
        (
            (
                "dialogue_lukin_intro",
                70,
                "Уберите железо, батюшка. Халату я за нож не плачу-с.",
                -1,
                "spoke_lukin",
                "look_clinic",
                None,
            ),
            (
                "dialogue_lukin_intro",
                71,
                "Ржавый-с, пустяки. {price} — вот получите.",
                -1,
                "spoke_lukin",
                "look_tenant",
                "item_knife",
            ),
            (
                "dialogue_lukin_intro",
                72,
                "Нагишом, да с ножом. Оденьтесь, батюшка, тогда и поговорим.",
                -1,
                "spoke_lukin",
                "look_bare",
                None,
            ),
            (
                "dialogue_lukin_intro",
                73,
                "Халат, и нож в руке. Не плачу-с, уберите железо.",
                -1,
                "spoke_lukin",
                "look_clinic_armed",
                None,
            ),
            (
                "dialogue_lukin_intro",
                74,
                "Положите на прилавок-с. {price} — вот получите.",
                -1,
                "spoke_lukin",
                "look_tenant_armed",
                "item_knife",
            ),
            (
                "dialogue_lukin_intro",
                75,
                "Голый, и железо в руке. Не торгую-с. Ступайте.",
                -1,
                "spoke_lukin",
                "look_bare_armed",
                None,
            ),
            (
                "dialogue_lukin_repeat",
                70,
                "Опять нож. Халату не плачу-с, уберите.",
                -1,
                None,
                "look_clinic",
                None,
            ),
            (
                "dialogue_lukin_repeat",
                71,
                "Опять ржавый. {price}-с, получите.",
                -1,
                None,
                "look_tenant",
                "item_knife",
            ),
            (
                "dialogue_lukin_repeat",
                72,
                "Опять нагишом. Не торгую-с. Ступайте.",
                -1,
                None,
                "look_bare",
                None,
            ),
            (
                "dialogue_lukin_repeat",
                73,
                "Опять халат с ножом. Не плачу-с. Уберите.",
                -1,
                None,
                "look_clinic_armed",
                None,
            ),
            (
                "dialogue_lukin_repeat",
                74,
                "Опять с руки. Положите-с: {price}.",
                -1,
                None,
                "look_tenant_armed",
                "item_knife",
            ),
            (
                "dialogue_lukin_repeat",
                75,
                "Опять голый, опять с ножом. Не торгую-с.",
                -1,
                None,
                "look_bare_armed",
                None,
            ),
        ),
    )


def _apply_phase26(conn) -> None:
    """Торг в лавке. В разговоре Лукин ртом не считает."""
    conn.executemany(
        """UPDATE dialogue_lines
           SET text = ?, takes_item_id = NULL
           WHERE dialogue_id = ? AND order_num = ?""",
        (
            (
                "Ржавый-с, пустяки. Кладите на прилавок — погляжу, что за него дам.",
                "dialogue_lukin_intro",
                71,
            ),
            (
                "С руки не беру, сударь. Коли продаёте — на прилавок, погляжу.",
                "dialogue_lukin_intro",
                74,
            ),
            (
                "Опять ржавый. Кладите, батюшка, — погляжу.",
                "dialogue_lukin_repeat",
                71,
            ),
            (
                "Опять с руки. На прилавок, сударь, — тогда погляжу.",
                "dialogue_lukin_repeat",
                74,
            ),
        ),
    )


