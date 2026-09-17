"""Система видимости и освещения с raycasting."""
import math
import numpy as np
from typing import List, Dict, Optional

class FOVSystem:
    """Система поля зрения с учётом источников света и препятствий."""
    
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.light_radius = 7  # Радиус зрения игрока
        
        # Матрицы
        self.current_fov = np.zeros((height, width), dtype=bool)
        self.explored = np.zeros((height, width), dtype=bool)
        self.transparent = np.ones((height, width), dtype=bool)
        
        # Освещённость: 0.0 — нет света, 1.0+ — ярко.
        self.illumination = np.zeros((height, width), dtype=float)
        # Только пламя ламп (`*`), без зрения игрока и окон.
        self.flame_illumination = np.zeros((height, width), dtype=float)
        # Лунный свет окон (`W`), без зрения и ламп.
        self.window_illumination = np.zeros((height, width), dtype=float)
        self.flames: List = []
        
        # Прозрачность тайлов для света (из БД)
        self.tile_blocks_light = {}
    
    def set_tile_transparency(self, transparency_dict: Dict[str, int]):
        """Установить прозрачность тайлов из БД."""
        self.tile_blocks_light = transparency_dict
    
    def initialize(self, map_tiles: List[List[str]]):
        """Инициализировать систему на основе карты."""
        height = len(map_tiles)
        width = len(map_tiles[0]) if height > 0 else 0
        
        self.transparent = np.ones((height, width), dtype=bool)
        
        for y in range(height):
            for x in range(width):
                if x < width and y < height:
                    char = map_tiles[y][x]
                    if char in ('#', ' '):
                        self.transparent[y, x] = False
                    elif char == 'd':
                        self.transparent[y, x] = False
                    else:
                        self.transparent[y, x] = True
    
    def _is_blocked(self, x: int, y: int, map_tiles: List[List[str]]) -> bool:
        """Проверить, блокирует ли клетка свет."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            return True
        
        char = map_tiles[y][x]
        
        # Проверяем словарь из БД
        if char in self.tile_blocks_light:
            return bool(self.tile_blocks_light[char])
        
        # Фолбэк
        if char in ('#', ' ', 'd'):
            return True
        return False
    
    def _has_los(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        map_tiles: List[List[str]],
    ) -> bool:
        """Прямая без стены между клетками. Саму цель можно подсветить."""
        n = max(abs(x1 - x0), abs(y1 - y0))
        if n <= 1:
            return True
        for i in range(1, n):
            ix = int(round(x0 + (x1 - x0) * i / n))
            iy = int(round(y0 + (y1 - y0) * i / n))
            if (ix, iy) in ((x0, y0), (x1, y1)):
                continue
            if self._is_blocked(ix, iy, map_tiles):
                return False
        return True

    def _window_normal(
        self,
        sx: int,
        sy: int,
        map_tiles: List[List[str]],
    ) -> Optional[tuple]:
        """Окно — ламбертов полушар внутрь комнаты, не 360°."""
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            bx, by = sx - dx, sy - dy
            fx, fy = sx + dx, sy + dy
            behind = (
                True
                if not (0 <= bx < self.width and 0 <= by < self.height)
                else self._is_blocked(bx, by, map_tiles)
            )
            front = (
                False
                if not (0 <= fx < self.width and 0 <= fy < self.height)
                else not self._is_blocked(fx, fy, map_tiles)
            )
            if behind and front:
                return (dx, dy)
        return None

    @staticmethod
    def _photometric(
        dist: float,
        radius: float,
        intensity: float,
        kind: str,
        cosine: float = 1.0,
    ) -> float:
        """Пятно по диаграмме, не спицы лучей.

        Свеча / уголёк — тип A, I / r² (полярный круг).
        Фонарь на столбе — изолюкс пола E = I·h / (r²+h²)^(3/2).
        Окно — ламберт: I(φ)·cosφ / r², полушар.
        Обрез по радиусу, как луч 50% в IES, чтобы не лить через карту.
        """
        if radius <= 0 or dist > radius + 0.51:
            return 0.0
        edge = max(0.0, 1.0 - (dist / (radius + 0.35)) ** 2)
        if kind == "window":
            r0 = 0.7
            return intensity * max(0.0, cosine) / (dist * dist + r0 * r0) * edge
        if kind == "lantern":
            height = 1.15
            d2 = dist * dist + height * height
            return intensity * height / (d2 ** 1.5) * edge
        r0 = 0.5
        return intensity / (dist * dist + r0 * r0) * edge

    def _add_source(
        self,
        source: Dict,
        map_tiles: List[List[str]],
    ) -> None:
        sx = int(source["x"])
        sy = int(source["y"])
        radius = float(source.get("radius", 5) or 0)
        intensity = float(source.get("intensity", 1.0) or 0)
        symbol = source.get("symbol") or ""
        kind_id = source.get("type") or ""
        is_window = symbol == "W" or kind_id == "window"
        is_flame = (not is_window) and (
            symbol == "*" or kind_id in ("ember", "candle", "lamp", "torch", "gas_lamp")
        )
        if is_flame:
            self.flames.append((sx, sy, radius, intensity))
        if is_window:
            photo = "window"
            normal = self._window_normal(sx, sy, map_tiles)
        elif kind_id in ("ember", "candle") or (is_flame and radius <= 2 and symbol != "*"):
            photo = "point"
            normal = None
        else:
            photo = "lantern"
            normal = None
        reach = max(1, int(math.ceil(radius)) + 1)
        y0 = max(0, sy - reach)
        y1 = min(self.height, sy + reach + 1)
        x0 = max(0, sx - reach)
        x1 = min(self.width, sx + reach + 1)
        for iy in range(y0, y1):
            for ix in range(x0, x1):
                dist = math.hypot(ix - sx, iy - sy)
                cosine = 1.0
                if photo == "window" and normal is not None:
                    if dist < 1e-6:
                        cosine = 1.0
                    else:
                        cosine = ((ix - sx) * normal[0] + (iy - sy) * normal[1]) / dist
                    if cosine <= 0.0 and dist > 0.51:
                        continue
                added = self._photometric(dist, radius, intensity, photo, cosine)
                if added <= 1e-4:
                    continue
                if not self._has_los(sx, sy, ix, iy, map_tiles):
                    continue
                self.illumination[iy, ix] += added
                if is_flame:
                    self.flame_illumination[iy, ix] += added
                if is_window:
                    self.window_illumination[iy, ix] += added

    def compute_fov(self, player_x: int, player_y: int, 
                    map_tiles: List[List[str]],
                    light_sources: List[Dict] = None):
        """Вычислить видимость и освещённость."""
        if not map_tiles:
            return
        
        # Сбрасываем
        self.current_fov = np.zeros((self.height, self.width), dtype=bool)
        self.illumination = np.zeros((self.height, self.width), dtype=float)
        self.flame_illumination = np.zeros((self.height, self.width), dtype=float)
        self.window_illumination = np.zeros((self.height, self.width), dtype=float)
        self.flames = []
        
        num_rays = 360
        
        # === 1. Видимость от игрока ===
        for angle_deg in range(num_rays):
            angle_rad = math.radians(angle_deg)
            dx = math.cos(angle_rad)
            dy = math.sin(angle_rad)
            
            x = float(player_x) + 0.5
            y = float(player_y) + 0.5
            
            for step in range(self.light_radius * 2):
                ix = int(x)
                iy = int(y)
                
                if not (0 <= ix < self.width and 0 <= iy < self.height):
                    break
                
                self.current_fov[iy, ix] = True
                
                if (ix, iy) != (player_x, player_y) and self._is_blocked(ix, iy, map_tiles):
                    break
                
                x += dx
                y += dy
        
        if light_sources:
            for source in light_sources:
                self._add_source(source, map_tiles)
        
        # Обновляем explored
        self.explored = np.logical_or(self.explored, self.current_fov)

        # Зрение игрока: в палате край должен быть темнее @, не плоская заливка.
        vision_radius = max(1.0, self.light_radius * 1.15)
        visible = np.argwhere(self.current_fov)
        for iy, ix in visible:
            dist = math.hypot(int(ix) - player_x, int(iy) - player_y)
            t = min(1.0, dist / vision_radius)
            vision = 0.10 + 0.78 * ((1.0 - t) ** 1.85)
            self.illumination[int(iy), int(ix)] = min(
                1.7, float(self.illumination[int(iy), int(ix)]) + vision
            )
    
    def is_visible(self, x: int, y: int) -> bool:
        """Проверить, видна ли клетка сейчас."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            return False
        return bool(self.current_fov[y, x])
    
    def is_explored(self, x: int, y: int) -> bool:
        """Проверить, была ли клетка исследована."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            return False
        return bool(self.explored[y, x])
    
    def get_illumination(self, x: int, y: int) -> float:
        """Получить уровень освещённости клетки (0.0 — темно, 1.0+ — ярко)."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            return 0.0
        return float(self.illumination[y, x])

    def get_flame_illumination(self, x: int, y: int) -> float:
        """Свет ламп на клетке, без зрения игрока."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            return 0.0
        return float(self.flame_illumination[y, x])

    def get_window_illumination(self, x: int, y: int) -> float:
        """Лунный свет окна на клетке, без зрения игрока."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            return 0.0
        return float(self.window_illumination[y, x])
    
    def is_illuminated(self, x: int, y: int) -> bool:
        """Проверить, освещена ли клетка хотя бы одним источником."""
        return self.get_illumination(x, y) > 0.05