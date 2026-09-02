"""Система квестов и сюжета."""
import json
from typing import List, Optional, Set


# Имя — назвал себя. Долг — кому должен. Туман слышит только оба.
NAME_FLAGS = frozenset({"archive_name", "sennaya_name"})
DEBT_FLAGS = frozenset({"guilt_admitted", "nastasya_escape"})


def has_name(flags: Optional[Set[str]] = None) -> bool:
    return bool(set(flags or ()) & NAME_FLAGS)


def has_debt(flags: Optional[Set[str]] = None) -> bool:
    return bool(set(flags or ()) & DEBT_FLAGS)


def debt_face(flags: Optional[Set[str]] = None) -> str:
    """Кому должны: Лизавете в канале, Настасье — выход."""
    flags = set(flags or ())
    names = []
    if "guilt_admitted" in flags:
        names.append("Лизавете")
    if "nastasya_escape" in flags:
        names.append("Настасье")
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return " и ".join(names)


def can_pass_fog(flags: Optional[Set[str]] = None) -> bool:
    return has_name(flags) and has_debt(flags)


def enrich_flags(flags: Optional[Set[str]] = None) -> Set[str]:
    """Производные флаги для веток диалога: has_name / has_debt / has_both."""
    filled = set(flags or ())
    if has_name(filled):
        filled.add("has_name")
    if has_debt(filled):
        filled.add("has_debt")
    if "has_name" in filled and "has_debt" in filled:
        filled.add("has_both")
    return filled


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
        """Цель на HUD: имя и долг по отдельности, не «N/M записок»."""
        flags = flags or set()
        named = has_name(flags)
        owed = has_debt(flags)
        face = debt_face(flags)
        if named and owed:
            whom = f" ({face})" if face else ""
            return [f"Имя и долг{whom} сказаны. Туман на востоке улицы уже слышал."]
        if named:
            return ["Имя есть. Долг ещё в коридоре. Туман на востоке ждёт оба."]
        if owed:
            whom = face or "долг"
            return [f"Долг — {whom}. Имени туман не слышал."]
        return ["Вспомнить имя. И долг. Без обоих улица — стена."]

    def is_all_completed(self) -> bool:
        """Проверить, все ли квесты завершены."""
        return len(self.active_quests) == 0
