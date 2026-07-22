"""Система безумия (SAN)."""
import random
import math


class SanSystem:
    """Управление уровнем рассудка и галлюцинациями."""
    
    def __init__(self, player):
        self.player = player
        self.current_san = player.san
        self.last_san = player.san
        self.hallucination_level = 0
        self.san_events = []
    
    def update(self):
        """Обновить состояние безумия."""
        # Проверяем изменение SAN
        if self.current_san != self.player.san:
            self.last_san = self.current_san
            self.current_san = self.player.san
            
            # Обновляем уровень галлюцинаций
            self.hallucination_level = self._calculate_hallucination_level()
            
            # Добавляем событие
            event = self._check_san_event()
            if event:
                self.san_events.append(event)
        
        return self.san_events
    
    def _calculate_hallucination_level(self) -> int:
        """Рассчитать уровень галлюцинаций."""
        if self.current_san > 80:
            return 0
        elif self.current_san > 60:
            return 1  # Лёгкие искажения
        elif self.current_san > 40:
            return 2  # Средние галлюцинации
        elif self.current_san > 20:
            return 3  # Сильные искажения
        else:
            return 4  # Полное безумие
    
    def _check_san_event(self) -> str:
        """Проверить, произошло ли событие безумия."""
        if self.current_san < 80 and self.current_san > 60:
            return random.choice([
                "Ваше зрение немного дрожит...",
                "Вы слышите шёпот за спиной...",
                "Края комнаты кажутся искажёнными..."
            ])
        
        elif self.current_san < 60 and self.current_san > 40:
            return random.choice([
                "Вы видите тень, которая исчезает при приближении.",
                "Кто-то называет ваше имя в пустом коридоре...",
                "Стены кажутся слишком близкими..."
            ])
        
        elif self.current_san < 40 and self.current_san > 20:
            return random.choice([
                "Вы видите стены, которые не существуют!",
                "Тени атакуют вас, но их нет на самом деле!",
                "Голоса в голове становятся громче..."
            ])
        
        elif self.current_san <= 20:
            return random.choice([
                "Вы сходите с ума! Все кажется нереальным!",
                "Ваше собственное отражение улыбается вам с угрозой!",
                "Комнаты перемещаются! Где выход?!"
            ])
        
        return ""
    
    def get_sanity_effects(self) -> dict:
        """Получить текущие эффекты безумия."""
        effects = {
            'visual': None,
            'sound': None,
            'control': None,
            'hallucinations': []
        }
        
        # Лёгкие искажения (60-80 SAN)
        if self.hallucination_level >= 1:
            effects['visual'] = 'flicker'  # Мерцание экрана
        
        # Средние галлюцинации (40-60 SAN)
        if self.hallucination_level >= 2:
            effects['visual'] = 'distortion'
            effects['hallucinations'] = self._generate_hallucinations(2)
        
        # Сильные искажения (20-40 SAN)
        if self.hallucination_level >= 3:
            effects['visual'] = 'heavy_distortion'
            effects['control'] = 'inverted'  # Инвертированное управление
            effects['hallucinations'] = self._generate_hallucinations(4)
        
        # Полное безумие (<20 SAN)
        if self.hallucination_level >= 4:
            effects['visual'] = 'chaos'
            effects['control'] = 'random'  # Случайное управление
            effects['hallucinations'] = self._generate_hallucinations(6)
        
        return effects
    
    def _generate_hallucinations(self, count: int) -> list:
        """Сгенерировать галлюцинации."""
        hallucinations = []
        for _ in range(count):
            type_ = random.choice(['shadow', 'wall', 'voice', 'figure'])
            x = random.randint(0, 79)
            y = random.randint(0, 49)
            hallucinations.append({
                'type': type_,
                'x': x,
                'y': y,
                'duration': random.randint(1, 5)
            })
        return hallucinations