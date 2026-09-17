"""Лавка Лукина: купить и продать."""
from typing import Dict, List, Optional, Tuple

from engine.look_memory import standing_of, worn_look


MERCHANTS: Dict[str, Dict] = {
    "shopkeeper_lukin": {
        "name": "Лукин",
        "sells": ("potion_heal", "potion_sanity", "item_knife"),
        "looks": ("tenant",),
        "refuse": {
            "clinic": "Халату не торгую-с. Ступайте, батюшка.",
            "bare": "Нагишом не торгую-с. Оденьтесь, батюшка.",
        },
    },
}


def kopeck_phrase(amount: int) -> str:
    n = max(0, int(amount))
    mod10, mod100 = n % 10, n % 100
    if mod10 == 1 and mod100 != 11:
        word = "копейка"
    elif mod10 in (2, 3, 4) and not 12 <= mod100 <= 14:
        word = "копейки"
    else:
        word = "копеек"
    return f"{n} {word}"


def counter_item_value(item) -> int:
    """Квест, ключ и записка не товар."""
    if item is None:
        return 0
    if getattr(item, "is_quest_item", False):
        return 0
    kind = getattr(item, "type", "") or ""
    if kind in {"key", "note"}:
        return 0
    try:
        return max(0, int(getattr(item, "value", 0) or 0))
    except (TypeError, ValueError):
        return 0


def can_sell_item(item) -> bool:
    return counter_item_value(item) > 0


def find_inventory_item(player, item_id: str):
    if player is None or not item_id:
        return None
    for item in getattr(player, "inventory", None) or []:
        if getattr(item, "id", None) == item_id:
            return item
    return None


def take_item_from_player(player, item_id: str) -> bool:
    if player is None or not item_id:
        return False
    kept = []
    found = False
    for item in getattr(player, "inventory", None) or []:
        if not found and getattr(item, "id", None) == item_id:
            found = True
            continue
        kept.append(item)
    if not found:
        return False
    player.inventory = kept
    eq = getattr(player, "equipped", None)
    if isinstance(eq, dict):
        for slot, held in list(eq.items()):
            if held == item_id:
                eq.pop(slot, None)
    return True


def sell_price(value: int, standing: int = 0) -> int:
    return max(1, int(value or 0) + int(standing or 0))


def buy_price(value: int, standing: int = 0) -> int:
    """Дороже продажи, иначе одно железо крутится бесконечно."""
    sold = sell_price(value, standing)
    asked = int(value or 0) * 2 - int(standing or 0)
    return max(sold + 1, asked, 1)


def quoted_price(player, item_id: str, standing=None, character_id: str = "") -> int:
    item = find_inventory_item(player, item_id)
    return sell_price(counter_item_value(item), standing_of(standing, character_id))


def merchant_record(character_id: str) -> Optional[Dict]:
    return MERCHANTS.get(character_id or "")


def can_open_shop(player, character_id: str) -> bool:
    record = merchant_record(character_id)
    if not record or player is None:
        return False
    return worn_look(player) in (record.get("looks") or ())


def refuse_shop(player, character_id: str) -> str:
    record = merchant_record(character_id)
    if not record:
        return "Лавки рядом нет."
    look = worn_look(player)
    lines = record.get("refuse") or {}
    return lines.get(look) or lines.get("clinic") or "Не торгую-с."


def sellable_items(player) -> List:
    seen = set()
    out = []
    for item in getattr(player, "inventory", None) or []:
        item_id = getattr(item, "id", None)
        if not item_id or item_id in seen or not can_sell_item(item):
            continue
        seen.add(item_id)
        out.append(item)
    return out


def apply_sell(player, item_id: str, standing=None, character_id: str = "") -> Tuple[bool, str]:
    record = merchant_record(character_id)
    if not record:
        return False, "Лавки рядом нет."
    if not can_open_shop(player, character_id):
        return False, refuse_shop(player, character_id)
    item = find_inventory_item(player, item_id)
    if not can_sell_item(item):
        return False, "Ключ да бумага не товар-с. Не возьму."
    price = sell_price(counter_item_value(item), standing_of(standing, character_id))
    if not take_item_from_player(player, item_id):
        return False, "Этого нет-с."
    player.kopecks = int(getattr(player, "kopecks", 0) or 0) + price
    return True, f"{kopeck_phrase(price)}-с. Вот получите."


def apply_buy(
    player, item_id: str, factory, standing=None, character_id: str = ""
) -> Tuple[bool, str]:
    record = merchant_record(character_id)
    if not record or factory is None:
        return False, "Лавки рядом нет."
    if not can_open_shop(player, character_id):
        return False, refuse_shop(player, character_id)
    if item_id not in (record.get("sells") or ()):
        return False, "Этого нет-с."
    sample = factory.create_item(item_id)
    if sample is None:
        return False, "Этого нет-с."
    value = int(getattr(sample, "value", 0) or 0)
    if value <= 0:
        return False, "Этого нет-с."
    price = buy_price(value, standing_of(standing, character_id))
    purse = int(getattr(player, "kopecks", 0) or 0)
    if purse < price:
        return False, "Мало-с, батюшка. В долг не даю."
    player.kopecks = purse - price
    player.inventory.append(sample)
    return True, f"{kopeck_phrase(price)}-с. Извольте, товар ваш."
