"""Чернила клиники: 18 цветов.

Тайлсет будет красить глиф этими чернилами, как Qud букву.
Не виридиан, не зелень терминала. Исследованное — затемнение к пустоте,
не новые чернила.
"""
from typing import Dict, Iterable, List, Tuple

# Имя → живой hex из tile_colors / HUD. Ровно 18.
INKS: Dict[str, str] = {
    "void": "#0a0c10",  # пустота
    "soot": "#1a2028",  # смоль пола
    "graphite": "#3e4854",  # грифель стены
    "slate": "#7a8694",  # сланец штриха
    "ash": "#96a0aa",  # зола HUD
    "linen": "#f0f0f8",  # халат
    "wood": "#5a4030",  # дерево мебели
    "ochre": "#d4b080",  # охра / желчь
    "paper": "#dcc896",  # бумага диалога
    "jamb": "#7a4a18",  # косяк
    "brass": "#b4a032",  # латунь лампы
    "lamp": "#fff064",  # золото огня
    "door": "#ffd080",  # дверь
    "frost": "#c8e0ff",  # мороз окна
    "ice": "#4a6a88",  # лёд / канал
    "canal": "#0c1828",  # вода
    "blood": "#b43232",  # кровь каймы
    "rust": "#ff8866",  # ржавчина замка
}

# Глиф → (fg, bg, подпись). Только имена из INKS.
TILE_INKS: Dict[str, Tuple[str, str, str]] = {
    "#": ("slate", "graphite", "Стена"),
    ".": ("slate", "soot", "Пол"),
    " ": ("graphite", "void", "Пустота"),
    "D": ("door", "jamb", "Дверь"),
    "d": ("rust", "soot", "Запертая дверь"),
    "'": ("lamp", "jamb", "Открытая дверь"),
    "B": ("ochre", "wood", "Кровать"),
    "T": ("ochre", "wood", "Стол"),
    "C": ("ochre", "wood", "Стул"),
    "H": ("ochre", "wood", "Шкаф"),
    "O": ("ochre", "wood", "Письменный стол"),
    '"': ("paper", "graphite", "Картина"),
    "E": ("frost", "ice", "Выход"),
    "S": ("frost", "ice", "Лестница вверх"),
    "s": ("frost", "canal", "Лестница вниз"),
    "W": ("frost", "ice", "Окно"),
    "*": ("lamp", "brass", "Источник света"),
    "+": ("rust", "blood", "Расходник"),
    "=": ("ice", "canal", "Канал"),
    "!": ("ochre", "wood", "Предмет"),
    ")": ("ochre", "wood", "Предмет"),
    "≈": ("paper", "wood", "Записка"),
    "~": ("paper", "wood", "Записка"),
    "&": ("blood", "graphite", "Человек"),
    "@": ("linen", "graphite", "Игрок"),
}

EXPLORED_MIX = 0.48


def hex_to_rgb(color: str) -> Tuple[int, int, int]:
    raw = (color or "").strip().lstrip("#")
    if len(raw) != 6:
        return 100, 100, 100
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"


def darken_hex(color: str, factor: float = EXPLORED_MIX) -> str:
    """Смешать чернила с пустотой. Новых слотов палитры не даёт."""
    r, g, b = hex_to_rgb(color)
    vr, vg, vb = hex_to_rgb(INKS["void"])
    t = max(0.0, min(1.0, factor))
    return rgb_to_hex(
        (
            int(r * t + vr * (1.0 - t)),
            int(g * t + vg * (1.0 - t)),
            int(b * t + vb * (1.0 - t)),
        )
    )


def ink_hex(name: str) -> str:
    return INKS[name]


def is_viridian(color: str) -> bool:
    """Терминальная зелень / виридиан Qud: G явно выше R и B."""
    r, g, b = hex_to_rgb(color)
    return g > r + 28 and g > b + 28 and g > 80


def iter_tile_colors() -> List[Tuple[str, str, str, str]]:
    rows = []
    for symbol, (fg, bg, desc) in TILE_INKS.items():
        rows.append((symbol, INKS[fg], INKS[bg], desc))
    return rows


def iter_explored_colors() -> List[Tuple[str, str, str]]:
    rows = []
    for symbol, (fg, bg, _desc) in TILE_INKS.items():
        rows.append((symbol, darken_hex(INKS[fg]), darken_hex(INKS[bg])))
    return rows


def visible_color_dicts() -> Dict[str, Dict[str, str]]:
    return {
        symbol: {"fg": INKS[fg], "bg": INKS[bg]}
        for symbol, (fg, bg, _desc) in TILE_INKS.items()
    }


def explored_color_dicts() -> Dict[str, Dict[str, str]]:
    return {
        symbol: {"fg": darken_hex(INKS[fg]), "bg": darken_hex(INKS[bg])}
        for symbol, (fg, bg, _desc) in TILE_INKS.items()
    }


def all_ink_hexes() -> Iterable[str]:
    return INKS.values()
