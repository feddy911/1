"""Тихие клики без файлов и без зависимости от микшера.

Партия уже читается. Звук — не саундтрек: бумага, дверь, финал.
Молчит, если платформа не умеет или что-то сломалось.
"""
import io
import math
import struct
import threading
import wave
from typing import Dict

_ENABLED = True
_lock = threading.Lock()
_cache: Dict[str, bytes] = {}

_RATE = 22050


def set_enabled(value: bool) -> None:
    global _ENABLED
    _ENABLED = bool(value)


def is_enabled() -> bool:
    return _ENABLED


def _pcm(samples) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(_RATE)
        frames = b"".join(struct.pack("<h", max(-32767, min(32767, int(s)))) for s in samples)
        wav.writeframes(frames)
    return buf.getvalue()


def _tone(freq: float, ms: int, volume: float = 0.07, decay: bool = True):
    n = int(_RATE * ms / 1000)
    samples = []
    for i in range(n):
        t = i / _RATE
        env = (1.0 - i / n) if decay else 1.0
        samples.append(volume * env * 32767 * math.sin(2 * math.pi * freq * t))
    return samples


def _thud(ms: int = 90, volume: float = 0.09):
    n = int(_RATE * ms / 1000)
    samples = []
    for i in range(n):
        env = (1.0 - i / n) ** 2
        s = env * math.sin(2 * math.pi * 90 * i / _RATE)
        s += 0.35 * env * math.sin(2 * math.pi * 45 * i / _RATE)
        samples.append(volume * 32767 * s)
    return samples


def _wav_for(kind: str) -> bytes:
    if kind in _cache:
        return _cache[kind]
    if kind == "paper":
        samples = _tone(980, 45, volume=0.05) + _tone(720, 30, volume=0.03)
    elif kind == "door":
        samples = _thud(110, volume=0.08)
    elif kind == "end":
        samples = _tone(196, 180, volume=0.045) + _tone(147, 220, volume=0.04)
    else:
        samples = _tone(440, 40, volume=0.03)
    _cache[kind] = _pcm(samples)
    return _cache[kind]


def play(kind: str) -> None:
    """Играть клик в фоне. Никогда не бросает в игровой цикл."""
    if not _ENABLED:
        return
    try:
        data = _wav_for(kind)
    except Exception:
        return

    def _run():
        with _lock:
            try:
                import winsound
                winsound.PlaySound(data, winsound.SND_MEMORY)
            except Exception:
                return

    threading.Thread(target=_run, daemon=True).start()
