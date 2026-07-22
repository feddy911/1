"""Сборщик карты из .txt блоков."""
import os
import random
from typing import List, Tuple, Dict
from engine.db_loader import DBLoader


class RoomBlock:
    """Представление блока комнаты."""
    
    def __init__(self, data: dict):
        self.id = data['id']
        self.name = data['name']
        self.description = data['description']
        self.block_type = data['block_type']
        self.width = data['width']
        self.height = data['height']
        self.layout_file = data['layout_file']
        self.doors = {
            'north': bool(data['has_door_north']),
            'south': bool(data['has_door_south']),
            'east': bool(data['has_door_east']),
            'west': bool(data['has_door_west'])
        }
        self.is_locked = bool(data['is_locked'])
        self.requires_key = data.get('requires_key')
        self.is_exit = bool(data['is_exit'])
        self.exit_type = data.get('exit_type')
        self.weight = data['weight']
        self.min_sanity = data['min_sanity']
        self.max_sanity = data['max_sanity']
        self.tiles = []
        self.spawn_points = {}
        self.rotation = 0
        self.flipped = False
    
    def load_layout(self, db: DBLoader):
        """Загрузить layout из файла."""
        file_path = os.path.join('data/blocks', self.layout_file)
        with open(file_path, 'r', encoding='utf-8') as f:
            self.tiles = [list(line.rstrip()) for line in f.readlines()]
    
    def rotate(self, times: int = 1):
        """Повернуть блок на 90 * times градусов."""
        for _ in range(times):
            self.tiles = [list(row) for row in zip(*self.tiles[::-1])]
            self.width, self.height = self.height, self.width
            new_doors = {
                'north': self.doors['west'],
                'east': self.doors['north'],
                'south': self.doors['east'],
                'west': self.doors['south']
            }
            self.doors = new_doors
            self.rotation = (self.rotation + 90) % 360
    
    def flip_horizontal(self):
        """Отразить по горизонтали."""
        self.tiles = [row[::-1] for row in self.tiles]
        self.doors['east'], self.doors['west'] = self.doors['west'], self.doors['east']
        self.flipped = not self.flipped
    
    def can_connect(self, other: 'RoomBlock', side: str) -> bool:
        """Проверить, можно ли соединить с другим блоком."""
        opposite = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east'}
        return self.doors.get(side, False) and other.doors.get(opposite[side], False)


class BlockMapGenerator:
    """Генератор карт из блоков."""
    
    def __init__(self, db: DBLoader):
        self.db = db
        self.placed_blocks = []
    
    def load_available_blocks(self, player_san: int = 100) -> List[RoomBlock]:
        """Загрузить доступные блоки из БД."""
        cursor = self.db.conn.execute(
            """SELECT * FROM room_blocks 
               WHERE min_sanity <= ? AND max_sanity >= ?
               ORDER BY weight DESC""",
            (player_san, player_san)
        )
        blocks = []
        for row in cursor.fetchall():
            block = RoomBlock(dict(row))
            block.load_layout(self.db)
            blocks.append(block)
        return blocks
    
    def generate(self, player_san: int = 100, max_blocks: int = 12) -> Tuple[List[List[str]], Dict]:
        """Сгенерировать карту из блоков."""
        available_blocks = self.load_available_blocks(player_san)
        if not available_blocks:
            return [], {}
        
        # Очищаем размещённые блоки
        self.placed_blocks = []
        
        print(f"[DEBUG] Доступно блоков: {len(available_blocks)}")
        
        # РАНДОМИЗАЦИЯ: Случайный начальный блок
        first_block = random.choice(available_blocks)
        
        # Случайная трансформация
        if random.random() < 0.5:
            rotations = random.randint(1, 3)
            for _ in range(rotations):
                first_block.rotate()
            print(f"[DEBUG] Начальный блок {first_block.id} повёрнут на {first_block.rotation}°")
        
        if random.random() < 0.3:
            first_block.flip_horizontal()
        
        self.placed_blocks.append({
            'block': first_block,
            'x': 0,
            'y': 0
        })
        
        # Пытаемся добавить блоки
        attempts = 0
        max_attempts = 2000  # УВЕЛИЧИВАЕМ
        
        while len(self.placed_blocks) < max_blocks and attempts < max_attempts:
            attempts += 1
            
            if not self.placed_blocks:
                break
            
            # Случайный базовый блок
            base = random.choice(self.placed_blocks)
            base_block = base['block']
            
            # Случайный порядок сторон
            sides = ['north', 'south', 'east', 'west']
            random.shuffle(sides)
            
            connected = False
            for side in sides:
                if not base_block.doors.get(side, False):
                    continue
                
                # Ищем подходящие блоки (БЕЗ проверки _is_placed!)
                candidates = [b for b in available_blocks 
                             if b.can_connect(base_block, side)]
                
                if not candidates:
                    continue
                
                # Случайный выбор из кандидатов
                new_block = random.choice(candidates)
                
                # Случайная трансформация
                if random.random() < 0.4:
                    rotations = random.randint(1, 3)
                    for _ in range(rotations):
                        new_block.rotate()
                
                if random.random() < 0.25:
                    new_block.flip_horizontal()
                
                # Вычисляем позицию
                offset = self._calculate_offset(base, side, new_block)
                
                # Проверяем коллизии
                if not self._has_collision(offset['x'], offset['y'], new_block):
                    self.placed_blocks.append({
                        'block': new_block,
                        'x': offset['x'],
                        'y': offset['y']
                    })
                    print(f"[DEBUG] Добавлен блок {new_block.id} в ({offset['x']},{offset['y']}) через {side}")
                    connected = True
                    break
            
            if not connected and attempts % 50 == 0:
                print(f"[DEBUG] Попытка {attempts}: не удалось добавить блок")
        
        print(f"[DEBUG] Всего размещено блоков: {len(self.placed_blocks)}")
        
        # Собираем финальную карту
        return self._build_final_map()
    
    def _is_placed(self, block: RoomBlock) -> bool:
        """Проверить, размещён ли уже блок (по позиции, не по ID)."""
        # Больше не используем — разрешаем дубли
        return False 
   
    def _calculate_diversity(self) -> float:
        """Рассчитать разнообразие размещённых блоков."""
        if not self.placed_blocks:
            return 0.0
        
        # Считаем уникальные типы блоков
        unique_types = len(set(p['block'].id for p in self.placed_blocks))
        total_blocks = len(self.placed_blocks)
        
        # Считаем количество поворотов
        rotations = sum(1 for p in self.placed_blocks if p['block'].rotation != 0)
        
        # Считаем отражения
        flips = sum(1 for p in self.placed_blocks if p['block'].flipped)
        
        # Формула разнообразия
        diversity = (unique_types / total_blocks) * 0.5
        diversity += (rotations / total_blocks) * 0.3
        diversity += (flips / total_blocks) * 0.2
        
        return diversity
    
    def _calculate_offset(self, base: Dict, side: str, new_block: RoomBlock) -> Dict:
        x, y = base['x'], base['y']
        if side == 'north':
            return {'x': x, 'y': y - new_block.height}
        elif side == 'south':
            return {'x': x, 'y': y + base['block'].height}
        elif side == 'east':
            return {'x': x + base['block'].width, 'y': y}
        elif side == 'west':
            return {'x': x - new_block.width, 'y': y}
        return {'x': x, 'y': y}
    
    def _has_collision(self, x: int, y: int, block: RoomBlock) -> bool:
        for placed in self.placed_blocks:
            px, py = placed['x'], placed['y']
            pb = placed['block']
            if not (x + block.width <= px or x >= px + pb.width or
                    y + block.height <= py or y >= py + pb.height):
                return True
        return False

    def _blocks_are_adjacent(self, b1: Dict, b2: Dict) -> bool:
        """Проверить, примыкают ли два блока друг к другу."""
        b1_right = b1['x'] + b1['block'].width
        b1_bottom = b1['y'] + b1['block'].height
        b2_right = b2['x'] + b2['block'].width
        b2_bottom = b2['y'] + b2['block'].height
        
        # Горизонтальное примыкание
        if b1_right == b2['x'] or b2_right == b1['x']:
            overlap_y = max(0, min(b1_bottom, b2_bottom) - max(b1['y'], b2['y']))
            print(f"[DEBUG] Горизонтальное примыкание, overlap_y={overlap_y}")
            return overlap_y > 0
        
        # Вертикальное примыкание
        if b1_bottom == b2['y'] or b2_bottom == b1['y']:
            overlap_x = max(0, min(b1_right, b2_right) - max(b1['x'], b2['x']))
            print(f"[DEBUG] Вертикальное примыкание, overlap_x={overlap_x}")
            return overlap_x > 0
        
        return False
    
    def _create_passages_between_blocks(self, final_map: List[List[str]]):
        """Создать проходы между примыкающими блоками."""
        # Находим границы для нормализации координат
        min_x = min(p['x'] for p in self.placed_blocks)
        min_y = min(p['y'] for p in self.placed_blocks)
        
        for i in range(len(self.placed_blocks)):
            for j in range(i + 1, len(self.placed_blocks)):
                block1 = self.placed_blocks[i]
                block2 = self.placed_blocks[j]
                
                # Проверяем, примыкают ли блоки
                if self._blocks_are_adjacent(block1, block2):
                    # Создаём ОДИН проход в месте примыкания
                    self._make_passage(final_map, block1, block2)
    
    def _make_passage(self, final_map: List[List[str]], b1: Dict, b2: Dict):
        """Создать дверь в центре стен двух примыкающих блоков."""
        b1_right = b1['x'] + b1['block'].width
        b1_bottom = b1['y'] + b1['block'].height
        b2_right = b2['x'] + b2['block'].width
        b2_bottom = b2['y'] + b2['block'].height
        
        height = len(final_map)
        width = len(final_map[0]) if height > 0 else 0
        
        # Случайный выбор: дверь (60%) или проход (40%)
        use_door = random.random() < 0.6
        passage_char = 'd' if use_door else '.'
        
        # Определяем сторону примыкания
        if b1_right == b2['x']:  # b2 справа от b1
            # Центр правой стены b1
            y1_center = b1['y'] + b1['block'].height // 2
            # Центр левой стены b2
            y2_center = b2['y'] + b2['block'].height // 2
            # Используем среднее между центрами стен
            y_passage = (y1_center + y2_center) // 2
            
            x1 = b1_right - 1  # Правая стена b1
            x2 = b2['x']       # Левая стена b2
            
            if 0 <= y_passage < height:
                if 0 <= x1 < width:
                    final_map[y_passage][x1] = passage_char
                if 0 <= x2 < width:
                    final_map[y_passage][x2] = '.'
        
        elif b2_right == b1['x']:  # b1 справа от b2
            y1_center = b1['y'] + b1['block'].height // 2
            y2_center = b2['y'] + b2['block'].height // 2
            y_passage = (y1_center + y2_center) // 2
            
            x1 = b2_right - 1
            x2 = b1['x']
            
            if 0 <= y_passage < height:
                if 0 <= x1 < width:
                    final_map[y_passage][x1] = passage_char
                if 0 <= x2 < width:
                    final_map[y_passage][x2] = '.'
        
        elif b1_bottom == b2['y']:  # b2 снизу от b1
            x1_center = b1['x'] + b1['block'].width // 2
            x2_center = b2['x'] + b2['block'].width // 2
            x_passage = (x1_center + x2_center) // 2
            
            y1 = b1_bottom - 1
            y2 = b2['y']
            
            if 0 <= x_passage < width:
                if 0 <= y1 < height:
                    final_map[y1][x_passage] = passage_char
                if 0 <= y2 < height:
                    final_map[y2][x_passage] = '.'
        
        elif b2_bottom == b1['y']:  # b1 снизу от b2
            x1_center = b1['x'] + b1['block'].width // 2
            x2_center = b2['x'] + b2['block'].width // 2
            x_passage = (x1_center + x2_center) // 2
            
            y1 = b2_bottom - 1
            y2 = b1['y']
            
            if 0 <= x_passage < width:
                if 0 <= y1 < height:
                    final_map[y1][x_passage] = passage_char
                if 0 <= y2 < height:
                    final_map[y2][x_passage] = '.'
                            
    def _create_connection(self, final_map: List[List[str]], visited: List[List[bool]], x: int, y: int):
        """Создать соединение между несвязанными областями."""
        map_height = len(final_map)
        map_width = len(final_map[0]) if map_height > 0 else 0
        
        # Ищем ближайшую посещенную клетку
        min_dist = float('inf')
        target_x, target_y = -1, -1
        
        for ty in range(map_height):
            for tx in range(map_width):
                if visited[ty][tx] and final_map[ty][tx] == '.':
                    dist = abs(tx - x) + abs(ty - y)
                    if dist < min_dist:
                        min_dist = dist
                        target_x, target_y = tx, ty
        
        # Создаём проход
        if target_x != -1 and target_y != -1:
            # Находим путь между клетками
            path = self._find_path(final_map, x, y, target_x, target_y)
            for px, py in path:
                if final_map[py][px] == '#':
                    final_map[py][px] = '.'                    
                    
    def _ensure_connectivity(self, final_map: List[List[str]], exits: List[Dict]):
        """Убедиться, что все блоки соединены между собой."""
        map_height = len(final_map)
        map_width = len(final_map[0]) if map_height > 0 else 0
        
        # Создаём матрицу для поиска в глубину
        visited = [[False for _ in range(map_width)] for _ in range(map_height)]
        
        # Находим стартовую точку (любой проход)
        start_x, start_y = -1, -1
        for y in range(map_height):
            for x in range(map_width):
                if final_map[y][x] == '.':
                    start_x, start_y = x, y
                    break
            if start_x != -1:
                break
        
        # Если не нашли проходов, возвращаемся
        if start_x == -1:
            return
        
        # Поиск в глубину для определения связности
        stack = [(start_x, start_y)]
        visited[start_y][start_x] = True
        
        while stack:
            x, y = stack.pop()
            
            # Проверяем соседние клетки
            for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                ny, nx = y + dy, x + dx
                if 0 <= ny < map_height and 0 <= nx < map_width:
                    if not visited[ny][nx] and final_map[ny][nx] == '.':
                        visited[ny][nx] = True
                        stack.append((nx, ny))
        
        # Проверяем, все ли проходимые клетки посещены
        for y in range(map_height):
            for x in range(map_width):
                if final_map[y][x] == '.' and not visited[y][x]:
                    # Найдена несвязанная область - создаём проход
                    self._create_connection(final_map, visited, x, y)

    
    def _find_path(self, final_map: List[List[str]], start_x: int, start_y: int, 
                    end_x: int, end_y: int) -> List[Tuple[int, int]]:
        """Найти путь между двумя точками."""
        map_height = len(final_map)
        map_width = len(final_map[0]) if map_height > 0 else 0
        
        # Используем BFS для поиска пути
        queue = [(start_x, start_y)]
        parent = {}
        visited = [[False for _ in range(map_width)] for _ in range(map_height)]
        visited[start_y][start_x] = True
        
        while queue:
            x, y = queue.pop(0)
            
            if x == end_x and y == end_y:
                # Восстанавливаем путь
                path = []
                while (x, y) != (start_x, start_y):
                    path.append((x, y))
                    x, y = parent[(x, y)]
                path.append((start_x, start_y))
                return path[::-1]
            
            # Проверяем соседние клетки
            for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                ny, nx = y + dy, x + dx
                if 0 <= ny < map_height and 0 <= nx < map_width:
                    if not visited[ny][nx] and final_map[ny][nx] in ('.', '#'):
                        visited[ny][nx] = True
                        parent[(nx, ny)] = (x, y)
                        queue.append((nx, ny))
        
        # Если путь не найден, возвращаем прямую линию
        path = []
        # Горизонталь
        for px in range(min(start_x, end_x), max(start_x, end_x) + 1):
            path.append((px, start_y))
        # Вертикаль
        for py in range(min(start_y, end_y) + 1, max(start_y, end_y) + 1):
            path.append((end_x, py))
        return path
 
    def _place_light_sources(self, final_map: List[List[str]], meta: Dict) -> List[Dict]:
        """Разместить источники света на карте."""
        lights = []
        height = len(final_map)
        width = len(final_map[0]) if height > 0 else 0
        
        # Получаем доступные источники света из БД
        cursor = self.db.conn.execute("SELECT * FROM light_sources")
        available_lights = [dict(row) for row in cursor.fetchall()]
        
        if not available_lights:
            return lights
        
        # Размещаем источники света (немного, как просил пользователь)
        num_lights = random.randint(3, 6)  # От 3 до 6 источников
        
        for _ in range(num_lights):
            # Случайная позиция в проходимой области
            attempts = 0
            while attempts < 50:
                x = random.randint(1, width - 2)
                y = random.randint(1, height - 2)
                
                # Проверяем, что клетка проходимая
                if final_map[y][x] == '.':
                    # Выбираем случайный тип источника
                    light_type = random.choice(available_lights)
                    
                    # Проверяем, нет ли уже источника рядом
                    too_close = False
                    for existing_light in lights:
                        dist = abs(existing_light['x'] - x) + abs(existing_light['y'] - y)
                        if dist < 5:  # Минимальное расстояние между источниками
                            too_close = True
                            break
                    
                    if not too_close:
                        lights.append({
                            'x': x,
                            'y': y,
                            'type': light_type['id'],
                            'symbol': light_type['symbol'],
                            'color': light_type['color'],
                            'radius': light_type['radius'],
                            'intensity': light_type['intensity'],
                            'flicker': bool(light_type['flicker'])
                        })
                        
                        # Помечаем клетку как источник света
                        final_map[y][x] = light_type['symbol']
                        break
                
                attempts += 1
        
        meta['light_sources'] = lights
        return lights

    def _mark_random_locked_doors(self, final_map: List[List[str]], locked_doors: List[Dict]):
        """Случайно пометить некоторые двери как запертые."""
        height = len(final_map)
        width = len(final_map[0]) if height > 0 else 0
        
        # Собираем все позиции дверей
        door_positions = []
        for y in range(height):
            for x in range(width):
                if final_map[y][x] == 'D':
                    door_positions.append((x, y))
        
        # Помечаем 30% дверей как запертые (символ 'd' — строчная)
        random.shuffle(door_positions)
        num_locked = max(1, len(door_positions) // 3)
        
        for i in range(min(num_locked, len(door_positions))):
            x, y = door_positions[i]
            final_map[y][x] = 'd'  # Строчная 'd' = запертая дверь
            
            # Добавляем в список запертых дверей
            locked_doors.append({
                'block_id': None,  # Обычная дверь между блоками
                'requires_key': random.choice(['key_warden', 'key_doctor', 'key_basement']),
                'x': x,
                'y': y
            })    
    
    def _build_final_map(self) -> Tuple[List[List[str]], Dict]:
        """Собрать финальную карту из размещённых блоков."""
        if not self.placed_blocks:
            return [], {}
        
        # Находим границы
        min_x = min(p['x'] for p in self.placed_blocks)
        min_y = min(p['y'] for p in self.placed_blocks)
        max_x = max(p['x'] + p['block'].width for p in self.placed_blocks)
        max_y = max(p['y'] + p['block'].height for p in self.placed_blocks)
        
        width = max_x - min_x
        height = max_y - min_y
        
        # ← ИСПРАВЛЕНИЕ: Инициализируем карту стенами вместо пустоты
        final_map = [['#' for _ in range(width)] for _ in range(height)]
        
        # Размещаем блоки
        exits = []
        locked_doors = []
        
        for placed in self.placed_blocks:
            block = placed['block']
            x, y = placed['x'] - min_x, placed['y'] - min_y
            
            for by, row in enumerate(block.tiles):
                for bx, char in enumerate(row):
                    if 0 <= y + by < height and 0 <= x + bx < width:
                        # ← Копируем только непустые символы
                        if char != ' ':
                            final_map[y + by][x + bx] = char
            
            if block.is_exit:
                exits.append({
                    'type': block.exit_type,
                    'x': x + block.width // 2,
                    'y': y + block.height // 2
                })
            
            if block.is_locked:
                locked_doors.append({
                    'requires_key': block.requires_key,
                    'x': x + block.width // 2,
                    'y': y + block.height // 2
                })
        
            # Регистрируем запертые двери блока
            if block.is_locked:
                locked_doors.append({
                    'block_id': block.id,
                    'requires_key': block.requires_key,
                    'x': x + block.width // 2,
                    'y': y + block.height // 2
                })
        
        # Создаём проходы между блоками
        self._create_passages_between_blocks(final_map)
        
        # ← НОВОЕ: Случайно помечаем некоторые двери как запертые
        self._mark_random_locked_doors(final_map, locked_doors) 
        
        # Проверяем, что все блоки связаны
        self._ensure_connectivity(final_map, exits)
        
        meta = {
            'exits': exits,
            'locked_doors': locked_doors,
            'blocks_placed': len(self.placed_blocks)
        }
        
        # Размещаем источники света
        self._place_light_sources(final_map, meta)
        
        return final_map, meta    
               
