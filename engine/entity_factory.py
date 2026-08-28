"""Фабрика сущностей — создаёт игроков, NPC, предметы."""
from typing import List, Optional
from tcod import libtcodpy


class Player:
    """Игрок."""
    
    def __init__(self, class_data: dict):
        self.id = class_data['id']
        self.class_name = class_data['name']
        self.name = class_data['name']

        json_stats = class_data.get('base_stats') or {}
        if isinstance(json_stats, str):
            json_stats = {}

        self.stats = {
            'STR': int(json_stats.get('STR', class_data.get('base_str', 10))),
            'DEX': int(json_stats.get('DEX', class_data.get('base_dex', 10))),
            'CON': int(json_stats.get('CON', class_data.get('base_con', 10))),
            'INT': int(json_stats.get('INT', class_data.get('base_int', 10))),
            'CHA': int(json_stats.get('CHA', class_data.get('base_cha', 10))),
        }

        con_mod = (self.stats['CON'] - 10) // 2
        str_mod = (self.stats['STR'] - 10) // 2
        dex_mod = (self.stats['DEX'] - 10) // 2

        base_hp = int(class_data.get('base_hp') or 10)
        self.max_hp = max(1, base_hp + con_mod)
        self.hp = self.max_hp
        self.san = int(class_data.get('base_san') or class_data.get('base_sanity') or 100)
        self.max_san = self.san

        self.x = 0
        self.y = 0
        self.symbol = '@'
        self.color = libtcodpy.Color(220, 220, 230)
        self.inventory: List[Item] = []
        starting = class_data.get('starting_items') or []
        self.starting_item_ids = list(starting) if isinstance(starting, list) else []
        self.damage_die = '1d6'
        self.attack_bonus = 2 + str_mod
        self.armor_class = 10 + dex_mod
    
    def is_alive(self) -> bool:
        return self.hp > 0
    
    def take_damage(self, amount: int):
        self.hp -= amount
        if self.hp < 0:
            self.hp = 0
    
    def heal(self, amount: int):
        self.hp += amount
        if self.hp > self.max_hp:
            self.hp = self.max_hp
    
    def lose_san(self, amount: int):
        self.san -= amount
        if self.san < 0:
            self.san = 0
    
    def gain_san(self, amount: int):
        self.san += amount
        if self.san > self.max_san:
            self.san = self.max_san
    
    def change_san(self, amount: int):
        if amount > 0:
            self.gain_san(amount)
        else:
            self.lose_san(abs(amount))


class Character:
    """Персонаж (NPC, враг)."""
    
    def __init__(self, data: dict):
        self.id = data['id']
        self.type = data['type']
        self.name = data['name']
        self.title = data['title']
        self.description = data['description']
        self.hp = data['hp']
        self.max_hp = data['hp']
        self.damage_die = data['damage_die']
        self.attack_bonus = data.get('attack_bonus', 0)
        self.armor_class = data.get('armor_class', 10)
        self.sanity_damage = data.get('sanity_damage', 0)
        self.stats = {
            'STR': data['str'],
            'DEX': data['dex'],
            'CON': data['con'],
            'INT': data['int'],
            'CHA': data['cha']
        }
        self.ai_behavior = data['ai_behavior']
        self.dialogue_id = data.get('dialogue_id')
        self.faction = data.get('faction', 'neutral')
        self.symbol = data.get('symbol', '&')
        self.color = self._parse_color(data.get('color', '#ffffff'))
        self.x = 0
        self.y = 0
    
    def _parse_color(self, color_str: str):
        if color_str.startswith('#'):
            r = int(color_str[1:3], 16)
            g = int(color_str[3:5], 16)
            b = int(color_str[5:7], 16)
            return libtcodpy.Color(r, g, b)
        return libtcodpy.Color(255, 255, 255)
    
    def is_alive(self) -> bool:
        return self.hp > 0
    
    def take_damage(self, amount: int):
        self.hp -= amount
        if self.hp < 0:
            self.hp = 0
    
    def heal(self, amount: int):
        self.hp += amount
        if self.hp > self.max_hp:
            self.hp = self.max_hp


class Item:
    """Универсальный предмет — ВСЕ данные из БД."""
    
    def __init__(self, data: dict):
        # Основные поля
        self.id = data['id']
        self.type = data['type']
        self.name = data['name']
        self.description = data.get('description', '')
        self.symbol = data.get('symbol', '!')
        self.color = self._parse_color(data.get('color', '#ffffff'))
        
        # Игровые свойства
        self.damage_die = data.get('damage_die', '')
        self.healing = data.get('healing', 0)
        self.sanity_restore = data.get('sanity_restore', 0)
        self.sanity_damage = data.get('sanity_damage', 0)
        self.sanity_effect = data.get('sanity_effect', 0)
        self.is_quest_item = bool(data.get('is_quest_item', 0))
        self.use_effect = data.get('use_effect', '')
        self.content = data.get('content', '')  # Для записок
        
        # Для ключей
        self.key_id = data.get('key_id')  # ID ключа в таблице keys
        self.opens_block_id = data.get('opens_block_id')  # Конкретный блок
        
        # Позиция
        self.x = 0
        self.y = 0
    
    def _parse_color(self, color_str: str):
        if color_str and color_str.startswith('#'):
            r = int(color_str[1:3], 16)
            g = int(color_str[3:5], 16)
            b = int(color_str[5:7], 16)
            return libtcodpy.Color(r, g, b)
        return libtcodpy.Color(255, 255, 255)
    
    def is_note(self) -> bool:
        """Проверить, является ли запиской."""
        return self.type == 'note' or self.use_effect == 'read_note'


class EntityFactory:
    """Фабрика для создания сущностей."""
    
    def __init__(self, db):
        self.db = db
    
    def create_character(self, char_id: str) -> Optional[Character]:
        """Создать персонажа из БД."""
        data = self.db.get_character(char_id)
        return Character(data) if data else None
    
    def create_item(self, item_id: str) -> Optional[Item]:
        """Создать предмет из БД — универсальный конструктор."""
        data = self.db.get_item(item_id)
        return Item(data) if data else None