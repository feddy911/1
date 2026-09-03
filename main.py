"""
Петербург. Клиника. Бред.
ASCII-рогалик в стиле Достоевского.
Точка входа.
"""
import tcod
from engine.clinic_font import load_clinic_tileset
from engine.constants import SCREEN_HEIGHT, SCREEN_WIDTH
from engine.game_engine import GameEngine


def main():
    tileset = load_clinic_tileset()
    kwargs = {
        "columns": SCREEN_WIDTH,
        "rows": SCREEN_HEIGHT,
        "vsync": True,
        "title": "Петербург. Клиника. Бред.",
    }
    if tileset is not None:
        kwargs["tileset"] = tileset
        kwargs["width"] = tileset.tile_width * SCREEN_WIDTH
        kwargs["height"] = tileset.tile_height * SCREEN_HEIGHT
    with tcod.context.new(**kwargs) as context:
        engine = GameEngine(context, tileset)
        engine.run()


if __name__ == "__main__":
    main()
