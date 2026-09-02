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
        
        # === 2. Освещение от источников света с затуханием ===
        if light_sources:
            for source in light_sources:
                sx = source['x']
                sy = source['y']
                radius = source.get('radius', 5)
                intensity = source.get('intensity', 1.0)
                symbol = source.get('symbol', '*')
                is_flame = symbol == '*'
                is_window = symbol == 'W'
                if is_flame:
                    self.flames.append((sx, sy, radius, intensity))
                
                for angle_deg in range(num_rays):
                    angle_rad = math.radians(angle_deg)
                    dx = math.cos(angle_rad)
                    dy = math.sin(angle_rad)
                    
                    x = float(sx) + 0.5
                    y = float(sy) + 0.5
                    
                    for step in range(max(1, radius) * 2):
                        ix = int(x)
                        iy = int(y)
                        
                        if not (0 <= ix < self.width and 0 <= iy < self.height):
                            break
                        
                        dist = math.sqrt((ix - sx) ** 2 + (iy - sy) ** 2)
                        
                        if radius > 0 and dist <= radius:
                            t = max(0.0, 1.0 - (dist / radius))
                            # Окно: круче к стеклу, иначе зрение @ заливает пятно.
                            falloff = (t ** 1.85) if is_window else t
                            added = intensity * falloff
                            self.illumination[iy, ix] += added
                            if is_flame:
                                self.flame_illumination[iy, ix] += added
                            if is_window:
                                self.window_illumination[iy, ix] += added
                        
                        if (ix, iy) != (sx, sy) and self._is_blocked(ix, iy, map_tiles):
                            break
                        
                        x += dx
                        y += dy
        
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