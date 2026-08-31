-- ============================================================
-- ПЕРСОНАЖИ
-- ============================================================
CREATE TABLE characters (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK(type IN ('npc', 'enemy', 'hallucination')),
    name TEXT NOT NULL,
    title TEXT,
    description TEXT,
    
    hp INTEGER DEFAULT 10,
    armor_class INTEGER DEFAULT 10,
    attack_bonus INTEGER DEFAULT 0,
    damage_die TEXT DEFAULT '1d6',
    
    str INTEGER DEFAULT 10,
    dex INTEGER DEFAULT 10,
    con INTEGER DEFAULT 10,
    int INTEGER DEFAULT 10,
    san INTEGER DEFAULT 10,
    cha INTEGER DEFAULT 10,
    
    ai_behavior TEXT DEFAULT 'passive' CHECK(ai_behavior IN ('passive', 'aggressive', 'fleeing', 'dialogue')),
    sanity_damage INTEGER DEFAULT 0,
    faction TEXT,
    symbol TEXT DEFAULT '?',
    color TEXT DEFAULT '#CCCCCC',
    dialogue_id TEXT
);

-- ============================================================
-- ПРЕДМЕТЫ
-- ============================================================
CREATE TABLE items (
    id TEXT PRIMARY KEY,
    type TEXT CHECK(type IN ('weapon', 'consumable', 'quest', 'note', 'key')),
    name TEXT NOT NULL,
    description TEXT,
    
    damage_die TEXT,
    healing INTEGER DEFAULT 0,
    sanity_restore INTEGER DEFAULT 0,
    sanity_damage INTEGER DEFAULT 0,
    
    symbol TEXT DEFAULT '?',
    color TEXT DEFAULT '#FFFFFF',
    
    is_quest_item INTEGER DEFAULT 0,
    use_effect TEXT
);

-- ============================================================
-- ШАБЛОНЫ КОМНАТ
-- ============================================================
CREATE TABLE room_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    layout_file TEXT NOT NULL,
    tags TEXT,
    ambient_sound TEXT
);

-- ============================================================
-- СПАВНЫ В КОМНАТАХ
-- ============================================================
CREATE TABLE room_spawns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_template_id TEXT NOT NULL,
    spawn_char TEXT,
    spawn_type TEXT NOT NULL CHECK(spawn_type IN ('character', 'item', 'trigger')),
    spawn_id TEXT NOT NULL,
    chance REAL DEFAULT 1.0,
    FOREIGN KEY (room_template_id) REFERENCES room_templates(id)
);

-- ============================================================
-- ОПИСАНИЯ ЛОКАЦИЙ
-- ============================================================
CREATE TABLE location_descriptions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    first_visit_text TEXT,
    revisit_text TEXT,
    sanity_effect INTEGER DEFAULT 0
);

-- ============================================================
-- ДИАЛОГИ
-- ============================================================
CREATE TABLE dialogues (
    id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL,
    trigger_condition TEXT,
    FOREIGN KEY (character_id) REFERENCES characters(id)
);

CREATE TABLE dialogue_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dialogue_id TEXT NOT NULL,
    order_num INTEGER NOT NULL,
    speaker TEXT NOT NULL CHECK(speaker IN ('npc', 'player', 'narrator')),
    text TEXT NOT NULL,
    sanity_change INTEGER DEFAULT 0,
    gives_item_id TEXT,
    triggers_event_id TEXT,
    FOREIGN KEY (dialogue_id) REFERENCES dialogues(id)
);

-- ============================================================
-- ТРИГГЕРЫ
-- ============================================================
CREATE TABLE triggers (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK(type IN (
        'on_enter', 'on_pickup', 'on_use', 'on_turn',
        'on_combat_start', 'on_death'
    )),
    target_id TEXT,
    text TEXT,
    sanity_change INTEGER DEFAULT 0,
    spawn_character_id TEXT,
    spawn_item_id TEXT,
    damage INTEGER DEFAULT 0,
    heal INTEGER DEFAULT 0,
    map_id TEXT,
    x INTEGER,
    y INTEGER
);

-- ============================================================
-- КЛАССЫ ИГРОКА
-- ============================================================
CREATE TABLE player_classes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    base_stats TEXT,
    starting_items TEXT,
    starting_room_id TEXT
);

-- ============================================================
-- АВТОРСКИЙ СПАВН НА ФИКСИРОВАННЫХ КАРТАХ
-- ============================================================
CREATE TABLE map_placements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    map_id TEXT NOT NULL,
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    spawn_type TEXT NOT NULL CHECK(spawn_type IN ('character', 'item')),
    spawn_id TEXT NOT NULL,
        UNIQUE(map_id, x, y)
);

CREATE TABLE door_locks (
    map_id TEXT NOT NULL,
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    required_key_id TEXT NOT NULL,
    PRIMARY KEY (map_id, x, y)
);

CREATE TABLE map_regions (
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