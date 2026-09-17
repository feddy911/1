"""Масло мест и вещей. Карта .txt не трогаем.

PNG из data/paintings. F4 прячет холст, подпись остаётся.
Нет файла — тихий пропуск, текст места всё равно читается.
"""
from pathlib import Path
from typing import Dict, Optional

import numpy as np

from engine.constants import BRED_MAP_ID

ROOT = Path(__file__).resolve().parents[1]
PAINTING_DIR = ROOT / "data" / "paintings"
LOCATION_DIR = PAINTING_DIR / "locations"
ITEM_DIR = PAINTING_DIR / "items"

LOCATION_FILES: Dict[str, str] = {
    "hospital_floor_1": "floor_1.png",
    "hospital_floor_2": "floor_2.png",
    "hospital_basement": "basement.png",
    "street_outside": "street.png",
    "street_traktir": "traktir.png",
    "street_tenement": "tenement.png",
    "street_canal_east": "street.png",
    BRED_MAP_ID: "bred.png",
}

ITEM_FILES: Dict[str, str] = {
    "item_knife": "knife.png",
    "potion_heal": "bottle_heal.png",
    "potion_sanity": "bottle_san.png",
    "letter_1": "letter.png",
    "note_canal": "canal_note.png",
    "note_tenement": "house_book.png",
}

# Клетка 16×24. 48×24 ≈ 4:3. 18×16 ≈ 3:4.
LOCATION_OIL_COLS = 48
LOCATION_OIL_ROWS = 24
ITEM_LOOK_COLS = 18
ITEM_LOOK_ROWS = 16

_pixels: Dict[str, np.ndarray] = {}


def oil_id_for_map(map_id: str) -> str:
    return f"map:{map_id}"


def oil_id_for_item(item_id: str) -> str:
    return f"item:{item_id}"


def _item_filename(item_id: str, item_type: str = "") -> Optional[str]:
    if item_id in ITEM_FILES:
        return ITEM_FILES[item_id]
    kind = item_type or ""
    if kind == "key" or item_id.startswith("key_"):
        return "key.png"
    if kind in ("note", "quest") or item_id.startswith(
        ("note", "diary", "document", "letter")
    ):
        return "paper.png"
    return None


def painting_path(oil_id: str, item_type: str = "") -> Optional[Path]:
    if oil_id.startswith("map:"):
        name = LOCATION_FILES.get(oil_id[4:])
        path = LOCATION_DIR / name if name else None
    elif oil_id.startswith("item:"):
        name = _item_filename(oil_id[5:], item_type)
        path = ITEM_DIR / name if name else None
    else:
        path = None
    return path if path is not None and path.is_file() else None


def load_pixels(oil_id: str, item_type: str = "") -> Optional[np.ndarray]:
    """RGBA uint8. Кэш на процесс."""
    if oil_id in _pixels:
        return _pixels[oil_id]
    path = painting_path(oil_id, item_type)
    if path is None:
        return None
    try:
        from PIL import Image
    except ImportError:
        return None
    image = Image.open(path).convert("RGBA")
    arr = np.ascontiguousarray(np.asarray(image))
    _pixels[oil_id] = arr
    return arr
