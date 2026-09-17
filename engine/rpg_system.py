"""Кость клиники: 3d6, успех если сумма с бонусом не ниже порога.

Сцена боя остаётся d20. Коридор и бумаги — здесь.
"""
import random
from dataclasses import dataclass
from typing import Optional, Tuple


SKILL_IDS = (
    "search",
    "read",
    "talk",
    "sneak",
    "fight",
    "hear",
    "break",
    "see_trace",
)

SKILL_NAMES = {
    "search": "Обыск",
    "read": "Чтение",
    "talk": "Говорить",
    "sneak": "Красться",
    "fight": "Удар",
    "hear": "Слышать",
    "break": "Ломать",
    "see_trace": "След",
}

# Занятие задаёт модификатор к 3d6 (значение − 10). Порог проверки — 11.
# Дерево талантов добавляет к броску, не вместо занятия.
CHECK_DC = 11
CLASS_SKILL_TABLE = {
    "seeker": {
        "search": 12,
        "read": 12,
        "talk": 10,
        "sneak": 10,
        "fight": 10,
        "hear": 10,
        "break": 8,
        "see_trace": 12,
    },
    "rebel": {
        "search": 10,
        "read": 8,
        "talk": 11,
        "sneak": 10,
        "fight": 12,
        "hear": 8,
        "break": 12,
        "see_trace": 8,
    },
    "mystic": {
        "search": 10,
        "read": 12,
        "talk": 11,
        "sneak": 10,
        "fight": 8,
        "hear": 12,
        "break": 8,
        "see_trace": 10,
    },
}

# Фразы живых глаголов коридора: крит / успех / провал / 17–18.
# Говорить звучит репликой NPC, не второй строкой в логе.
SKILL_PHRASES = {
    "search": (
        "Палец нашёл шов, который прятали. Прятали плохо — или хотели, чтобы нашли.",
        "Нащупали. Рука знает больше памяти.",
        "Пыль. Рука не нашла. Впрочем, пыль тоже ответ.",
        "Пыль легла в ладонь. Пусто. Пустота, сударь, тоже сытая.",
    ),
    "sneak": (
        "Тень дышит мимо вас, как мимо столба. Столбу, видите ли, прощают.",
        "Прошли мимо. Тень не обернулась. Не обернулась — и слава богу.",
        "Тень повернулась. Увидела. Конечно, увидела: вы слишком живые.",
        "Шаг слишком живой. Тень уже смотрит. Смотрит — и не прощает.",
    ),
    "hear": (
        "Шёпот зовёт вас не тем именем, которым крестили. Вы не оборачиваетесь. Не надо.",
        "Шёпот узнаёт вас. Это уже не первый раз — вы просто не помните. Не помните, и стыдно.",
        "Шёпот сбился. Не разобрать, чьё. Чьё — и не надо разбирать.",
        "Шёпот сбился в своё имя — чужим голосом. Потом тишина. Тишина хуже.",
    ),
    "break": (
        "Замок сдался сразу. Плечо помнит дверь лучше ключа. Помнит — и радуется, подлец.",
        "Вы выбиваете дверь плечом. Замок орёт. Рассудок — тоже. Оба имеют право.",
        "Плечо ударило. Замок сильнее. Сильнее — пока. Пока.",
        "Плечо гудит. Замок смеётся железным смехом. Смеётся, как человек, которому можно.",
    ),
}

# CoC-пара: потеря при успехе воли / кость при провале.
# Бумага, двойник, признание, одержимый — одна таблица. Не плюсовать
# к item.sanity_damage и не к удару врага.
SAN_EVENTS = {
    "note_mysterious": (0, "1d4"),
    "note_1": (0, "1d4"),
    "note_2": (0, "1d4"),
    "note_case": (0, "1d4"),
    "note_canal": (0, "1d6"),
    "note_tenement": (0, "1d4"),
    "diary_1": (0, "1d4"),
    "diary_2": (0, "1d4"),
    "diary_3": (0, "1d4"),
    "letter_1": (0, "1d4"),
    "document_1": (0, "1d6"),
    "double": (1, "1d6"),
    "guilt_admitted": (1, "1d4"),
    "possessed": (1, "1d6"),
}

SAN_SPEECH_FLAGS = {
    "guilt_admitted": "guilt_admitted",
    "spoke_possessed": "possessed",
}
SAN_SPEECH_CHARACTERS = frozenset({"possessed_patient", "player_double"})

SAN_FAIL_PHRASE = {
    "double": "Халат ваш. Лица нет. Впрочем, лицо и прежде было не ваше.",
    "guilt_admitted": "Долг звучит громче воли. Громче — и не стыдится.",
    "possessed": "В нём молятся не его ртом. Не его — и всё-таки его.",
}


@dataclass(frozen=True)
class RollResult:
    total: int
    target: int
    success: bool
    crit: bool
    fumble: bool


def roll_3d6() -> int:
    return random.randint(1, 6) + random.randint(1, 6) + random.randint(1, 6)


def roll_die(spec: str) -> int:
    spec = (spec or "").strip().lower()
    if not spec:
        return 0
    if spec.isdigit():
        return max(0, int(spec))
    if "d" not in spec:
        return 0
    count, _, size = spec.partition("d")
    try:
        n = int(count or "1")
        faces = int(size)
    except ValueError:
        return 0
    return sum(random.randint(1, faces) for _ in range(max(1, n)))


def skill_base(player, skill_id: str) -> int:
    skills = getattr(player, "skills", None) or {}
    if skill_id in skills:
        return int(skills[skill_id])
    table = CLASS_SKILL_TABLE.get(getattr(player, "id", ""), {})
    if skill_id in table:
        return int(table[skill_id])
    return 10


def skill_modifier(player, skill_id: str) -> int:
    from engine.talent_system import skill_bonus

    return skill_base(player, skill_id) - 10 + skill_bonus(player, skill_id)


def skill_dc(player=None, skill_id: str = "") -> int:
    return CHECK_DC


def will_target(player) -> int:
    stats = getattr(player, "stats", None) or {}
    will = stats.get("WILL", stats.get("SAN"))
    if will is None:
        return 10
    return max(6, min(16, int(will)))


def will_modifier(player) -> int:
    return will_target(player) - 10


def roll_skill(player, skill_id: str) -> RollResult:
    """3d6 + модификатор ≥ 11. 17–18 крит, 3–4 провал. Не d20."""
    total = roll_3d6()
    modifier = skill_modifier(player, skill_id)
    dc = CHECK_DC
    fumble = total <= 4
    crit = total >= 17
    success = (not fumble) and (crit or (total + modifier) >= dc)
    return RollResult(
        total=total, target=dc, success=success, crit=crit, fumble=fumble
    )


def skill_phrase(check: RollResult, skill_id: str) -> str:
    """Одна фраза на бросок. Говорить звучит репликой NPC, не отсюда."""
    pack = SKILL_PHRASES.get(skill_id)
    if not pack:
        return ""
    crit, ok, bad, fumble = pack
    if check.fumble:
        return fumble
    if check.crit and check.success:
        return crit
    if check.success:
        return ok
    return bad


def roll_will(player) -> RollResult:
    total = roll_3d6()
    modifier = will_modifier(player)
    dc = CHECK_DC
    fumble = total <= 4
    crit = total >= 17
    success = (not fumble) and (crit or (total + modifier) >= dc)
    return RollResult(
        total=total, target=dc, success=success, crit=crit, fumble=fumble
    )


def is_canon_loot(item) -> bool:
    """Ключ, записка, квест — не теряем из-за кости."""
    if item is None:
        return False
    if getattr(item, "is_quest_item", False):
        return True
    kind = getattr(item, "type", "") or ""
    return kind in {"key", "note", "clothing"}


def san_loss_for(event_id: str, player) -> Tuple[int, Optional[str]]:
    """Таблица CoC. Неизвестное событие — (0, None)."""
    pair = SAN_EVENTS.get(event_id)
    if not pair:
        return 0, None
    held, fail_die = pair
    check = roll_will(player)
    if check.success:
        amount = int(held)
        if amount <= 0:
            return 0, None
        return amount, "Воля удержала. Ненадолго."
    from engine.talent_system import has_note_hold

    paper = event_id.startswith(("note_", "diary_", "letter_", "document_"))
    if paper and has_note_hold(player):
        amount = max(1, int(held) or 1)
        return amount, "Чужой почерк держит. Кость не падает. Ненадолго."
    amount = max(1, roll_die(fail_die))
    fail_phrase = SAN_FAIL_PHRASE.get(
        event_id, "Строка держит дольше, чем взгляд."
    )
    return amount, fail_phrase
