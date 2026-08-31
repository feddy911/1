"""Один слот партии: JSON на диске, без pickle."""
import json
from pathlib import Path
from typing import Optional

import numpy as np

from engine.entity_factory import Character, Item

SAVE_VERSION = 1
SAVE_PATH = Path("data") / "saves" / "last.json"


def save_file_path() -> Path:
    return SAVE_PATH


def has_save(path: Optional[Path] = None) -> bool:
    target = path or SAVE_PATH
    return target.is_file()


def _entity_record(entity) -> Optional[dict]:
    entity_id = getattr(entity, "id", None)
    if not entity_id:
        return None
    if isinstance(entity, Character):
        kind = "character"
    elif isinstance(entity, Item):
        kind = "item"
    else:
        kind = "item" if getattr(entity, "type", "") in (
            "weapon", "consumable", "quest", "note", "key"
        ) else "character"
    return {
        "kind": kind,
        "id": entity_id,
        "x": int(getattr(entity, "x", 0)),
        "y": int(getattr(entity, "y", 0)),
        "hp": int(getattr(entity, "hp", 0) or 0),
    }


def dump_engine(engine) -> dict:
    """Сериализовать живую партию. Бой и диалог сохраняются как игра."""
    engine._save_current_map_state()
    map_states = {}
    for map_id, saved in engine.map_states.items():
        explored = saved.get("explored")
        if explored is None:
            explored_list = None
        else:
            explored_list = np.asarray(explored).astype(int).tolist()
        entities = []
        for entity in saved.get("entities") or []:
            record = _entity_record(entity)
            if record:
                entities.append(record)
        map_states[map_id] = {
            "tiles": ["".join(row) for row in saved.get("tiles") or []],
            "explored": explored_list,
            "entities": entities,
        }
    quest = engine.quest_system
    player = engine.player
    return {
        "version": SAVE_VERSION,
        "class_id": player.id,
        "player": {
            "x": player.x,
            "y": player.y,
            "hp": player.hp,
            "max_hp": player.max_hp,
            "san": player.san,
            "max_san": player.max_san,
            "inventory": [item.id for item in player.inventory],
        },
        "map_id": engine.current_map_id,
        "flags": sorted(engine.flags),
        "visited_regions": sorted(engine.visited_regions),
        "visited_maps": sorted(engine.visited_maps),
        "bred_seed": getattr(engine, "bred_seed", 1),
        "bred_return": getattr(engine, "bred_return", None),
        "notified_quests": list(getattr(engine, "notified_quests", []) or []),
        "fired_triggers": sorted(getattr(engine, "fired_triggers", set()) or []),
        "found_notes": list(quest.found_notes) if quest else [],
        "map_states": map_states,
    }


def write_save(engine, path: Optional[Path] = None) -> Path:
    target = path or SAVE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dump_engine(engine)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def read_save(path: Optional[Path] = None) -> Optional[dict]:
    target = path or SAVE_PATH
    if not target.is_file():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("version") != SAVE_VERSION:
        return None
    if not payload.get("class_id") or not payload.get("map_id"):
        return None
    return payload


def restore_map_states(engine, payload: dict) -> dict:
    """Собрать map_states движка из JSON."""
    states = {}
    for map_id, saved in (payload.get("map_states") or {}).items():
        tiles = [list(row) for row in saved.get("tiles") or []]
        explored_raw = saved.get("explored")
        explored = None
        if explored_raw is not None:
            explored = np.array(explored_raw, dtype=bool)
        entities = []
        for record in saved.get("entities") or []:
            kind = record.get("kind")
            entity_id = record.get("id")
            if kind == "character":
                entity = engine.entity_factory.create_character(entity_id)
            else:
                entity = engine.entity_factory.create_item(entity_id)
            if not entity:
                continue
            entity.x = int(record.get("x", 0))
            entity.y = int(record.get("y", 0))
            if kind == "character" and hasattr(entity, "hp"):
                entity.hp = int(record.get("hp") or entity.hp)
            entities.append(entity)
        states[map_id] = {
            "tiles": tiles,
            "entities": entities,
            "light_sources": [],
            "explored": explored,
        }
    return states
