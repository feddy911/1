"""Клавиши ответа в диалоге. Рамка рисует 1..N, ввод должен покрывать N."""

from typing import Optional

MAX_DIALOGUE_CHOICES = 9


def choice_index_from_key(sym_name: str) -> Optional[int]:
    """N1–N9 и KP_1–KP_9 → индекс 0..8. F5 и прочее не считаются."""
    name = (sym_name or "").upper()
    digits = ""
    if name.startswith("KP_") and name[3:].isdigit():
        digits = name[3:]
    elif name.startswith("N") and name[1:].isdigit() and not name.startswith("N0"):
        digits = name[1:]
    else:
        return None
    number = int(digits)
    if 1 <= number <= MAX_DIALOGUE_CHOICES:
        return number - 1
    return None
