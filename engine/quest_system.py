"""Система квестов и сюжета."""
import json
from typing import List, Dict, Optional


class QuestSystem:
    """Управление квестами и целями."""
    
    def __init__(self, db):
        self.db = db
        self.active_quests = []
        self.completed_quests = []
        self.found_notes = []
        self.load_quests()
    
    def load_quests(self):
        """Загрузить квесты из БД."""
        quests = self.db.get_all_quests()
        for quest_data in quests:
            quest = {
                'id': quest_data['id'],
                'title': quest_data['title'],
                'description': quest_data['description'],
                'is_completed': bool(quest_data['is_completed']),
                'required_items': json.loads(quest_data['required_items'] or '[]')
            }
            self.active_quests.append(quest)
    
    def add_note(self, note_id: str) -> Optional[str]:
        """Добавить найденную записку. Возвращает текст записки."""
        if note_id in self.found_notes:
            return None
        
        self.found_notes.append(note_id)
        note_data = self.db.get_note(note_id)
        
        if note_data:
            # Проверяем квесты
            self._check_quest_progress()
            return note_data.get('content', '')  # ← Возвращаем content
        
        return None
    
    def _check_quest_progress(self):
        """Проверить прогресс квестов."""
        for quest in self.active_quests:
            if quest['is_completed']:
                continue
            
            required = quest.get('required_items', [])
            if not required:
                continue
            
            # Проверяем, найдены ли все предметы
            if all(item in self.found_notes for item in required):
                quest['is_completed'] = True
                self.completed_quests.append(quest)
                self.active_quests.remove(quest)
    
    def get_quest_progress(self, quest_id: str) -> tuple:
        """Получить прогресс квеста (найдено, всего)."""
        for quest in self.active_quests + self.completed_quests:
            if quest['id'] == quest_id:
                required = quest.get('required_items', [])
                found = sum(1 for item in required if item in self.found_notes)
                return found, len(required)
        
        return 0, 0
    
    def get_active_quest_descriptions(self) -> List[str]:
        """Получить описания активных квестов."""
        descriptions = []
        for quest in self.active_quests:
            found, total = self.get_quest_progress(quest['id'])
            desc = f"{quest['title']}: {found}/{total} записок найдено"
            descriptions.append(desc)
        return descriptions
    
    def is_all_completed(self) -> bool:
        """Проверить, все ли квесты завершены."""
        return len(self.active_quests) == 0