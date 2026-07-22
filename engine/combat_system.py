"""Боевая система на основе d20."""
import random
from typing import Tuple, Optional
from engine.entity_factory import Character, Player, Item


def roll_d20() -> int:
    """Бросить d20."""
    return random.randint(1, 20)


def roll_damage(damage_die: str) -> int:
    """
    Бросить кость урона.
    Формат: '1d6', '2d4', '1d8' и т.д.
    """
    if not damage_die:
        return 0
    
    try:
        parts = damage_die.split('d')
        num_dice = int(parts[0])
        die_size = int(parts[1])
        return sum(random.randint(1, die_size) for _ in range(num_dice))
    except:
        return 0


def calculate_attack_bonus(attacker) -> int:
    """Рассчитать бонус атаки."""
    # Базовый бонус из характеристик
    if hasattr(attacker, 'attack_bonus'):
        return attacker.attack_bonus
    
    # Если нет attack_bonus, используем STR или DEX
    if hasattr(attacker, 'stats'):
        str_mod = (attacker.stats.get('STR', 10) - 10) // 2
        return str_mod
    
    return 0


def calculate_armor_class(defender) -> int:
    """Рассчитать класс брони."""
    if hasattr(defender, 'armor_class'):
        return defender.armor_class
    
    # Если нет AC, используем базовый 10 + DEX
    if hasattr(defender, 'stats'):
        dex_mod = (defender.stats.get('DEX', 10) - 10) // 2
        return 10 + dex_mod
    
    return 10


def perform_attack(attacker, defender) -> Tuple[bool, int, str]:
    """
    Выполнить атаку.
    Возвращает: (попало, урон, сообщение)
    """
    # Получаем имя атакующего
    attacker_name = getattr(attacker, 'name', 'Неизвестный')
    if not attacker_name and hasattr(attacker, 'class_name'):
        attacker_name = attacker.class_name
    
    # Получаем имя защитника
    defender_name = getattr(defender, 'name', 'Неизвестный')
    
    # Бросок атаки
    attack_roll = roll_d20()
    attack_bonus = calculate_attack_bonus(attacker)
    total_attack = attack_roll + attack_bonus
    
    # Класс брони цели
    armor_class = calculate_armor_class(defender)
    
    # Проверяем попадание
    if total_attack >= armor_class:
        # Попали! Считаем урон
        damage = roll_damage(getattr(attacker, 'damage_die', '1d6'))
        
        # Критический удар (натуральная 20)
        if attack_roll == 20:
            damage *= 2
            message = f"КРИТИЧЕСКИЙ УДАР! {attacker_name} наносит {damage} урона!"
        else:
            message = f"{attacker_name} попадает и наносит {damage} урона."
        
        # Применяем урон
        if hasattr(defender, 'take_damage'):
            defender.take_damage(damage)
        
        return True, damage, message
    else:
        # Промах
        if attack_roll == 1:
            message = f"{attacker_name} проваливает атаку (натуральная 1)!"
        else:
            message = f"{attacker_name} промахивается (AC {armor_class})."
        
        return False, 0, message

def is_hostile(entity1, entity2) -> bool:
    """Проверить, враждебны ли сущности друг другу."""
    # Игрок враждебен всем врагам
    if isinstance(entity1, Player) and hasattr(entity2, 'type'):
        return entity2.type == 'enemy'
    
    if isinstance(entity2, Player) and hasattr(entity1, 'type'):
        return entity1.type == 'enemy'
    
    # Проверяем фракции
    if hasattr(entity1, 'faction') and hasattr(entity2, 'faction'):
        return entity1.faction != entity2.faction
    
    return False