"""Фабрика сущностей — создаёт игроков, NPC, предметы."""
from typing import List, Optional, Tuple
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
            'WILL': int(json_stats.get('SAN', json_stats.get('WILL', 10))),
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
        self.skills = dict(class_data.get('skills') or {})
        self.talents: List[str] = []
        self.equipped_weapon_id: Optional[str] = None
        from engine.constants import UNARMED_DAMAGE_DIE

        self.damage_die = UNARMED_DAMAGE_DIE
        self.attack_bonus = 2 + str_mod
        self.armor_class = 10 + dex_mod
        
        # Боевая способность класса
        ability_json = class_data.get('class_ability')
        import json as json_module
        if ability_json and isinstance(ability_json, str):
            self.class_ability = json_module.loads(ability_json)
        elif isinstance(ability_json, dict):
            self.class_ability = ability_json
        else:
            self.class_ability = None
        
        # Активные эффекты способности
        self.active_effects = []
    
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
    
    def use_class_ability(self, san_system=None) -> Tuple[bool, str]:
        """Использовать способность класса. Возвращает (успех, сообщение)."""
        if not self.class_ability:
            return False, "У этого класса нет способности."
        
        ability = self.class_ability
        ability_type = ability.get('type', '')
        
        # Проверка SAN cost
        san_cost = ability.get('san_cost', 0)
        if san_cost > 0 and self.san < san_cost:
            return False, f"Недостаточно рассудка для {ability['name']} (нужно {san_cost})."
        
        # Применяем эффект в зависимости от типа
        if ability_type == 'combat_buff':
            # Временный бонус к урону
            damage_bonus = ability.get('damage_bonus', 0)
            duration = ability.get('duration', 1)
            self.active_effects.append({
                'type': 'damage_buff',
                'value': damage_bonus,
                'duration': duration
            })
            if san_cost > 0:
                self.lose_san(san_cost)
            return True, f"{ability['name']}: рука тяжелее на {duration} удар. Тяжелее — и стыднее."
        
        elif ability_type == 'critical_strike':
            # Автоматический крит - просто помечаем следующий удар как критический
            self.active_effects.append({
                'type': 'next_crit',
                'value': True,
                'duration': 1
            })
            return True, f"{ability['name']}: следующий удар пойдёт насквозь. Насквозь — или никак."
        
        elif ability_type == 'sanity_restore':
            # Восстановление SAN
            san_restore = ability.get('san_restore', 0)
            madness_immunity = ability.get('madness_immunity', False)
            
            old_san = self.san
            self.gain_san(san_restore)
            actual_restore = self.san - old_san
            
            if madness_immunity:
                self.active_effects.append({
                    'type': 'madness_immunity',
                    'value': True,
                    'duration': 1
                })
            
            msg = f"{ability['name']}: воля вернулась на {actual_restore}"
            if madness_immunity:
                msg += "; бред не берёт, пока держитесь"
            return True, msg + "."
        
        return False, "Неизвестный тип способности."

    def chart_marks(self) -> str:
        """Короткие пометки шапки дела. Не кулдаун MMORPG."""
        labels = {
            "damage_buff": "рука тяжелее",
            "next_crit": "удар насквозь",
            "madness_immunity": "бред не берёт",
        }
        marks = []
        for effect in self.active_effects:
            if int(effect.get("duration") or 0) <= 0:
                continue
            label = labels.get(effect.get("type"))
            if label and label not in marks:
                marks.append(label)
        return " · ".join(marks)

    def add_effect(self, kind: str, value=True, duration: int = 1):
        self.active_effects.append(
            {"type": kind, "value": value, "duration": max(1, int(duration))}
        )
    
    def has_active_effect(self, effect_type: str) -> bool:
        """Проверить наличие активного эффекта."""
        for effect in self.active_effects:
            if effect['type'] == effect_type and effect['duration'] > 0:
                return True
        return False
    
    def get_damage_bonus(self) -> int:
        """Получить бонус к урону от активных эффектов."""
        bonus = 0
        for effect in self.active_effects:
            if effect['type'] == 'damage_buff' and effect['duration'] > 0:
                bonus += effect.get('value', 0)
        from engine.talent_system import damage_bonus as talent_damage

        return bonus + talent_damage(self)

    def get_talent_attack(self) -> int:
        from engine.talent_system import attack_bonus as talent_attack

        return talent_attack(self)
    
    def consume_next_crit(self) -> bool:
        """Потребить эффект критического удара. Возвращает True если был крит."""
        for i, effect in enumerate(self.active_effects):
            if effect['type'] == 'next_crit' and effect['duration'] > 0:
                self.active_effects.pop(i)
                return True
        return False
    
    def update_effects(self):
        """Обновить длительность эффектов (вызывать каждый ход)."""
        for effect in self.active_effects[:]:
            effect['duration'] -= 1
            if effect['duration'] <= 0:
                self.active_effects.remove(effect)


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