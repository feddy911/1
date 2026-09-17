"""Товарищи рядом. История потом скажет, кто встаёт в ряд.

Игрок всегда первый. Ещё двое — слоты. Не девятый глагол и не набор в меню.
"""
from typing import List

PARTY_MAX = 3


def party_ids(engine) -> List[str]:
    raw = [item for item in (getattr(engine, "party_ids", None) or []) if item]
    player = getattr(engine, "player", None)
    pid = getattr(player, "id", "") if player else ""
    out: List[str] = []
    if pid:
        out.append(pid)
    for item in raw:
        if item not in out:
            out.append(item)
    return out[:PARTY_MAX]


def companion_ids(engine) -> List[str]:
    ids = party_ids(engine)
    player = getattr(engine, "player", None)
    pid = getattr(player, "id", "") if player else ""
    return [item for item in ids if item != pid]


def join_party(engine, character_id: str) -> bool:
    """Встать в ряд. Сцен вступления нет — вызовет история."""
    if not character_id:
        return False
    ids = party_ids(engine)
    if character_id in ids or len(ids) >= PARTY_MAX:
        return False
    engine.party_ids = ids + [character_id]
    return True


def parse_party(payload, class_id: str = "") -> List[str]:
    raw = payload.get("party") if isinstance(payload, dict) else None
    ids = [item for item in (raw or []) if isinstance(item, str) and item]
    if class_id and class_id not in ids:
        ids = [class_id] + ids
    out: List[str] = []
    for item in ids:
        if item not in out:
            out.append(item)
    return out[:PARTY_MAX]
