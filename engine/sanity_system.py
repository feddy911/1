"""Система безумия (SAN) с динамическими эффектами."""
import random
from typing import List, Optional


# Сообщения только при росте hallucination_level (пороги 80 / 60 / 40 / 20).
_LEVEL_EVENTS = {
    1: [
        "Зрение дрожит, как лампа в коридоре.",
        "Кто-то шепчет за спиной — и смолкает, когда оборачиваетесь.",
        "Края комнаты чуть дальше, чем стена.",
    ],
    2: [
        "Тень исчезает, едва вы шагнете. След остаётся теплее воздуха.",
        "В пустом коридоре называют вас — не по имени.",
        "Стены ближе, чем план здания.",
    ],
    3: [
        "Вы видите проём, которого нет на стене.",
        "Тени замахиваются — и проходят сквозь воздух.",
        "Голоса в голове становятся громче шагов.",
    ],
    4: [
        "Отражение улыбается без вас.",
        "Комнаты меняются местами. Выход помнит другой этаж.",
        "Имя, которого не было, просят повторить.",
    ],
}

# Штраф к d20. visual/control для рендера — periphery / None.
# Клавиши не инвертируем: молчащие уже принимали за поломку.
_HALLUCINATION_EFFECTS = {
    0: {"combat_penalty": 0, "description": "Ясно"},
    1: {"combat_penalty": 0, "description": "Зрение дрожит, как лампа в коридоре"},
    2: {"combat_penalty": -1, "description": "Стены ближе, чем план здания"},
    3: {"combat_penalty": -2, "description": "Вы видите проём, которого нет на стене"},
    4: {"combat_penalty": -4, "description": "Отражение улыбается без вас"},
}


class SanSystem:
    """Управление уровнем рассудка, галлюцинациями и событиями безумия."""

    def __init__(self, player):
        self.player = player
        self.current_san = player.san
        self.last_san = player.san
        self.hallucination_level = self._calculate_hallucination_level()
        self.san_events: List[str] = []
        self.triggered_thresholds: set = set()
        self.stabilization_bonus = 0

    def update(self) -> List[str]:
        """Вернуть только новые события. Повторный вызов без смены SAN — пусто."""
        if self.current_san == self.player.san:
            return []

        old_level = self.hallucination_level
        self.last_san = self.current_san
        self.current_san = self.player.san
        new_level = self._calculate_hallucination_level()

        events = []
        if new_level > old_level:
            event = self._event_for_level(new_level)
            if event:
                events.append(event)
                threshold = self._get_threshold_for_level(new_level)
                if threshold:
                    self.triggered_thresholds.add(threshold)
        elif new_level < old_level:
            threshold = self._get_threshold_for_level(old_level)
            if threshold and threshold in self.triggered_thresholds:
                self.triggered_thresholds.remove(threshold)
            events.append("Голоса стихают. На мгновение.")

        self.hallucination_level = new_level
        self.san_events.extend(events)
        return events

    def lose_san(self, amount: int, source: str = "") -> List[str]:
        """Потерять рассудок. Иммунитет мистика на ход глушит удар."""
        if amount <= 0:
            return []
        if hasattr(self.player, "has_active_effect") and self.player.has_active_effect(
            "madness_immunity"
        ):
            return []
        self.player.lose_san(amount)
        return self.update()

    def gain_san(self, amount: int, source: str = "") -> List[str]:
        """Восстановить рассудок."""
        if amount <= 0:
            self.update()
            return []
        self.player.gain_san(amount)
        return self.update()

    def apply_stabilization(self, bonus: int, duration: int = 0):
        """Временный запас рассудка. duration пока не тратится по ходам."""
        self.stabilization_bonus = max(0, bonus)
        if bonus > 0 and hasattr(self.player, "max_san"):
            self.player.san = min(self.player.max_san, self.player.san + bonus)
        elif bonus > 0:
            self.player.san = self.player.san + bonus
        self.update()

    def clear_stabilization(self):
        if self.stabilization_bonus > 0:
            self.player.san = max(0, self.player.san - self.stabilization_bonus)
        self.stabilization_bonus = 0
        self.update()

    def get_combat_penalty(self) -> int:
        effects = _HALLUCINATION_EFFECTS.get(self.hallucination_level, {})
        return int(effects.get("combat_penalty", 0))

    def get_sanity_effects(self) -> dict:
        """Эффекты для рендера.

        Карту не скремблируем и не гасим весь кадр: только край зрения.
        control не инвертируем: молчащие клавиши уже принимали за поломку.
        """
        level = self.hallucination_level
        return {
            "visual": "periphery" if level else None,
            "level": level,
            "sound": None,
            "control": None,
            "hallucinations": [],
            "combat_penalty": self.get_combat_penalty(),
        }

    def get_effects(self) -> dict:
        fx = self.get_sanity_effects()
        table = _HALLUCINATION_EFFECTS.get(self.hallucination_level, {})
        fx["description"] = table.get("description", "")
        fx["stabilized"] = self.stabilization_bonus > 0
        fx["san_percent"] = self.current_san
        return fx

    def _calculate_hallucination_level(self) -> int:
        san = self.player.san
        if san > 80:
            return 0
        if san > 60:
            return 1
        if san > 40:
            return 2
        if san > 20:
            return 3
        return 4

    def _get_threshold_for_level(self, level: int) -> Optional[int]:
        return {1: 80, 2: 60, 3: 40, 4: 20}.get(level)

    def _event_for_level(self, level: int) -> str:
        options = _LEVEL_EVENTS.get(level)
        if not options:
            return ""
        return random.choice(options)

    def can_act_normally(self) -> bool:
        return self.hallucination_level < 3

    def is_critical(self) -> bool:
        return self.hallucination_level >= 4 or self.player.san <= 10
