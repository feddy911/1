"""Система диалогов с ветками выбора."""
from typing import Optional, List, Dict, Tuple

from engine.quest_system import DEBT_FLAGS, NAME_FLAGS, enrich_flags
from engine.rpg_system import SAN_SPEECH_CHARACTERS, SAN_SPEECH_FLAGS, SKILL_NAMES
from engine.shop import (
    counter_item_value,
    find_inventory_item,
    kopeck_phrase,
    quoted_price,
    take_item_from_player,
)

TRUTH_FLAGS = NAME_FLAGS | DEBT_FLAGS


def _is_lie_line(line: Dict) -> bool:
    flag = line.get("is_lie")
    if flag in (None, "", 0, "0"):
        return False
    return True


def _effective_san(line: Dict, character_id=None) -> int:
    change = int(line.get("sanity_change") or 0)
    flag = line.get("sets_flag")
    if character_id in SAN_SPEECH_CHARACTERS or flag in SAN_SPEECH_FLAGS:
        return 0
    return change


def choice_stakes(line: Dict, character_id=None, flags=None, by_order=None) -> str:
    """Что ответ даёт или забирает. Пусто, если ничего."""
    bits = []
    held = set(flags or ())
    flag = (line.get("sets_flag") or "").strip()
    if flag == "nastasya_escape" and flag not in held:
        bits.append("долг: Настасье")
    elif flag == "guilt_admitted" and flag not in held:
        bits.append("долг: Лизавете")
    elif flag == "archive_name" and flag not in held:
        bits.append("имя")
    change = _effective_san(line, character_id)
    if change:
        bits.append(f"воля {change:+d}")
    ending = (line.get("ending_id") or "").strip()
    if not ending and by_order:
        nxt = line.get("next_order")
        try:
            dest = by_order.get(int(nxt))
        except (TypeError, ValueError):
            dest = None
        if dest:
            ending = (dest.get("ending_id") or "").strip()
    if ending == "stay":
        bits.append("остаться")
    elif ending == "flee":
        bits.append("уйти")
    return ", ".join(bits)


def choice_prefix(line: Dict, player=None, character_id=None, flags=None, by_order=None) -> str:
    """Метка умения, лжи и ставки. Текст реплики не трогает."""
    bits = []
    skill_id = (line.get("skill_id") or "").strip()
    if skill_id:
        name = SKILL_NAMES.get(skill_id, skill_id)
        if player is not None:
            from engine.rpg_system import CHECK_DC, skill_modifier
            from engine.talent_system import has_reroll

            modifier = skill_modifier(player, skill_id)
            chunk = f"{name}: 3d6{modifier:+d} ≥ {CHECK_DC}"
            if has_reroll(player, skill_id):
                chunk += ", повтор"
            bits.append(f"[{chunk}]")
        else:
            bits.append(f"[{name}]")
    if _is_lie_line(line):
        bits.append("[ложь]")
    stakes = choice_stakes(line, character_id=character_id, flags=flags, by_order=by_order)
    if stakes:
        bits.append(f"({stakes})")
    return " ".join(bits)


def format_choice_label(line: Dict, player=None, character_id=None, flags=None, by_order=None) -> str:
    tag = choice_prefix(
        line, player, character_id=character_id, flags=flags, by_order=by_order
    )
    text = line.get("text") or ""
    if tag:
        return f"{tag} {text}"
    return text


def format_check_banner(skill_id: str, total: int, target: int, success: bool, bonus: int = 0) -> str:
    name = SKILL_NAMES.get(skill_id, skill_id)
    outcome = "успех" if success else "провал"
    shown = f"{total}{bonus:+d}" if bonus else str(total)
    return f"{name}: {shown} ≥ {target} — {outcome}"


class DialogueState:
    """Состояние текущего диалога."""

    def __init__(
        self, dialogue_data: Dict, flags=None, san: int = 100, player=None, standing=None
    ):
        self.dialogue_id = dialogue_data['id']
        self.character_id = dialogue_data['character_id']
        self.lines = dialogue_data['lines']
        self.by_order = {line['order_num']: line for line in self.lines}
        self.flags = enrich_flags(flags)
        from engine.look_memory import pocket_flags, sight_and_memory_flags

        self.flags |= sight_and_memory_flags(
            player, standing=standing, character_id=self.character_id
        )
        self.flags |= pocket_flags(player)
        self.san = san
        self.player = player
        self.standing = standing if isinstance(standing, dict) else {}
        self._truths_held = TRUTH_FLAGS & set(self.flags)
        self.current_order = min(self.by_order) if self.by_order else 0
        self.finished = False
        self.sanity_change_total = 0
        self.standing_delta = 0
        self._lied = False
        self.items_given: List[str] = []
        self.items_taken: List[str] = []
        self.kopecks_delta = 0
        self._quoted_price = None
        self.flags_set: List[str] = []
        self.ending_id: Optional[str] = None
        self.last_text = ''
        self.last_check = ''
        self.choices: List[Dict] = []

    def _is_choice(self, line: Dict) -> bool:
        group = line.get('choice_group')
        return group is not None and group != ''

    def _choice_allowed(self, line: Dict) -> bool:
        required = line.get('requires_flag')
        if required and required not in self.flags and required not in self.flags_set:
            return False
        # Бумага уже стала долгом — не предлагать вторую «Лизавете».
        if (
            required == "knows_lizaveta"
            and ("guilt_admitted" in self.flags or "guilt_admitted" in self.flags_set)
        ):
            return False
        min_san = line.get('requires_min_san')
        if min_san is not None and min_san != '' and self.san < int(min_san):
            return False
        return True

    def _apply(self, line: Dict):
        change = line.get('sanity_change') or 0
        flag = line.get('sets_flag')
        if self.character_id in SAN_SPEECH_CHARACTERS or flag in SAN_SPEECH_FLAGS:
            change = 0
        self.sanity_change_total += change
        if line.get('gives_item_id'):
            self.items_given.append(line['gives_item_id'])
        take_id = (line.get("takes_item_id") or "").strip()
        if take_id and self.player is not None:
            held = find_inventory_item(self.player, take_id)
            if counter_item_value(held) > 0:
                price = quoted_price(
                    self.player, take_id, self.standing, self.character_id
                )
                if take_item_from_player(self.player, take_id):
                    self._quoted_price = price
                    self.items_taken.append(take_id)
                    self.kopecks_delta += price
                    self.player.kopecks = (
                        int(getattr(self.player, "kopecks", 0) or 0) + price
                    )
        if flag:
            self.flags_set.append(flag)
            self.flags.add(flag)
        if _is_lie_line(line) and line.get("speaker") == "player":
            self._lied = True
            self.standing_delta -= 1
        elif (
            flag
            and str(flag).startswith("spoke_")
            and not self._lied
        ):
            self.standing_delta += 1
        ending = line.get('ending_id')
        if ending:
            self.ending_id = ending

    def _skill_roll(self, line: Dict):
        """3d6 умения. Нет игрока — без броска. Правду не снимаем."""
        skill_id = (line.get("skill_id") or "").strip()
        if not skill_id or self.player is None:
            return None
        from engine.rpg_system import skill_modifier
        from engine.talent_system import roll_verb

        check = roll_verb(self.player, skill_id)
        bonus = skill_modifier(self.player, skill_id)
        self.last_check = format_check_banner(
            skill_id, check.total, check.target, check.success, bonus
        )
        return check

    def _skill_failed(self, line: Dict) -> bool:
        check = self._skill_roll(line)
        if check is None:
            return False
        return not check.success

    def _choice_next(self, line: Dict, failed: bool):
        if failed:
            nxt = line.get("fail_next_order")
            if nxt is not None and nxt != "":
                return nxt
        return line.get("next_order")

    def _format(self, line: Dict) -> str:
        prefix = {
            'npc': '',
            'player': '[Вы] ',
            'narrator': '— ',
        }.get(line.get('speaker') or 'npc', '')
        text = line.get("text") or ""
        if "{price}" in text:
            price = self._quoted_price
            if price is None:
                take_id = (line.get("takes_item_id") or "").strip()
                price = quoted_price(
                    self.player, take_id, self.standing, self.character_id
                )
            text = text.replace("{price}", kopeck_phrase(price))
        return f"{prefix}{text}"

    def _collect_choices(self, group) -> List[Dict]:
        opts = [
            line for line in self.lines
            if line.get('choice_group') == group and self._choice_allowed(line)
        ]
        opts.sort(key=lambda line: line['order_num'])
        return opts

    def _skip_disallowed_text(self) -> Optional[Dict]:
        """Реплики с requires_flag, которые не проходят — шаг к следующему номеру."""
        seen = set()
        while self.current_order not in seen:
            seen.add(self.current_order)
            line = self.by_order.get(self.current_order)
            if not line:
                return None
            if self._is_choice(line) or self._choice_allowed(line):
                return line
            nxt = min(
                (n for n in self.by_order if n > self.current_order),
                default=None,
            )
            if nxt is None:
                return None
            self.current_order = nxt
        return None

    def present(self) -> Tuple[str, Optional[str]]:
        """Показать текущий узел. ('text', строка), ('choices', None), ('end', None)."""
        if self.finished:
            return 'end', None
        line = self._skip_disallowed_text()
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
        failed = self._skill_failed(line)
        self._apply(line)
        self.flags |= self._truths_held
        self.last_text = self._format(line)
        self.choices = []
        return self._goto(self._choice_next(line, failed))


class DialogueEngine:
    """Управляет диалогами."""

    def __init__(self, db_loader):
        self.db = db_loader
        self.current_dialogue: Optional[DialogueState] = None

    def start_dialogue(
        self, dialogue_id: str, flags=None, san: int = 100, player=None, standing=None
    ) -> bool:
        data = self.db.get_dialogue(dialogue_id)
        if not data or not data['lines']:
            return False
        self.current_dialogue = DialogueState(
            data, flags=flags, san=san, player=player, standing=standing
        )
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
        player = self.current_dialogue.player
        return [
            format_choice_label(
                line,
                player,
                character_id=self.current_dialogue.character_id,
                flags=self.current_dialogue.flags,
                by_order=self.current_dialogue.by_order,
            )
            for line in self.current_dialogue.choices
        ]

    def get_check_banner(self) -> str:
        if not self.current_dialogue:
            return ""
        return self.current_dialogue.last_check or ""

    def is_active(self) -> bool:
        return self.current_dialogue is not None and not self.current_dialogue.finished

    def finish(self):
        if not self.current_dialogue:
            return None
        result = {
            'sanity_change': self.current_dialogue.sanity_change_total,
            'items_given': self.current_dialogue.items_given.copy(),
            'items_taken': self.current_dialogue.items_taken.copy(),
            'kopecks_delta': self.current_dialogue.kopecks_delta,
            'flags': list(self.current_dialogue.flags_set),
            'ending_id': self.current_dialogue.ending_id,
            'character_id': self.current_dialogue.character_id,
            'standing_delta': self.current_dialogue.standing_delta,
        }
        self.current_dialogue = None
        return result

    def get_character_id(self) -> Optional[str]:
        if self.current_dialogue:
            return self.current_dialogue.character_id
        return None
