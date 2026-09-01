"""Система безумия (SAN)."""
import random


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


class SanSystem:
    """Управление уровнем рассудка и галлюцинациями."""

    def __init__(self, player):
        self.player = player
        self.current_san = player.san
        self.last_san = player.san
        self.hallucination_level = self._calculate_hallucination_level()
        self.san_events = []

    def update(self):
        """Вернуть только новые события. Повторный вызов без смены SAN — пусто."""
        if self.current_san == self.player.san:
            return []

        old_level = self.hallucination_level
        self.last_san = self.current_san
        self.current_san = self.player.san
        self.hallucination_level = self._calculate_hallucination_level()

        if self.hallucination_level <= old_level:
            return []

        event = self._event_for_level(self.hallucination_level)
        if event:
            self.san_events.append(event)
            return [event]
        return []

    def _calculate_hallucination_level(self) -> int:
        """Рассчитать уровень галлюцинаций."""
        if self.current_san > 80:
            return 0
        elif self.current_san > 60:
            return 1
        elif self.current_san > 40:
            return 2
        elif self.current_san > 20:
            return 3
        else:
            return 4

    def _event_for_level(self, level: int) -> str:
        options = _LEVEL_EVENTS.get(level)
        if not options:
            return ""
        return random.choice(options)

    def _check_san_event(self) -> str:
        """Совместимость: текст для текущего уровня, без смены состояния."""
        return self._event_for_level(self.hallucination_level)

    def get_sanity_effects(self) -> dict:
        """Эффекты для рендера.

        Карту не скремблируем и не гасим весь кадр: только край зрения.
        control не инвертируем: молчащие клавиши уже принимали за поломку.
        """
        level = self.hallucination_level
        return {
            'visual': 'periphery' if level else None,
            'level': level,
            'sound': None,
            'control': None,
            'hallucinations': [],
        }
