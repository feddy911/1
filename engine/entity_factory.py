"""Фабрика сущностей — создаёт игроков, NPC, предметы."""
from typing import List, Optional
from tcod import libtcodpy


class Player:
    """Игрок."""
    
    def __init__(self, class_data: dict):
        self.id = class_data['id']
        self.class_name = class_data['name']
        self.name = class_data['name']
        self.hp = class_data['base_hp']
        self.max_hp = class_data['base_hp']
        self.san = class_data['base_san']
        self.max_san = class_data['base_san']
        self.stats = {
            'STR': class_data['base_str'],
            'DEX': class_data['base_dex'],
            'CON': class_data['base_con'],
            'INT': class_data['base_int'],
            'CHA': class_data['base_cha']
        }
        self.x = 0
        self.y = 0
        self.symbol = '@'
        self.color = libtcodpy.Color(220, 220, 230)
        self.inventory: List[Item] = []
        self.starting_item_ids = []
        self.damage_die = '1d6'
        self.attack_bonus = 2
        self.armor_class = 12
    
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
        if self.san <= 0:
            self.hp = 0
    
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