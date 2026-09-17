"""Вид на теле, память на человека, карман как довод. Не фракция и не кость."""
from typing import Dict, Optional, Set

from engine.equipment import item_in_slot

LOOKS = ("clinic", "tenant", "bare")
LOOK_IDS = {"item_robe": "clinic", "item_coat": "tenant"}


def worn_look(player) -> str:
    """Что видят: халат, сюртук или голое тело. Без игрока — казённый вид."""
    if player is None:
        return "clinic"
    body = item_in_slot(player, "body")
    if body is not None:
        explicit = (getattr(body, "look", None) or "").strip()
        if explicit in LOOKS:
            return explicit
        return LOOK_IDS.get(getattr(body, "id", ""), "clinic")
    held = [getattr(item, "id", None) for item in getattr(player, "inventory", None) or []]
    if "item_robe" in held or "item_coat" in held:
        return "bare"
    return "clinic"


def is_armed(player) -> bool:
    """Нож в правой. Кулак и карман не считаются."""
    held = item_in_slot(player, "main_hand") if player else None
    if held is None:
        return False
    if (getattr(held, "type", "") or "") != "weapon":
        return False
    return bool((getattr(held, "damage_die", "") or "").strip())


def look_flag(player) -> str:
    look = worn_look(player)
    if is_armed(player):
        return f"look_{look}_armed"
    return f"look_{look}"


def memory_flag(character_id: str) -> str:
    return f"warm_{character_id}"


def standing_of(standing: Optional[Dict], character_id: str) -> int:
    if not character_id or not isinstance(standing, dict):
        return 0
    try:
        return int(standing.get(character_id, 0) or 0)
    except (TypeError, ValueError):
        return 0


def remember(standing: Dict[str, int], character_id: str, delta: int) -> None:
    if not character_id or not delta:
        return
    standing[character_id] = standing_of(standing, character_id) + int(delta)


def sight_and_memory_flags(
    player,
    standing: Optional[Dict] = None,
    character_id: str = "",
) -> Set[str]:
    """Флаги для веток. Вид сейчас. Память — если человека уже знают."""
    flags = {look_flag(player)}
    if is_armed(player):
        flags.add("armed")
    if character_id and standing_of(standing, character_id) >= 1:
        flags.add(memory_flag(character_id))
    return flags


def pocket_flags(player) -> Set[str]:
    """Что можно положить на стол. Вещь в кармане, не вес."""
    flags: Set[str] = set()
    if player is None:
        return flags
    for item in getattr(player, "inventory", None) or []:
        item_id = (getattr(item, "id", None) or "").strip()
        if item_id:
            flags.add(f"have_{item_id}")
    return flags


def parse_standing(raw) -> Dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, int] = {}
    for key, value in raw.items():
        name = str(key or "").strip()
        if not name:
            continue
        try:
            out[name] = int(value)
        except (TypeError, ValueError):
            continue
    return out
