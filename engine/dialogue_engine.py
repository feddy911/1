"""Система диалогов."""
from typing import Optional, List, Dict


class DialogueState:
    """Состояние текущего диалога."""
    def __init__(self, dialogue_data: Dict):
        self.dialogue_id = dialogue_data['id']
        self.character_id = dialogue_data['character_id']
        self.lines = dialogue_data['lines']
        self.current_index = 0
        self.finished = False
        self.messages: List[str] = []
        self.sanity_change_total = 0
        self.items_given: List[str] = []
    
    def advance(self) -> Optional[str]:
        """Перейти к следующей реплике. Возвращает текст или None если конец."""
        if self.current_index >= len(self.lines):
            self.finished = True
            return None
        
        line = self.lines[self.current_index]
        self.current_index += 1
        
        # Формируем строку с указанием говорящего
        speaker_prefix = {
            'npc': '',
            'player': '[Вы] ',
            'narrator': '— '
        }
        prefix = speaker_prefix.get(line['speaker'], '')
        text = f"{prefix}{line['text']}"
        
        # Применяем эффекты
        if line.get('sanity_change'):
            self.sanity_change_total += line['sanity_change']
        if line.get('gives_item_id'):
            self.items_given.append(line['gives_item_id'])
        
        return text


class DialogueEngine:
    """Управляет диалогами."""
    
    def __init__(self, db_loader):
        self.db = db_loader
        self.current_dialogue: Optional[DialogueState] = None
    
    def start_dialogue(self, dialogue_id: str) -> bool:
        """Начать диалог. Возвращает True если удалось."""
        data = self.db.get_dialogue(dialogue_id)
        if not data or not data['lines']:
            return False
        self.current_dialogue = DialogueState(data)
        return True
    
    def advance(self) -> Optional[str]:
        """Перейти к следующей реплике."""
        if not self.current_dialogue:
            return None
        return self.current_dialogue.advance()
    
    def is_active(self) -> bool:
        return self.current_dialogue is not None and not self.current_dialogue.finished
    
    def finish(self):
        """Завершить текущий диалог и вернуть накопленные эффекты."""
        if not self.current_dialogue:
            return None
        result = {
            'sanity_change': self.current_dialogue.sanity_change_total,
            'items_given': self.current_dialogue.items_given.copy()
        }
        self.current_dialogue = None
        return result
    
    def get_character_id(self) -> Optional[str]:
        if self.current_dialogue:
            return self.current_dialogue.character_id
        return None
