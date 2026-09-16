"""Дерево талантов: ветки восьми глаголов, не четвёртая сотня имён.

Бой и мир. Узел берут и углубляют. Плата — воля и поступок, не опыт.
see_trace не бросает кость: след — взгляд, не девятый глагол.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set

from engine.quest_system import has_debt, has_name


SAN_FLOOR = 20


@dataclass(frozen=True)
class Talent:
    id: str
    name: str
    description: str
    branch: str
    verb: str
    parent_id: Optional[str]
    rank: int
    san_cost: int
    require_deed: str
    prefer_class: Optional[str]
    effects: Dict


TALENTS: Sequence[Talent] = (
    Talent(
        "fight_1", "Рука помнит удар",
        "Удар. Постоянно +1 к урону каждого попадания (кость оружия + 1). "
        "Бросок атаки d20 не меняется. Для бунтаря плата волей меньше.",
        "combat", "fight", None, 1, 6, "", "rebel",
        {"damage": 1},
    ),
    Talent(
        "fight_2", "Тяжелее обыкновенного",
        "Удар. Ещё +1 к урону и +1 к броску атаки (d20 + бонус против брони). "
        "Складывается с «Рука помнит удар». Для бунтаря плата волей меньше.",
        "combat", "fight", "fight_1", 2, 8, "spoke", "rebel",
        {"damage": 1, "attack": 1},
    ),
    Talent(
        "fight_3", "Насквозь",
        "Удар. Ещё +1 к урону. В начале схватки ваш первый удар — критический "
        "(урон ×2), даже без 20 на d20. Дальше бросок обычный. Нужны имя или долг.",
        "combat", "fight", "fight_2", 3, 10, "truth", "rebel",
        {"damage": 1, "opening_crit": True},
    ),
    Talent(
        "break_1", "Плечо знает дверь",
        "Ломать (3d6 + модификатор ≥ 11). К броску +2. У бунтаря: одна запертая дверь плечом. "
        "Успех — дверь открыта (−8 воли и 1 плоть). Провал — дверь стоит. "
        "Стену сломать нельзя. Для бунтаря плата волей меньше.",
        "combat", "break", "fight_1", 2, 6, "", "rebel",
        {"skill": {"break": 2}},
    ),
    Talent(
        "break_2", "Дверь сдаётся дважды",
        "Ломать (3d6 + модификатор ≥ 11). Если бросок провален, но не 3–4, он повторяется "
        "один раз. 3–4 — сразу провал, повтора нет. Для бунтаря плата волей меньше.",
        "combat", "break", "break_1", 3, 8, "spoke", "rebel",
        {"reroll": "break"},
    ),
    Talent(
        "flee_1", "Стыд живых",
        "Бегство в бою (клавиша 3). Шанс уйти 50% становится 75% (не выше 85%). "
        "Успех — схватка кончена, вы живы. Провал — враг бьёт в ответ.",
        "combat", "fight", "fight_1", 2, 7, "spoke", None,
        {"flee": 0.25},
    ),
    Talent(
        "search_1", "Шов в пыли",
        "Обыск (3d6 + модификатор ≥ 11). К броску +1. Успех — находите спрятанное в мебели. "
        "Провал — пусто, если это не ключ и не записка (их кость не отнимает). "
        "Для искателя плата волей меньше.",
        "world", "search", None, 1, 5, "", "seeker",
        {"skill": {"search": 1}},
    ),
    Talent(
        "search_2", "Нащупали дважды",
        "Обыск (3d6 + модификатор ≥ 11). Если бросок провален, но не 3–4, он повторяется "
        "один раз. 3–4 — сразу провал. Для искателя плата волей меньше.",
        "world", "search", "search_1", 2, 7, "spoke", "seeker",
        {"reroll": "search"},
    ),
    Talent(
        "sneak_1", "Как столб",
        "Красться (3d6 + модификатор ≥ 11). К броску +2. Успех — проходите клетку тени в подвале "
        "без схватки. Провал — бой как обычно. Одержимого обойти нельзя. "
        "Для искателя плата волей меньше.",
        "world", "sneak", "search_1", 2, 6, "", "seeker",
        {"skill": {"sneak": 2}},
    ),
    Talent(
        "sneak_2", "Тень не смотрит",
        "Красться (3d6 + модификатор ≥ 11). Если бросок провален, но не 3–4, он повторяется "
        "один раз. 3–4 — сразу бой. Для искателя плата волей меньше.",
        "world", "sneak", "sneak_1", 3, 8, "spoke", "seeker",
        {"reroll": "sneak"},
    ),
    Talent(
        "talk_1", "Два слова",
        "Говорить (3d6 + модификатор ≥ 11) в тех репликах, где стоит проверка. К броску +1. "
        "Успех — NPC отвечает по удачной ветке. Провал — отказ или хуже. "
        "В лог фраза умения не пишется: отвечает человек.",
        "world", "talk", None, 1, 5, "", None,
        {"skill": {"talk": 1}},
    ),
    Talent(
        "talk_2", "Не сбился",
        "Говорить (3d6 + модификатор ≥ 11). Если бросок провален, но не 3–4, он повторяется "
        "один раз. Повтор не даёт имя и не ставит долг.",
        "world", "talk", "talk_1", 2, 8, "spoke", None,
        {"reroll": "talk"},
    ),
    Talent(
        "hear_1", "Уменьшительное",
        "Слышать (3d6 + модификатор ≥ 11). К броску +2. Успех легче у лампы в коридоре и в тех "
        "репликах, где стоит проверка слуха (свисток постового и т.п.). "
        "Для мистика плата волей меньше.",
        "world", "hear", None, 1, 5, "", "mystic",
        {"skill": {"hear": 2}},
    ),
    Talent(
        "hear_2", "Лампа зовёт",
        "Слышать (3d6 + модификатор ≥ 11) у лампы на 1 этаже. Можно без занятия мистика. "
        "Успех один раз за ночь: слышите след у лампы. Имя и долг не даёт. "
        "Для мистика плата волей меньше.",
        "world", "hear", "hear_1", 2, 8, "spoke", "mystic",
        {"hear_lamp": True},
    ),
    Talent(
        "read_1", "Поля",
        "Чтение (3d6 + модификатор ≥ 11). К броску +1, когда проверка чтения есть. "
        "Нужна, чтобы взять «Чужой почерк». Для мистика плата волей меньше.",
        "world", "read", "hear_1", 2, 6, "", "mystic",
        {"skill": {"read": 1}},
    ),
    Talent(
        "read_2", "Чужой почерк",
        "Воля (3d6 + модификатор ≥ 11) при чтении записки. Успех — как в таблице. "
        "Провал: −1 воля вместо кости провала (1d4 или 1d6). "
        "На двойника и одержимого не действует. Нужны имя или долг.",
        "world", "read", "read_1", 3, 9, "truth", "mystic",
        {"note_hold": True},
    ),
    Talent(
        "trace_1", "След, не кость",
        "След. Без броска (это не девятый глагол). При первом входе в некоторые "
        "места видите лишнюю деталь: пыль, каблук, графу. Имя и долг не даёт. "
        "Для искателя плата волей меньше.",
        "world", "see_trace", "search_1", 2, 7, "spoke", "seeker",
        {"glimpse": True},
    ),
)

TALENT_BY_ID: Dict[str, Talent] = {node.id: node for node in TALENTS}

TALENT_GLIMPSES = {
    "f1_hall": "Пыль у плинтуса стёрта дважды. Второй раз — босой пяткой.",
    "st_fog": "В вате след каблука и след, который вата съела.",
    "ten_shop": "На прилавке овал от ключей свежее пыли. Клали сегодня.",
    "tav_room": "Под скатертью адрес вычеркнут до дыры — и рядом новый.",
}


def owned_ids(player) -> Set[str]:
    return set(getattr(player, "talents", None) or ())


def has_talent(player, talent_id: str) -> bool:
    return talent_id in owned_ids(player)


def talent_effects(player) -> List[Dict]:
    found = []
    for talent_id in owned_ids(player):
        node = TALENT_BY_ID.get(talent_id)
        if node:
            found.append(node.effects)
    return found


def skill_bonus(player, skill_id: str) -> int:
    total = 0
    for effects in talent_effects(player):
        table = effects.get("skill") or {}
        total += int(table.get(skill_id, 0) or 0)
    return total


def damage_bonus(player) -> int:
    return sum(int(effects.get("damage") or 0) for effects in talent_effects(player))


def attack_bonus(player) -> int:
    return sum(int(effects.get("attack") or 0) for effects in talent_effects(player))


def flee_bonus(player) -> float:
    return sum(float(effects.get("flee") or 0) for effects in talent_effects(player))


def has_reroll(player, skill_id: str) -> bool:
    return any(effects.get("reroll") == skill_id for effects in talent_effects(player))


def has_opening_crit(player) -> bool:
    return any(effects.get("opening_crit") for effects in talent_effects(player))


def has_hear_lamp(player) -> bool:
    return any(effects.get("hear_lamp") for effects in talent_effects(player))


def has_note_hold(player) -> bool:
    return any(effects.get("note_hold") for effects in talent_effects(player))


def has_trace_glimpse(player) -> bool:
    return any(effects.get("glimpse") for effects in talent_effects(player))


def san_cost_for(node: Talent, class_id: str) -> int:
    cost = int(node.san_cost)
    if node.prefer_class and node.prefer_class == class_id:
        return max(2, cost - 3)
    return cost


def deed_ready(node: Talent, flags: Optional[Set[str]]) -> bool:
    flags = set(flags or ())
    if not node.require_deed:
        return True
    if node.require_deed == "spoke":
        if any(flag.startswith("spoke_") for flag in flags):
            return True
        if any(flag.startswith("searched:") for flag in flags):
            return True
        return "fog_house" in flags
    if node.require_deed == "truth":
        return has_name(flags) or has_debt(flags)
    return True


def can_see(node: Talent, player) -> bool:
    taken = owned_ids(player)
    if node.id in taken:
        return True
    if node.parent_id is None:
        return True
    return node.parent_id in taken


def visible_talents(player) -> List[Talent]:
    nodes = [node for node in TALENTS if can_see(node, player)]
    order = {"combat": 0, "world": 1}
    nodes.sort(key=lambda node: (order.get(node.branch, 9), node.rank, node.id))
    return nodes


def take_block_reason(player, node: Talent, flags: Optional[Set[str]]) -> Optional[str]:
    if has_talent(player, node.id):
        return "Эта пометка уже в тетради. Уже — и хватит."
    if node.parent_id and node.parent_id not in owned_ids(player):
        parent = TALENT_BY_ID[node.parent_id]
        return f"Сначала «{parent.name}». Иначе ветка не держит."
    if not deed_ready(node, flags):
        if node.require_deed == "truth":
            return "Имя или долг. Без них пометка не садится. Не садится — и правильно."
        return "Сначала поступок: речь, обыск, туман. Тетрадь сытая на чужие руки."
    cost = san_cost_for(node, getattr(player, "id", ""))
    san = int(getattr(player, "san", 0) or 0)
    if san - cost < SAN_FLOOR:
        return (
            "Воля не отпустит эту пометку. После неё останется меньше двадцати. "
            "Меньше — и бред пишет сам."
        )
    return None


def take_talent(player, talent_id: str, flags: Optional[Set[str]] = None):
    """Взять узел. Возвращает (успех, фраза)."""
    node = TALENT_BY_ID.get(talent_id)
    if not node:
        return False, "Такой пометки нет."
    reason = take_block_reason(player, node, flags)
    if reason:
        return False, reason
    cost = san_cost_for(node, getattr(player, "id", ""))
    owned = list(getattr(player, "talents", None) or [])
    owned.append(node.id)
    player.talents = owned
    player.lose_san(cost)
    return True, f"В тетрадь: {node.name}. Воля заплатила {cost}."


def roll_verb(player, skill_id: str):
    """3d6 глагола. Повтор — только если тетрадь это купила."""
    from engine.rpg_system import roll_skill

    check = roll_skill(player, skill_id)
    if check.success or check.fumble:
        return check
    if has_reroll(player, skill_id):
        return roll_skill(player, skill_id)
    return check
