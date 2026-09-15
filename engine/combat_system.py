"""Боевая система на основе d20 с учётом рассудка."""
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


def calculate_attack_bonus(attacker, san_penalty: int = 0) -> int:
    """
    Рассчитать бонус атаки с учётом штрафа рассудка.
    
    Args:
        attacker: Атакующий
        san_penalty: Штраф от системы рассудка (отрицательное число)
    """
    # Базовый бонус из характеристик
    base_bonus = 0
    if hasattr(attacker, 'attack_bonus'):
        base_bonus = attacker.attack_bonus
    elif hasattr(attacker, 'stats'):
        str_mod = (attacker.stats.get('STR', 10) - 10) // 2
        base_bonus = str_mod
    
    # Применяем штраф рассудка (только для игрока)
    if isinstance(attacker, Player):
        talent = 0
        if hasattr(attacker, "get_talent_attack"):
            talent = attacker.get_talent_attack()
        final_bonus = base_bonus + san_penalty + talent
        # Штраф не может снизить бонус ниже -5
        return max(-5, final_bonus)
    
    return base_bonus


def calculate_armor_class(defender) -> int:
    """Рассчитать класс брони."""
    if hasattr(defender, 'armor_class'):
        return defender.armor_class
    
    # Если нет AC, используем базовый 10 + DEX
    if hasattr(defender, 'stats'):
        dex_mod = (defender.stats.get('DEX', 10) - 10) // 2
        return 10 + dex_mod
    
    return 10


def perform_attack(attacker, defender, san_penalty: int = 0, use_ability: bool = False) -> Tuple[bool, int, str]:
    """
    Выполнить атаку с учётом штрафа рассудка и способностей.
    
    Args:
        attacker: Атакующий
        defender: Защитник
        san_penalty: Штраф к броску атаки от рассудка (0 или отрицательное)
        use_ability: Использовать ли способность класса (для игрока)
    
    Returns:
        (попало, урон, сообщение)
    """
    # Получаем имя атакующего
    attacker_name = getattr(attacker, 'name', 'Неизвестный')
    if not attacker_name and hasattr(attacker, 'class_name'):
        attacker_name = attacker.class_name
    
    # Получаем имя защитника
    defender_name = getattr(defender, 'name', 'Неизвестный')
    
    # Проверка способности критического удара
    is_crit_from_ability = False
    damage_bonus = 0
    
    if isinstance(attacker, Player) and hasattr(attacker, 'consume_next_crit'):
        is_crit_from_ability = attacker.consume_next_crit()
    
    if isinstance(attacker, Player) and hasattr(attacker, 'get_damage_bonus'):
        damage_bonus = attacker.get_damage_bonus()
    
    # Бросок атаки
    attack_roll = roll_d20()
    attack_bonus = calculate_attack_bonus(attacker, san_penalty)
    total_attack = attack_roll + attack_bonus
    
    # Класс брони цели
    armor_class = calculate_armor_class(defender)
    
    # Проверяем попадание
    if total_attack >= armor_class:
        # Попали! Считаем урон
        damage = roll_damage(getattr(attacker, 'damage_die', '1d6'))
        
        # Добавляем бонус от способностей
        damage += damage_bonus
        
        # Критический удар (натуральная 20 или от способности)
        if attack_roll == 20 or is_crit_from_ability:
            damage *= 2
            crit_source = " — занятие" if is_crit_from_ability else ""
            message = f"Удар навылет{crit_source}. {attacker_name} ранит на {damage}."
        else:
            if san_penalty < 0:
                message = f"{attacker_name} попал, хотя рука дрожала, и ранил на {damage}."
            elif damage_bonus > 0:
                message = f"{attacker_name} попал тяжелее обыкновенного и ранил на {damage}."
            else:
                message = f"{attacker_name} попал. Боль на {damage}."
        
        # Применяем урон
        if hasattr(defender, 'take_damage'):
            defender.take_damage(damage)
        
        return True, damage, message
    else:
        # Промах
        if attack_roll == 1:
            message = f"{attacker_name} махнул в пустоту. Пустота не обиделась."
        else:
            message = f"{attacker_name} промахнулся. Воздух гуще тела."
        
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


def calculate_damage_with_mods(base_damage: int, attacker=None, defender=None, 
                                strength_mod: bool = True, san_penalty: int = 0) -> int:
    """
    Рассчитать итоговый урон с модификаторами.
    
    Args:
        base_damage: Базовый урон
        attacker: Атакующий (для STR модификатора)
        defender: Защитник (для сопротивления)
        strength_mod: Применять модификатор силы
        san_penalty: Штраф от рассудка к урону
    
    Returns:
        Итоговый урон (минимум 1 при попадании)
    """
    damage = base_damage
    
    # Модификатор силы атакующего
    if strength_mod and attacker and hasattr(attacker, 'stats'):
        str_mod = (attacker.stats.get('STR', 10) - 10) // 2
        damage += max(0, str_mod)  # Только положительный модификатор
    
    # Штраф от рассудка
    if san_penalty < 0:
        damage = max(1, damage + san_penalty)  # Минимум 1 урон
    
    return damage