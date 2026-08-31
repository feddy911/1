"""Шрифт клиники: кириллица, ≈, рамки диалогов."""
from pathlib import Path
from typing import Optional

import tcod.tileset

ROOT = Path(__file__).resolve().parents[1]
BUNDLED_FONT = ROOT / "assets" / "fonts" / "DejaVuSansMono.ttf"
TILE_HEIGHT = 16

# Windows-запас, если бандл отсутствует. Не копируем эти файлы в репозиторий.
_WINDOWS_FALLBACKS = (
    Path(r"C:\Windows\Fonts\consola.ttf"),
    Path(r"C:\Windows\Fonts\cour.ttf"),
    Path(r"C:\Windows\Fonts\lucon.ttf"),
)

# А, я, ≈, ─, │, ┌ — то, что ломал стандартный CP437.
REQUIRED_CODEPOINTS = (0x0410, 0x044F, 0x2248, 0x2500, 0x2502, 0x250C)


def font_candidates() -> list[Path]:
    found = []
    if BUNDLED_FONT.is_file():
        found.append(BUNDLED_FONT)
    for path in _WINDOWS_FALLBACKS:
        if path.is_file() and path not in found:
            found.append(path)
    return found


def find_font_path() -> Optional[Path]:
    paths = font_candidates()
    return paths[0] if paths else None


def glyph_is_drawn(tileset, codepoint: int) -> bool:
    tile = tileset.get_tile(codepoint)
    if tile is None or tile.size == 0:
        return False
    return int(tile[:, :, 3].sum()) > 0


def load_clinic_tileset(path: Optional[Path] = None):
    """TrueType-тайлсет. None — пусть tcod возьмёт свой, хуже кириллицы."""
    font_path = path or find_font_path()
    if font_path is None:
        return None
    return tcod.tileset.load_truetype_font(str(font_path), 0, TILE_HEIGHT)
