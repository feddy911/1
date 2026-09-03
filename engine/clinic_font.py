"""Шрифт клиники: кириллица, ≈, рамки диалогов.

libtcod кладёт TTF в почти квадратную клетку, а моноширинный глиф
занимает ~40% её ширины — отсюда «л е г е н д а». Здесь тайл режется
по реальному шагу буквы, затем кладётся в клетку 16×24. Маски легенды
лежат в Private Use (U+E000), не на точке и не на латинских HP/SAN.
Кириллица, диалог и HUD всегда шрифт. F4 переключает только карту.
"""
from pathlib import Path
from typing import Optional

import numpy as np
import tcod.tileset

from engine.clinic_tiles import (
    TILE_HEIGHT,
    TILE_WIDTH,
    stamp_proto_tiles,
)

ROOT = Path(__file__).resolve().parents[1]
BUNDLED_FONT = ROOT / "assets" / "fonts" / "DejaVuSansMono.ttf"
SOURCE_HEIGHT = 64

# Windows-запас, если бандл отсутствует. Не копируем эти файлы в репозиторий.
_WINDOWS_FALLBACKS = (
    Path(r"C:\Windows\Fonts\consola.ttf"),
    Path(r"C:\Windows\Fonts\cour.ttf"),
    Path(r"C:\Windows\Fonts\lucon.ttf"),
)

# А, я, ≈, ─, │, ┌ — то, что ломал стандартный CP437.
REQUIRED_CODEPOINTS = (0x0410, 0x044F, 0x2248, 0x2500, 0x2502, 0x250C)

_BOX_DRAWING = {
    0x2500: "h",   # ─
    0x2502: "v",   # │
    0x250C: "tl",  # ┌
    0x2510: "tr",  # ┐
    0x2514: "bl",  # └
    0x2518: "br",  # ┘
}


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


def glyph_width_fill(tileset, codepoint: int, threshold: int = 10) -> float:
    """Доля ширины клетки, занятая чернилами. У разъехавшегося TTF ~0.4."""
    tile = tileset.get_tile(codepoint)
    if tile is None or tile.size == 0 or tileset.tile_width <= 0:
        return 0.0
    alpha = tile[:, :, 3]
    cols = [x for x in range(alpha.shape[1]) if (alpha[:, x] > threshold).any()]
    if not cols:
        return 0.0
    return (cols[-1] - cols[0] + 1) / float(tileset.tile_width)


def _ink_columns(tile, threshold: int = 10) -> list[int]:
    alpha = tile[:, :, 3]
    return [x for x in range(alpha.shape[1]) if (alpha[:, x] > threshold).any()]


def _advance_crop(source) -> tuple[int, int]:
    """Горизонтальное окно шага: W/Ж/─, не em-квадрат libtcod."""
    cols: list[int] = []
    for ch in "WЖM─":
        cols.extend(_ink_columns(source.get_tile(ord(ch))))
    if not cols:
        return 0, source.tile_width
    pad = 1
    x0 = max(0, min(cols) - pad)
    x1 = min(source.tile_width, max(cols) + pad + 1)
    return x0, x1


def _resize_rgba(img: np.ndarray, dest_h: int, dest_w: int) -> np.ndarray:
    src_h, src_w = img.shape[:2]
    if src_h == dest_h and src_w == dest_w:
        return np.ascontiguousarray(img)
    ys = np.linspace(0, src_h - 1, dest_h)
    xs = np.linspace(0, src_w - 1, dest_w)
    y0 = np.floor(ys).astype(np.int32)
    x0 = np.floor(xs).astype(np.int32)
    y1 = np.clip(y0 + 1, 0, src_h - 1)
    x1 = np.clip(x0 + 1, 0, src_w - 1)
    img_f = img.astype(np.float32)
    tl = img_f[y0[:, None], x0]
    tr = img_f[y0[:, None], x1]
    bl = img_f[y1[:, None], x0]
    br = img_f[y1[:, None], x1]
    wy = (ys - y0).astype(np.float32)[:, None, None]
    wx = (xs - x0).astype(np.float32)[None, :, None]
    out = (
        tl * (1 - wy) * (1 - wx)
        + tr * (1 - wy) * wx
        + bl * wy * (1 - wx)
        + br * wy * wx
    )
    return np.clip(out, 0, 255).astype(np.uint8)


def _codepoints_to_pack() -> list[int]:
    cps = set()
    cps.update(range(0x20, 0x7F))
    cps.update(range(0xA0, 0x100))
    cps.update(range(0x400, 0x460))
    cps.update(range(0x2010, 0x2028))
    cps.update(range(0x2500, 0x2570))
    cps.add(0x2248)
    cps.add(0x25B6)
    return sorted(cps)


def _paint_box_drawing(tileset) -> None:
    """Рамки из TTF не дотягиваются до края обрезанной клетки — рисуем сами."""
    th, tw = tileset.tile_height, tileset.tile_width
    h_thick = 2 if th >= 16 else 1
    v_thick = 2 if tw >= 14 else 1
    cy = max(0, (th - h_thick) // 2)
    cx = max(0, (tw - v_thick) // 2)

    def blank() -> np.ndarray:
        return np.zeros((th, tw, 4), dtype=np.uint8)

    def stroke(tile: np.ndarray, rows, cols) -> None:
        tile[rows, cols, :] = 255

    tiles = {}
    h = blank()
    stroke(h, slice(cy, cy + h_thick), slice(None))
    tiles["h"] = h
    v = blank()
    stroke(v, slice(None), slice(cx, cx + v_thick))
    tiles["v"] = v
    tl = blank()
    stroke(tl, slice(cy, cy + h_thick), slice(cx, None))
    stroke(tl, slice(cy, None), slice(cx, cx + v_thick))
    tiles["tl"] = tl
    tr = blank()
    stroke(tr, slice(cy, cy + h_thick), slice(None, cx + v_thick))
    stroke(tr, slice(cy, None), slice(cx, cx + v_thick))
    tiles["tr"] = tr
    bl = blank()
    stroke(bl, slice(cy, cy + h_thick), slice(cx, None))
    stroke(bl, slice(None, cy + h_thick), slice(cx, cx + v_thick))
    tiles["bl"] = bl
    br = blank()
    stroke(br, slice(cy, cy + h_thick), slice(None, cx + v_thick))
    stroke(br, slice(None, cy + h_thick), slice(cx, cx + v_thick))
    tiles["br"] = br

    for code, kind in _BOX_DRAWING.items():
        tileset[code] = tiles[kind]


def apply_sprite_mode(tileset, sprites: bool, font_glyphs=None) -> bool:
    """Флаг F4. Маски уже в PUA, буквы DejaVu не снимаем."""
    if tileset is None:
        return False
    if not getattr(tileset, "_clinic_sprites_ready", False):
        return False
    tileset._clinic_sprites = bool(sprites)
    return True


def _pack_tight_tileset(source, sprites: bool = True):
    x0, x1 = _advance_crop(source)
    packed = tcod.tileset.Tileset(TILE_WIDTH, TILE_HEIGHT)
    for code in _codepoints_to_pack():
        cropped = source.get_tile(code)[:, x0:x1]
        packed[code] = _resize_rgba(cropped, TILE_HEIGHT, TILE_WIDTH)
    _paint_box_drawing(packed)
    stamp_proto_tiles(packed)
    packed._clinic_sprites = bool(sprites)
    return packed


def load_clinic_tileset(path: Optional[Path] = None, sprites: bool = True):
    """TrueType, обрезанный по шагу буквы. None — пусть tcod возьмёт свой."""
    font_path = path or find_font_path()
    if font_path is None:
        return None
    source = tcod.tileset.load_truetype_font(str(font_path), 0, SOURCE_HEIGHT)
    return _pack_tight_tileset(source, sprites=sprites)
