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
        
        # ← НОВОЕ: Матрица освещённости (0.0 — нет света, 1.0+ — яркий свет)
        self.illumination = np.zeros((height, width), dtype=float)
        
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
                
                for angle_deg in range(num_rays):
                    angle_rad = math.radians(angle_deg)
                    dx = math.cos(angle_rad)
                    dy = math.sin(angle_rad)
                    
                    x = float(sx) + 0.5
                    y = float(sy) + 0.5
                    
                    for step in range(radius * 2):
                        ix = int(x)
                        iy = int(y)
                        
                        if not (0 <= ix < self.width and 0 <= iy < self.height):
                            break
                        
                        # ← НОВОЕ: Затухание пропорционально расстоянию
                        # Используем квадратичное затухание для более реалистичного эффекта
                        dist = math.sqrt((ix - sx) ** 2 + (iy - sy) ** 2)
                        
                        if dist <= radius:
                            # Линейное затухание: 1.0 у источника, 0.0 на границе радиуса
                            falloff = 1.0 - (dist / radius)
                            falloff = max(0.0, min(1.0, falloff))
                            
                            # Добавляем освещённость с учётом интенсивности и затухания
                            self.illumination[iy, ix] += intensity * falloff
                        
                        if (ix, iy) != (sx, sy) and self._is_blocked(ix, iy, map_tiles):
                            break
                        
                        x += dx
                        y += dy
        
        # Обновляем explored
        self.explored = np.logical_or(self.explored, self.current_fov)
    
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
    
    def is_illuminated(self, x: int, y: int) -> bool:
        """Проверить, освещена ли клетка хотя бы одним источником."""
        return self.get_illumination(x, y) > 0.05