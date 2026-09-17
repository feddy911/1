"""
Петербург. Клиника. Бред.
ASCII-рогалик в стиле Достоевского.
Точка входа.
"""
import argparse
import tcod
from engine.clinic_font import load_clinic_tileset
from engine.constants import SCREEN_HEIGHT, SCREEN_WIDTH
from engine.game_engine import GameEngine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--2d",
        dest="view2d",
        action="store_true",
        help="Тот же Петербург сверху в pygame. Не analog.",
    )
    args = parser.parse_args()
    if args.view2d:
        from engine.view2d import View2D

        view = View2D()
        engine = GameEngine(None, view=view)
        try:
            engine.run()
        finally:
            view.close()
        return

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
