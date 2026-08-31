"""Система квестов и сюжета."""
import json
from typing import List, Optional, Set


# Флаги, после которых туман на улице уже может услышать правду.
_VOICE_FLAGS = (
    "guilt_admitted",
    "sennaya_name",
    "archive_name",
    "nastasya_escape",
)


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
            self._check_quest_progress()
            return note_data.get('content', '')

        return None

    def _check_quest_progress(self):
        """Проверить прогресс квестов."""
        for quest in self.active_quests:
            if quest['is_completed']:
                continue

            required = quest.get('required_items', [])
            if not required:
                continue

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

    def get_active_quest_descriptions(self, flags: Optional[Set[str]] = None) -> List[str]:
        """Цель на HUD: имя и долг, не «N/M записок»."""
        flags = flags or set()
        if any(flag in flags for flag in _VOICE_FLAGS):
            return ["Туман на востоке улицы ждёт правду, которую вы уже сказали."]
        if len(self.found_notes) >= 3:
            return ["Бумаг довольно. Туман услышит имя — если вспомните долг."]
        return ["Вспомнить имя. Или долг. Без этого улица — стена."]

    def is_all_completed(self) -> bool:
        """Проверить, все ли квесты завершены."""
        return len(self.active_quests) == 0
