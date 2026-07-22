"""Система заранее определенных триггеров."""
from typing import List, Dict
import random


class TriggerResult:
    """Результат срабатывания триггера."""
    def __init__(self):
        self.messages: List[str] = []
        self.sanity_change: int = 0
        self.hp_change: int = 0
        self.spawn_character_id: str = None
        self.spawn_item_id: str = None


class TriggerSystem:
    """Обрабатывает триггеры из БД."""
    
    def __init__(self, db_loader):
        self.db = db_loader
    
    def check_enter_trigger(self, x: int, y: int, player) -> TriggerResult:
        """Проверить триггеры при входе на клетку."""
        result = TriggerResult()
        triggers = self.db.get_triggers_at(x, y)
        
        for trigger in triggers:
            self._apply_trigger(trigger, player, result)
        
        return result
    
    def _apply_trigger(self, trigger: Dict, player, result: TriggerResult):
        """Применить эффект триггера."""
        # Текст
        if trigger.get('text'):
            result.messages.append(trigger['text'])
        
        # Изменение рассудка
        sanity_change = trigger.get('sanity_change', 0)
        if sanity_change != 0:
            player.change_san(sanity_change)
            result.sanity_change += sanity_change
        
        # Урон
        damage = trigger.get('damage', 0)
        if damage > 0:
            player.take_damage(damage)
            result.hp_change -= damage
        
        # Лечение
        heal = trigger.get('heal', 0)
        if heal > 0:
            player.heal(heal)
            result.hp_change += heal
        
        # Спавн (запоминаем ID, спавнит game_engine)
        if trigger.get('spawn_character_id'):
            result.spawn_character_id = trigger['spawn_character_id']
        if trigger.get('spawn_item_id'):
            result.spawn_item_id = trigger['spawn_item_id']
            
    def check_san_trigger(self, x: int, y: int, player) -> List[str]:
        """Проверить триггеры безумия."""
        messages = []
        
        # В комнатах с низким SAN может происходить безумие
        if player.san < 60:
            if random.random() < 0.1:  # 10% шанс
                messages.append("Вы чувствуете, как ваш рассудок тает...")
                player.lose_san(5)
        
        return messages        
