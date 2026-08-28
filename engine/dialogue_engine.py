"""Система диалогов с ветками выбора."""
from typing import Optional, List, Dict, Tuple


class DialogueState:
    """Состояние текущего диалога."""

    def __init__(self, dialogue_data: Dict, flags=None, san: int = 100):
        self.dialogue_id = dialogue_data['id']
        self.character_id = dialogue_data['character_id']
        self.lines = dialogue_data['lines']
        self.by_order = {line['order_num']: line for line in self.lines}
        self.flags = set(flags or [])
        self.san = san
        self.current_order = min(self.by_order) if self.by_order else 0
        self.finished = False
        self.sanity_change_total = 0
        self.items_given: List[str] = []
        self.flags_set: List[str] = []
        self.ending_id: Optional[str] = None
        self.last_text = ''
        self.choices: List[Dict] = []

    def _is_choice(self, line: Dict) -> bool:
        group = line.get('choice_group')
        return group is not None and group != ''

    def _choice_allowed(self, line: Dict) -> bool:
        required = line.get('requires_flag')
        if required and required not in self.flags and required not in self.flags_set:
            return False
        min_san = line.get('requires_min_san')
        if min_san is not None and min_san != '' and self.san < int(min_san):
            return False
        return True

    def _apply(self, line: Dict):
        change = line.get('sanity_change') or 0
        self.sanity_change_total += change
        if line.get('gives_item_id'):
            self.items_given.append(line['gives_item_id'])
        flag = line.get('sets_flag')
        if flag:
            self.flags_set.append(flag)
            self.flags.add(flag)
        ending = line.get('ending_id')
        if ending:
            self.ending_id = ending

    def _format(self, line: Dict) -> str:
        prefix = {
            'npc': '',
            'player': '[Вы] ',
            'narrator': '— ',
        }.get(line.get('speaker') or 'npc', '')
        return f"{prefix}{line['text']}"

    def _collect_choices(self, group) -> List[Dict]:
        opts = [
            line for line in self.lines
            if line.get('choice_group') == group and self._choice_allowed(line)
        ]
        opts.sort(key=lambda line: line['order_num'])
        return opts

    def present(self) -> Tuple[str, Optional[str]]:
        """Показать текущий узел. ('text', строка), ('choices', None), ('end', None)."""
        if self.finished:
            return 'end', None
        line = self.by_order.get(self.current_order)
        if not line:
            self.finished = True
            return 'end', None
        if self._is_choice(line):
            self.choices = self._collect_choices(line.get('choice_group'))
            if not self.choices:
                self.finished = True
                return 'end', None
            return 'choices', None
        self.choices = []
        self._apply(line)
        self.last_text = self._format(line)
        return 'text', self.last_text

    def _goto(self, next_order) -> Tuple[str, Optional[str]]:
        if next_order is None or next_order == '':
            next_order = self.current_order + 1
        try:
            next_order = int(next_order)
        except (TypeError, ValueError):
            next_order = -1
        if next_order < 0 or next_order not in self.by_order:
            self.finished = True
            return 'end', None
        self.current_order = next_order
        return self.present()

    def advance(self) -> Tuple[str, Optional[str]]:
        """Дальше по линейной реплике. На выборе не двигается."""
        if self.choices:
            return 'choices', None
        if self.finished:
            return 'end', None
        line = self.by_order.get(self.current_order)
        if not line:
            self.finished = True
            return 'end', None
        return self._goto(line.get('next_order'))

    def choose(self, index: int) -> Tuple[str, Optional[str]]:
        if index < 0 or index >= len(self.choices):
            return 'choices', None
        line = self.choices[index]
        self._apply(line)
        self.last_text = self._format(line)
        self.choices = []
        return self._goto(line.get('next_order'))


class DialogueEngine:
    """Управляет диалогами."""

    def __init__(self, db_loader):
        self.db = db_loader
        self.current_dialogue: Optional[DialogueState] = None

    def start_dialogue(self, dialogue_id: str, flags=None, san: int = 100) -> bool:
        data = self.db.get_dialogue(dialogue_id)
        if not data or not data['lines']:
            return False
        self.current_dialogue = DialogueState(data, flags=flags, san=san)
        return True

    def present(self) -> Tuple[str, Optional[str]]:
        if not self.current_dialogue:
            return 'end', None
        return self.current_dialogue.present()

    def advance(self) -> Tuple[str, Optional[str]]:
        if not self.current_dialogue:
            return 'end', None
        return self.current_dialogue.advance()

    def choose(self, index: int) -> Tuple[str, Optional[str]]:
        if not self.current_dialogue:
            return 'end', None
        return self.current_dialogue.choose(index)

    def get_choices(self) -> List[str]:
        if not self.current_dialogue:
            return []
        return [line['text'] for line in self.current_dialogue.choices]

    def is_active(self) -> bool:
        return self.current_dialogue is not None and not self.current_dialogue.finished

    def finish(self):
        if not self.current_dialogue:
            return None
        result = {
            'sanity_change': self.current_dialogue.sanity_change_total,
            'items_given': self.current_dialogue.items_given.copy(),
            'flags': list(self.current_dialogue.flags_set),
            'ending_id': self.current_dialogue.ending_id,
        }
        self.current_dialogue = None
        return result

    def get_character_id(self) -> Optional[str]:
        if self.current_dialogue:
            return self.current_dialogue.character_id
        return None
