"""Масло в рамке диалога. Карта .txt не трогаем.

PNG из data/portraits. F4 (буквы) прячет лицо. Нет файла — тихий пропуск.
"""
from pathlib import Path
from typing import Dict, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PORTRAIT_DIR = ROOT / "data" / "portraits"

PORTRAIT_FILES: Dict[str, str] = {
    "doctor_shpilkin": "shpilkin.png",
    "patient_nastasya": "nastasya.png",
    "sanitary_panteleimon": "panteleimon.png",
    "archivist_klara": "klara.png",
    "possessed_patient": "possessed.png",
    "seeker": "seeker.png",
    "mystic": "mystic.png",
    "rebel": "rebel.png",
}

PORTRAIT_COLS = 11
# Клетка 16×24; 11×13 давало 176×312 и тянуло бюст 3:4. 11×10 ≈ 176×240.
PORTRAIT_ROWS = 10

_pixels: Dict[str, np.ndarray] = {}


def portrait_path(portrait_id: str) -> Optional[Path]:
    name = PORTRAIT_FILES.get(portrait_id)
    if not name:
        return None
    path = PORTRAIT_DIR / name
    return path if path.is_file() else None


def load_pixels(portrait_id: str) -> Optional[np.ndarray]:
    """RGBA uint8, C-contiguous. Кэш на процесс."""
    if portrait_id in _pixels:
        return _pixels[portrait_id]
    path = portrait_path(portrait_id)
    if path is None:
        return None
    try:
        from PIL import Image
    except ImportError:
        return None
    image = Image.open(path).convert("RGBA")
    arr = np.ascontiguousarray(np.asarray(image))
    _pixels[portrait_id] = arr
    return arr
