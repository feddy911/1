"""
Петербург. Клиника. Бред.
ASCII-рогалик в стиле Достоевского.
Точка входа.
"""
import tcod
from engine.game_engine import GameEngine
from engine.constants import SCREEN_WIDTH, SCREEN_HEIGHT


def main():
    # Создаем контекст через new_terminal
    with tcod.context.new_terminal(
        SCREEN_WIDTH, 
        SCREEN_HEIGHT,
        vsync=True,
    ) as context:
        engine = GameEngine(context)
        engine.run()


if __name__ == '__main__':
    main()