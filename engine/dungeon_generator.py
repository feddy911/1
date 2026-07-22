"""BSP-генератор подземелий для клиники."""
import random
from typing import List, Tuple, Dict


class Room:
    """Комната в подземелье."""
    def __init__(self, x: int, y: int, width: int, height: int):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.center_x = x + width // 2
        self.center_y = y + height // 2
    
    def intersects(self, other: 'Room', padding: int = 1) -> bool:
        return (self.x - padding <= other.x + other.width and
                self.x + self.width + padding >= other.x and
                self.y - padding <= other.y + other.height and
                self.y + self.height + padding >= other.y)


class BSPGenerator:
    """BSP-генератор подземелий."""
    
    def __init__(self, width: int, height: int, min_room_size: int = 4, 
                 max_room_size: int = 10, max_depth: int = 5):
        self.width = width
        self.height = height
        self.min_room_size = min_room_size
        self.max_room_size = max_room_size
        self.max_depth = max_depth
        
        self.tiles = [[0 for _ in range(width)] for _ in range(height)]
        self.rooms: List[Room] = []
    
    def generate(self) -> Tuple[List[List[int]], List[Room]]:
        self._create_rooms()
        self._connect_rooms()
        return self.tiles, self.rooms
    
    def _create_rooms(self):
        attempts = 0
        max_attempts = 100
        
        while len(self.rooms) < 8 and attempts < max_attempts:
            attempts += 1
            
            room_width = random.randint(self.min_room_size, self.max_room_size)
            room_height = random.randint(self.min_room_size, self.max_room_size)
            
            room_x = random.randint(1, self.width - room_width - 1)
            room_y = random.randint(1, self.height - room_height - 1)
            
            new_room = Room(room_x, room_y, room_width, room_height)
            
            intersects = False
            for room in self.rooms:
                if new_room.intersects(room):
                    intersects = True
                    break
            
            if not intersects:
                self.rooms.append(new_room)
                self._carve_room(new_room)
    
    def _carve_room(self, room: Room):
        for y in range(room.y, room.y + room.height):
            for x in range(room.x, room.x + room.width):
                self.tiles[y][x] = 1
    
    def _connect_rooms(self):
        for i in range(len(self.rooms) - 1):
            room1 = self.rooms[i]
            room2 = self.rooms[i + 1]
            
            if random.random() > 0.5:
                self._create_h_corridor(room1.center_x, room2.center_x, room1.center_y)
                self._create_v_corridor(room1.center_y, room2.center_y, room2.center_x)
            else:
                self._create_v_corridor(room1.center_y, room2.center_y, room1.center_x)
                self._create_h_corridor(room1.center_x, room2.center_x, room2.center_y)
    
    def _create_h_corridor(self, x1: int, x2: int, y: int):
        for x in range(min(x1, x2), max(x1, x2) + 1):
            if 0 <= y < self.height and 0 <= x < self.width:
                self.tiles[y][x] = 1
    
    def _create_v_corridor(self, y1: int, y2: int, x: int):
        for y in range(min(y1, y2), max(y1, y2) + 1):
            if 0 <= y < self.height and 0 <= x < self.width:
                self.tiles[y][x] = 1
    
    def get_available_rooms(self, player_pos: Tuple[int, int]) -> List[Room]:
        """Получить комнаты для спавна (исключая комнату игрока)."""
        player_room = None
        for room in self.rooms:
            if (room.x <= player_pos[0] < room.x + room.width and
                room.y <= player_pos[1] < room.y + room.height):
                player_room = room
                break
        
        return [r for r in self.rooms if r != player_room]
    
    def to_ascii(self) -> List[str]:
        lines = []
        for row in self.tiles:
            line = ''
            for cell in row:
                line += '.' if cell == 1 else '#'
            lines.append(line)
        return lines