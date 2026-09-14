"""Система безумия (SAN) с динамическими эффектами."""
import random
from typing import List, Dict, Optional, Tuple


# Таблица событий при потере рассудка (при переходе через порог вниз)
_SAN_LOSS_EVENTS = {
    80: [
        "Вам кажется, что лампа мигнула чаще обычного.",
        "Где-то капает вода. Или это кровь?",
        "Вы слышите шаги, но они не ваши.",
    ],
    60: [
        "Стены дышат. Вдох — выдох.",
        "Кто-то назвал вас чужим именем.",
        "Отражение в окне моргнуло позже вас.",
    ],
    40: [
        "Двойник стоит в конце коридора. Он не двигается.",
        "Голоса спорят о том, кто вы есть.",
        "Пол стал мягче. Как плоть.",
    ],
    20: [
        "Имя рассыпается. Вы не помните первую букву.",
        "Коридор ведёт внутрь себя.",
        "Тени отделились от стен. Они наблюдают.",
    ],
}

# Эффекты для каждого уровня галлюцинаций
_HALLUCINATION_EFFECTS = {
    0: {
        'visual': None,
        'sound': None,
        'control': None,
        'combat_penalty': 0,
        'description': "Ясно",
    },
    1: {
        'visual': 'periphery_flicker',  # Мерцание по краям
        'sound': 'whisper_soft',  # Тихий шёпот
        'control': None,
        'combat_penalty': 0,
        'description': "Зрение дрожит, как лампа в коридоре",
    },
    2: {
        'visual': 'periphery_warp',  # Искажение периферии
        'sound': 'whisper_medium',  # Отчётливый шёпот
        'control': 'delay_50ms',  # Задержка ввода 50мс
        'combat_penalty': -1,
        'description': "Стены ближе, чем план здания",
    },
    3: {
        'visual': 'center_distort',  # Искажение центра
        'sound': 'voice_call',  # Голос зовёт
        'control': 'invert_one_key',  # Одна клавиша инвертирована
        'combat_penalty': -2,
        'description': "Вы видите проём, которого нет на стене",
    },
    4: {
        'visual': 'full_hallucinate',  # Полные галлюцинации
        'sound': 'chaos_voices',  # Хаос голосов
        'control': 'random_misinput',  # Случайные неверные ввода
        'combat_penalty': -4,
        'description': "Отражение улыбается без вас",
    },
}


class SanSystem:
    """Управление уровнем рассудка, галлюцинациями и событиями безумия."""

    def __init__(self, player):
        self.player = player
        self.current_san = player.san
        self.last_san = player.san
        self.hallucination_level = self._calculate_hallucination_level()
        self.san_events: List[str] = []
        self.triggered_thresholds: set = set()  # Пороги, которые уже сработали
        self.stabilization_bonus = 0  # Временный бонус от предметов/способностей
        self.temp_san_loss = 0  # Временная потеря SAN (восстанавливается)

    def update(self) -> List[str]:
        """Обновить состояние и вернуть новые события."""
        if self.current_san == self.player.san:
            return []

        old_level = self.hallucination_level
        self.last_san = self.current_san
        self.current_san = self.player.san
        new_level = self._calculate_hallucination_level()
        
        events = []

        # Проверка на переход через порог вниз (потеря SAN)
        if new_level > old_level:
            threshold = self._get_threshold_for_level(new_level)
            if threshold and threshold not in self.triggered_thresholds:
                event_text = self._get_san_loss_event(threshold)
                if event_text:
                    events.append(event_text)
                    self.triggered_thresholds.add(threshold)

        # Проверка на восстановление через порог вверх (лечение SAN)
        elif new_level < old_level:
            threshold = self._get_threshold_for_level(old_level)
            if threshold and threshold in self.triggered_thresholds:
                self.triggered_thresholds.remove(threshold)
                events.append("Голоса стихают. На мгновение.")

        self.hallucination_level = new_level
        self.san_events.extend(events)
        return events

    def lose_san(self, amount: int, source: str = "") -> List[str]:
        """
        Потерять рассудок. Возвращает события.
        source: причина потери (для логов)
        """
        old_level = self.hallucination_level
        self.player.lose_san(amount)
        events = self.update()
        
        # Критическая потеря SAN (более 10 за раз)
        if amount >= 10:
            # Находим ближайший порог для выбора сообщения
            current_san = self.player.san
            if current_san > 60:
                threshold = 80
            elif current_san > 40:
                threshold = 60
            elif current_san > 20:
                threshold = 40
            else:
                threshold = 20
            
            options = _SAN_LOSS_EVENTS.get(threshold, _SAN_LOSS_EVENTS[20])
            crit_event = f"Внезапный ужас: {random.choice(options)}"
            events.append(crit_event)
        
        return events

    def gain_san(self, amount: int, source: str = "") -> List[str]:
        """
        Восстановить рассудок. Возвращает события.
        """
        old_level = self.hallucination_level
        self.player.gain_san(amount)
        events = self.update()
        
        if old_level > self.hallucination_level:
            events.append("Рассудок возвращается... частично.")
        
        return events

    def apply_stabilization(self, bonus: int, duration: int = 0):
        """
        Применить временную стабилизацию рассудка.
        bonus: бонус к SAN (положительный)
        duration: длительность в ходах (0 = постоянно до сброса)
        """
        self.stabilization_bonus = bonus
        self.player.san = min(self.player.max_san, self.player.san + bonus)

    def clear_stabilization(self):
        """Сбросить временную стабилизацию."""
        if self.stabilization_bonus > 0:
            self.player.san = max(0, self.player.san - self.stabilization_bonus)
        self.stabilization_bonus = 0

    def get_combat_penalty(self) -> int:
        """Получить штраф к бою от текущего уровня SAN."""
        effects = _HALLUCINATION_EFFECTS.get(self.hallucination_level, {})
        return effects.get('combat_penalty', 0)

    def get_effects(self) -> dict:
        """Получить все активные эффекты для рендера и логики."""
        effects = _HALLUCINATION_EFFECTS.get(self.hallucination_level, {})
        return {
            'visual': effects.get('visual'),
            'sound': effects.get('sound'),
            'control': effects.get('control'),
            'level': self.hallucination_level,
            'san_percent': self.current_san,
            'combat_penalty': self.get_combat_penalty(),
            'description': effects.get('description', ''),
            'stabilized': self.stabilization_bonus > 0,
        }

    def _calculate_hallucination_level(self) -> int:
        """Рассчитать уровень галлюцинаций на основе текущего SAN."""
        san = self.player.san
        if san > 80:
            return 0
        elif san > 60:
            return 1
        elif san > 40:
            return 2
        elif san > 20:
            return 3
        else:
            return 4

    def _get_threshold_for_level(self, level: int) -> Optional[int]:
        """Получить порог SAN для уровня галлюцинаций."""
        thresholds = {1: 80, 2: 60, 3: 40, 4: 20}
        return thresholds.get(level)

    def _get_san_loss_event(self, threshold: int) -> str:
        """Получить событие потери рассудка для порога."""
        options = _SAN_LOSS_EVENTS.get(threshold, [])
        if not options:
            return ""
        return random.choice(options)

    def can_act_normally(self) -> bool:
        """Проверить, может ли игрок действовать нормально (без помех)."""
        return self.hallucination_level < 3

    def is_critical(self) -> bool:
        """Проверить критическое состояние рассудка."""
        return self.hallucination_level >= 4 or self.player.san <= 10
