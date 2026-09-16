"""Слоты как в ролевой: тело, руки, ноги. Одежду меняют, халат снимают."""
from typing import Dict, List, Optional, Tuple

# Кукла. Правая рука бьёт. Тело — одежда, не навечно халат.
EQUIP_SLOTS: Tuple[Tuple[str, str], ...] = (
    ("head", "голова"),
    ("cloak", "плащ"),
    ("body", "тело"),
    ("hands", "кисти"),
    ("main_hand", "правая рука"),
    ("off_hand", "левая рука"),
    ("belt", "пояс"),
    ("legs", "ноги"),
    ("feet", "обувь"),
)

# Правая колонка окна «на себе»: голова сверху, обувь снизу.
EQUIP_LAYOUT: Dict[str, Tuple[int, int]] = {
    "head": (14, 0),
    "cloak": (0, 3),
    "hands": (28, 3),
    "body": (0, 6),
    "main_hand": (28, 6),
    "belt": (0, 9),
    "off_hand": (28, 9),
    "legs": (14, 12),
    "feet": (14, 15),
}

WORN_WHERE = {
    "head": "на голове",
    "cloak": "на плечах",
    "body": "на теле",
    "hands": "на кистях",
    "main_hand": "в руке",
    "off_hand": "в левой",
    "belt": "на поясе",
    "legs": "на ногах",
    "feet": "на обуви",
}

SLOT_INDEX = {slot_id: i for i, (slot_id, _name) in enumerate(EQUIP_SLOTS)}


def slot_for_item(item) -> Optional[str]:
    """Куда надевается вещь. Пусто — в карман, не на тело."""
    if item is None:
        return None
    explicit = (getattr(item, "equip_slot", None) or "").strip()
    if explicit:
        return explicit
    kind = getattr(item, "type", "") or ""
    if kind == "weapon":
        return "main_hand"
    if kind == "clothing":
        return "body"
    return None


def empty_fill(slot_id: str) -> str:
    if slot_id == "main_hand":
        return "кулак"
    return "пусто"


def slot_name(slot_id: str) -> str:
    for sid, name in EQUIP_SLOTS:
        if sid == slot_id:
            return name
    return slot_id


def equipped_map(player) -> Dict[str, str]:
    raw = getattr(player, "equipped", None)
    if isinstance(raw, dict):
        return raw
    player.equipped = {}
    return player.equipped


def item_in_slot(player, slot_id: str):
    item_id = equipped_map(player).get(slot_id)
    if not item_id:
        return None
    for item in getattr(player, "inventory", None) or []:
        if getattr(item, "id", None) == item_id:
            return item
    return None


def slot_fill_name(player, slot_id: str) -> str:
    held = item_in_slot(player, slot_id)
    if held:
        return getattr(held, "name", "вещь") or "вещь"
    return empty_fill(slot_id)


def worn_phrase(player, item_id: str) -> str:
    for slot_id, equipped_id in equipped_map(player).items():
        if equipped_id == item_id:
            return WORN_WHERE.get(slot_id, "на себе")
    return ""


def first_item_for_slot(player, slot_id: str, skip_id: Optional[str] = None):
    for item in getattr(player, "inventory", None) or []:
        if getattr(item, "id", None) == skip_id:
            continue
        if slot_for_item(item) == slot_id:
            return item
    return None
