"""Система инвентаря с улучшенным использованием предметов."""
from typing import List, Optional, Tuple
from engine.entity_factory import Item


class InventoryManager:
    """Управление инвентарём игрока."""
    
    def __init__(self):
        self.is_open = False
        self.selected_index = 0
        self.items: List[Item] = []
        self.show_details = False  # Показать детальное описание
    
    def open(self):
        """Открыть инвентарь."""
        self.is_open = True
        self.selected_index = 0
        self.show_details = False
    
    def close(self):
        """Закрыть инвентарь."""
        self.is_open = False
    
    def toggle(self):
        """Переключить состояние."""
        if self.is_open:
            self.close()
        else:
            self.open()
    
    def move_selection(self, direction: int):
        """Переместить выделение (1 = вниз, -1 = вверх)."""
        if not self.items:
            return
        
        self.selected_index += direction
        
        # +1 для пункта "Выход"
        max_index = len(self.items)
        self.selected_index = max(0, min(self.selected_index, max_index))
    
    def get_selected_item(self) -> Optional[Item]:
        """Получить выбранный предмет."""
        if 0 <= self.selected_index < len(self.items):
            return self.items[self.selected_index]
        return None
    
    def is_exit_selected(self) -> bool:
        """Проверить, выбран ли пункт 'Выход'."""
        return self.selected_index == len(self.items)
    
    def use_selected_item(self, player, san_system=None) -> Optional[str]:
        """
        Использовать выбранный предмет. Возвращает сообщение или None.
        
        Args:
            player: Игрок
            san_system: Система рассудка (для эффектов SAN)
        """
        item = self.get_selected_item()
        if not item:
            return None
        
        effect = getattr(item, 'use_effect', '')
        message = ''
        
        if effect == 'heal':
            healing = getattr(item, 'healing', 0)
            if healing > 0:
                old_hp = player.hp
                player.hp = min(player.max_hp, player.hp + healing)
                actual_heal = player.hp - old_hp
                message = f"Вы используете '{item.name}'. Восстановлено {actual_heal} HP."
                self.items.remove(item)
        
        elif effect == 'restore_sanity':
            restore = getattr(item, 'sanity_restore', 0)
            if restore > 0:
                old_san = player.san
                player.san = min(player.max_san, player.san + restore)
                actual_restore = player.san - old_san
                message = f"Вы используете '{item.name}'. Восстановлено {actual_restore} рассудка."
                
                # Если есть система рассудка, вызываем её метод
                if san_system:
                    events = san_system.gain_san(0)  # Обновить состояние
                    if events:
                        message += f" {' '.join(events)}"
                
                self.items.remove(item)
        
        elif effect == 'unlock_door':
            message = "Ключи используются автоматически при взаимодействии с дверью."
        
        elif effect == 'read_note':
            content = getattr(item, 'content', '')
            if content:
                message = f"Записка '{item.name}':\n{content}"
                # Записки не исчезают после прочтения
            else:
                message = "Записка пуста."
        
        elif effect == 'stabilize_sanity':
            # Предметы временной стабилизации рассудка
            bonus = getattr(item, 'sanity_effect', 5)
            duration = getattr(item, 'duration', 0)
            if san_system:
                san_system.apply_stabilization(bonus, duration)
                message = f"'{item.name}' стабилизирует рассудок (+{bonus})."
                self.items.remove(item)
            else:
                player.san = min(player.max_san, player.san + bonus)
                message = f"'{item.name}' восстанавливает {bonus} рассудка."
                self.items.remove(item)
        
        elif effect == 'temporary_buff':
            # Временные баффы (кофеин, стимуляторы)
            buff_type = getattr(item, 'buff_type', 'attack')
            buff_value = getattr(item, 'buff_value', 2)
            message = f"'{item.name}' даёт временный бонус к {buff_type} (+{buff_value})."
            # TODO: Реализовать систему временных баффов
            self.items.remove(item)
        
        else:
            message = f"Вы используете '{item.name}', но ничего не происходит."
            # Предметы без эффекта не исчезают
            # self.items.remove(item)
        
        return message
    
    def sync_with_player(self, player):
        """Синхронизировать список предметов с инвентарём игрока."""
        if hasattr(player, 'inventory'):
            self.items = player.inventory.copy()
    
    def has_key_for_door(self, door_block_id: str) -> Tuple[bool, Optional[Item]]:
        """
        Проверить, есть ли ключ для конкретной двери.
        
        Args:
            door_block_id: ID блока двери
        
        Returns:
            (есть ключ, предмет ключа)
        """
        for item in self.items:
            if getattr(item, 'key_id', None):
                # Проверяем, открывает ли ключ эту дверь
                if getattr(item, 'opens_block_id', None) == door_block_id:
                    return True, item
            # Также проверяем универсальные ключи
            if getattr(item, 'type', '') == 'key_universal':
                return True, item
        return False, None
    
    def can_use_item(self, item: Item, player) -> bool:
        """
        Проверить, можно ли использовать предмет сейчас.
        
        Args:
            item: Предмет
            player: Игрок
        
        Returns:
            Можно ли использовать
        """
        # Проверка требований предмета
        required_class = getattr(item, 'required_class', None)
        if required_class and player.id != required_class:
            return False
        
        required_san = getattr(item, 'required_san', 0)
        if player.san < required_san:
            return False
        
        return True
    
    def get_item_description(self, item: Item, detailed: bool = False) -> str:
        """
        Получить описание предмета.
        
        Args:
            item: Предмет
            detailed: Полное описание
        
        Returns:
            Строка описания
        """
        name = getattr(item, 'name', 'Неизвестный предмет')
        desc = getattr(item, 'description', '')
        
        if detailed:
            lines = [f"{item.symbol} {name}"]
            if desc:
                lines.append(desc)
            
            # Добавляем эффекты
            effects = []
            if getattr(item, 'healing', 0) > 0:
                effects.append(f"Лечение: +{item.healing} HP")
            if getattr(item, 'sanity_restore', 0) > 0:
                effects.append(f"Рассудок: +{item.sanity_restore}")
            if getattr(item, 'damage_die', ''):
                effects.append(f"Урон: {item.damage_die}")
            
            if effects:
                lines.append("Эффекты: " + ", ".join(effects))
            
            return "\n".join(lines)
        else:
            return f"{item.symbol} {name}"