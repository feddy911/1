"""Загрузчик данных из SQLite базы."""
import sqlite3
import json
from typing import Optional, List, Dict


class DBLoader:
    """Централизованный доступ ко всем данным игры."""
    
    def __init__(self, db_path: str = 'data/petersburg.db'):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row  # Доступ по именам колонок
    
    def get_character(self, char_id: str) -> Optional[Dict]:
        cursor = self.conn.execute(
            "SELECT * FROM characters WHERE id = ?", (char_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
   

    def get_room_template(self, template_id: str) -> Optional[Dict]:
        cursor = self.conn.execute(
            "SELECT * FROM room_templates WHERE id = ?", (template_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def get_room_spawns(self, template_id: str) -> List[Dict]:
        cursor = self.conn.execute(
            "SELECT * FROM room_spawns WHERE room_template_id = ?",
            (template_id,)
        )
        return [dict(row) for row in cursor.fetchall()]
    
    def get_triggers_at(self, x: int, y: int) -> List[Dict]:
        cursor = self.conn.execute(
            "SELECT * FROM triggers WHERE type = 'on_enter' AND target_id = ?",
            (f"{x},{y}",)
        )
        return [dict(row) for row in cursor.fetchall()]
    
    def get_dialogue(self, dialogue_id: str) -> Optional[Dict]:
        cursor = self.conn.execute(
            "SELECT * FROM dialogues WHERE id = ?", (dialogue_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        
        dialogue = dict(row)
        cursor = self.conn.execute(
            "SELECT * FROM dialogue_lines WHERE dialogue_id = ? ORDER BY order_num",
            (dialogue_id,)
        )
        dialogue['lines'] = [dict(line) for line in cursor.fetchall()]
        return dialogue
    
    def get_all_player_classes(self) -> List[Dict]:
        cursor = self.conn.execute("SELECT * FROM player_classes")
        classes = []
        for row in cursor.fetchall():
            class_data = dict(row)
            class_data['base_stats'] = json.loads(class_data['base_stats'])
            class_data['starting_items'] = json.loads(class_data['starting_items'])
            classes.append(class_data)
        return classes
    
    def get_player_class(self, class_id: str) -> Optional[Dict]:
        cursor = self.conn.execute(
            "SELECT * FROM player_classes WHERE id = ?", (class_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        class_data = dict(row)
        class_data['base_stats'] = json.loads(class_data['base_stats'])
        class_data['starting_items'] = json.loads(class_data['starting_items'])
        return class_data
    
    def get_dungeon_spawn_pool(self, entity_type: str, player_san: int = 100) -> List[Dict]:
        """Получить пул сущностей для спавна в подземелье."""
        cursor = self.conn.execute(
        """SELECT * FROM dungeon_spawn_pool 
           WHERE entity_type = ? 
           AND min_sanity <= ? 
           AND max_sanity >= ?
           ORDER BY weight DESC""",
           (entity_type, player_san, player_san)
        )
        return [dict(row) for row in cursor.fetchall()]
    
    def get_triggers_at_position(self, x: int, y: int) -> List[Dict]:
        """Получить триггеры в указанной позиции."""
        cursor = self.conn.execute(
            """SELECT * FROM triggers 
               WHERE x = ? AND y = ?""",
            (x, y)
        )
        return [dict(row) for row in cursor.fetchall()]
    
    def get_note(self, note_id: str) -> Optional[Dict]:
        """Получить записку по ID."""
        cursor = self.conn.execute(
            "SELECT * FROM items WHERE id = ? AND type = 'note'",
            (note_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def get_notes_at_location(self, location: str) -> List[Dict]:
        """Получить все записки в локации."""
        cursor = self.conn.execute(
            "SELECT * FROM notes WHERE location = ?",
            (location,)
        )
        return [dict(row) for row in cursor.fetchall()]
    
    def get_all_quests(self) -> List[Dict]:
        """Получить все квесты."""
        cursor = self.conn.execute("SELECT * FROM quests")
        return [dict(row) for row in cursor.fetchall()]
    
    def get_item(self, item_id: str) -> Optional[Dict]:
        """Получить предмет по ID."""
        cursor = self.conn.execute(
            "SELECT * FROM items WHERE id = ?",
            (item_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_key(self, key_id: str) -> Optional[Dict]:
        """Получить ключ по ID."""
        cursor = self.conn.execute(
            "SELECT * FROM keys WHERE id = ?", (key_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def get_all_keys(self) -> List[Dict]:
        """Получить все ключи."""
        cursor = self.conn.execute("SELECT * FROM keys")
        return [dict(row) for row in cursor.fetchall()]
    
    def get_keys_for_block(self, block_id: str) -> List[Dict]:
        """Получить ключи, которые открывают указанный блок."""
        cursor = self.conn.execute(
            """SELECT k.* FROM keys k
               JOIN key_door_mapping m ON k.id = m.key_id
               WHERE m.block_id = ?""",
            (block_id,)
        )
        return [dict(row) for row in cursor.fetchall()]
    
    def get_keys_for_block_type(self, block_type: str) -> List[Dict]:
        """Получить ключи для типа блока."""
        cursor = self.conn.execute(
            "SELECT * FROM keys WHERE opens_block_type = ? OR opens_block_type IS NULL",
            (block_type,)
        )
        return [dict(row) for row in cursor.fetchall()]    
           
    def close(self):
        self.conn.close()
        
    def get_tile_colors(self) -> Dict[str, Dict]:
        """Получить цвета для всех символов карты."""
        cursor = self.conn.execute("SELECT * FROM tile_colors")
        colors = {}
        for row in cursor.fetchall():
            colors[row['symbol']] = {
                'fg': row['fg_color'],
                'bg': row['bg_color']
            }
        return colors
    
    def get_tile_colors_explored(self) -> Dict[str, Dict]:
        """Получить приглушённые цвета для исследованных клеток."""
        cursor = self.conn.execute("SELECT * FROM tile_colors_explored")
        colors = {}
        for row in cursor.fetchall():
            colors[row['symbol']] = {
                'fg': row['fg_color'],
                'bg': row['bg_color']
            }
        return colors        
    
    def get_starting_map(self) -> Optional[Dict]:
        """Получить стартовую карту."""
        cursor = self.conn.execute(
            "SELECT * FROM maps WHERE is_starting_map = 1 LIMIT 1"
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def get_map(self, map_id: str) -> Optional[Dict]:
        """Получить карту по ID."""
        cursor = self.conn.execute(
            "SELECT * FROM maps WHERE id = ?", (map_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def get_maps_for_san(self, player_san: int) -> List[Dict]:
        """Получить карты, доступные для текущего уровня SAN."""
        cursor = self.conn.execute(
            """SELECT * FROM maps 
               WHERE min_sanity <= ? AND max_sanity >= ?
               ORDER BY id""",
            (player_san, player_san)
        )
        return [dict(row) for row in cursor.fetchall()]    
    
    def get_tile_transparency(self) -> Dict[str, int]:
        """Получить прозрачность тайлов для света."""
        try:
            cursor = self.conn.execute("SELECT * FROM tile_transparency")
            return {row['symbol']: row['blocks_light'] for row in cursor.fetchall()}
        except:
            # Дефолтные значения если таблицы нет
            return {
                '#': 1, ' ': 1, 'd': 1,  # Блокируют свет
                '.': 0, 'D': 0, 'W': 0, 'S': 0, '*': 0, '!': 0, ')': 0,
                '~': 0, '&': 0, '@': 0, 'k': 0, 'P': 0  # Пропускают свет
            }
    
    def get_light_sources(self) -> List[Dict]:
        """Получить все типы источников света."""
        try:
            cursor = self.conn.execute("SELECT * FROM light_sources")
            return [dict(row) for row in cursor.fetchall()]
        except:
            return []
    
    def get_light_source(self, source_id: str) -> Optional[Dict]:
        """Получить источник света по ID."""
        cursor = self.conn.execute(
            "SELECT * FROM light_sources WHERE id = ?", (source_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None