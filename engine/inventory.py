"""Система инвентаря."""
from typing import List, Optional
from engine.entity_factory import Item

class InventoryManager:
    """Управление инвентарём игрока."""
    
    def __init__(self):
        self.is_open = False
        self.selected_index = 0
        self.items: List[Item] = []
    
    def open(self):
        """Открыть инвентарь."""
        self.is_open = True
        self.selected_index = 0
    
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
    
    def use_selected_item(self, player) -> Optional[str]:
        """Использовать выбранный предмет. Возвращает сообщение или None."""
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
                self.items.remove(item)
        
        elif effect == 'unlock_door':
            message = "Ключи используются автоматически при взаимодействии с дверью."
        
        else:
            message = f"Вы используете '{item.name}', но ничего не происходит."
            self.items.remove(item)
        
        return message
    
    def sync_with_player(self, player):
        """Синхронизировать список предметов с инвентарём игрока."""
        if hasattr(player, 'inventory'):
            self.items = player.inventory.copy()