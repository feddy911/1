"""Петля карты из data/music. Клики остаются в sound.py.

m4a с acemusic.ai режется в ogg: хвост тишины срезаем, край кроссфейдим.
Крутит pygame-ce Sound (не mixer.music — у стрима пауза на стыке).
Диалог приглушает петлю. M — mute. Нет файла — тишина.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Dict, Optional

import numpy as np

from engine.constants import BRED_MAP_ID

ROOT = Path(__file__).resolve().parents[1]
MUSIC_DIR = ROOT / "data" / "music"

MAP_TRACKS: Dict[str, str] = {
    "hospital_floor_1": "clinic_hall",
    "hospital_floor_2": "clinic_hall",
    "hospital_basement": "basement",
    "street_outside": "street_canal",
    "street_traktir": "traktir",
    BRED_MAP_ID: "bred",
}

VOLUME_BED = 0.32
VOLUME_DUCK = 0.08
CROSSFADE_SEC = 0.45
# Сырой ACE-Step всегда 32 с. После среза хвоста петля короче.
RAW_CLIP_SEC = 31.0

_ENABLED = True
_MUTED = False
_DUCKED = False
_current_stem: Optional[str] = None
_mixer_ready = False
_channel = None
_sound = None

_PLAYABLE = (".ogg", ".wav", ".mp3")
_SOURCE = (".m4a", ".aac")


def set_enabled(value: bool) -> None:
    global _ENABLED
    _ENABLED = bool(value)
    if not _ENABLED:
        stop()


def is_enabled() -> bool:
    return _ENABLED


def is_muted() -> bool:
    return _MUTED


def toggle_mute() -> bool:
    global _MUTED
    _MUTED = not _MUTED
    _apply_volume()
    if _MUTED:
        _pause()
    elif _current_stem:
        _unpause()
    return _MUTED


def set_ducked(value: bool) -> None:
    global _DUCKED
    wanted = bool(value)
    if wanted == _DUCKED:
        return
    _DUCKED = wanted
    _apply_volume()


def stop() -> None:
    global _current_stem, _channel, _sound
    _current_stem = None
    if _channel is not None:
        try:
            _channel.stop()
        except Exception:
            pass
    _channel = None
    _sound = None


def set_for_map(map_id: Optional[str]) -> None:
    """Сменить петлю под карту. Тот же stem — не перезапускать."""
    global _current_stem, _channel, _sound
    if not _ENABLED:
        return
    stem = MAP_TRACKS.get(map_id or "")
    if stem == _current_stem:
        _apply_volume()
        if _MUTED:
            _pause()
        return
    if not stem:
        stop()
        return
    path = ensure_playable(stem)
    if path is None:
        stop()
        return
    mixer = _mixer()
    if mixer is None:
        return
    stop()
    try:
        sound = mixer.Sound(str(path))
        channel = sound.play(loops=-1)
    except Exception:
        stop()
        return
    if channel is None:
        return
    _sound = sound
    _channel = channel
    _current_stem = stem
    _apply_volume()
    if _MUTED:
        _pause()


def resolve_source(stem: str) -> Optional[Path]:
    """Файл пользователя: ogg/wav/mp3 или сырой m4a."""
    for ext in _SOURCE + _PLAYABLE:
        path = MUSIC_DIR / f"{stem}{ext}"
        if path.is_file():
            return path
    return None


def ensure_playable(stem: str) -> Optional[Path]:
    """ogg без хвоста тишины. Сырой m4a перегоняем; старый 32с ogg пересобираем."""
    dest = MUSIC_DIR / f"{stem}.ogg"
    source = None
    for ext in _SOURCE:
        candidate = MUSIC_DIR / f"{stem}{ext}"
        if candidate.is_file():
            source = candidate
            break
    if source is None:
        for ext in _PLAYABLE:
            candidate = MUSIC_DIR / f"{stem}{ext}"
            if candidate.is_file() and candidate != dest:
                source = candidate
                break
        if source is None and dest.is_file() and _needs_loop_rebuild(dest):
            source = dest
        elif source is None and dest.is_file():
            return dest
    if source is None:
        return None
    if dest.is_file() and dest != source and not _needs_loop_rebuild(dest):
        return dest
    if _transcode_loop(source, dest):
        return dest
    return dest if dest.is_file() else None


def _needs_loop_rebuild(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 20000:
        return True
    duration = _media_duration(path)
    return duration is None or duration >= RAW_CLIP_SEC


def _ffmpeg_exe() -> Optional[str]:
    try:
        from imageio_ffmpeg import get_ffmpeg_exe

        return get_ffmpeg_exe()
    except Exception:
        return None


def _ffmpeg_banner(path: Path) -> str:
    exe = _ffmpeg_exe()
    if not exe:
        return ""
    try:
        result = subprocess.run(
            [exe, "-i", str(path)],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except Exception:
        return ""
    raw = result.stderr or b""
    return raw.decode("utf-8", "replace")


def _media_duration(path: Path) -> Optional[float]:
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", _ffmpeg_banner(path))
    if not match:
        return None
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))


def _decode_pcm(source: Path) -> Optional[np.ndarray]:
    exe = _ffmpeg_exe()
    if not exe:
        return None
    try:
        result = subprocess.run(
            [
                exe,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-f",
                "s16le",
                "-ac",
                "2",
                "-ar",
                "44100",
                "pipe:1",
            ],
            capture_output=True,
            timeout=60,
            check=False,
        )
    except Exception:
        return None
    if not result.stdout or len(result.stdout) < 44100 * 4:
        return None
    pcm = np.frombuffer(result.stdout, dtype=np.int16)
    if pcm.size < 2 or pcm.size % 2:
        return None
    return pcm.reshape(-1, 2).astype(np.float32)


def _trim_trailing_silence(frames: np.ndarray, rate: int = 44100) -> np.ndarray:
    """Срезать затухание ACE-Step в конце. Начало не трогаем."""
    peak = 32768.0 * (10 ** (-38.0 / 20.0))
    amp = np.max(np.abs(frames), axis=1)
    loud = np.flatnonzero(amp > peak)
    if loud.size == 0:
        return frames
    end = int(loud[-1]) + 1
    if end < rate:
        return frames
    return frames[:end]


def _crossfade_loop(frames: np.ndarray, rate: int = 44100) -> np.ndarray:
    n = int(rate * CROSSFADE_SEC)
    if n < 64 or frames.shape[0] < n * 2 + rate:
        return frames
    fade = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, None]
    head = frames[:n]
    body = frames[n:].copy()
    body[-n:] = body[-n:] * (1.0 - fade) + head * fade
    return body


def _transcode_loop(source: Path, dest: Path) -> bool:
    exe = _ffmpeg_exe()
    if not exe:
        return False
    frames = _decode_pcm(source)
    if frames is None:
        return False
    frames = _crossfade_loop(_trim_trailing_silence(frames))
    pcm = np.clip(np.rint(frames), -32767, 32767).astype(np.int16).tobytes()
    tmp = dest.with_name(dest.stem + ".tmp.ogg")
    try:
        result = subprocess.run(
            [
                exe,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "s16le",
                "-ac",
                "2",
                "-ar",
                "44100",
                "-i",
                "pipe:0",
                "-c:a",
                "libvorbis",
                "-q:a",
                "4",
                str(tmp),
            ],
            input=pcm,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except Exception:
        if tmp.is_file():
            tmp.unlink()
        return False
    if result.returncode != 0 or not tmp.is_file() or tmp.stat().st_size < 20000:
        if tmp.is_file():
            tmp.unlink()
        return False
    tmp.replace(dest)
    return dest.is_file() and dest.stat().st_size >= 20000


def _mixer():
    global _mixer_ready
    if not _ENABLED:
        return None
    if _mixer_ready:
        try:
            import pygame

            return pygame.mixer
        except Exception:
            return None
    try:
        import pygame

        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        pygame.mixer.set_num_channels(8)
        _mixer_ready = True
        return pygame.mixer
    except Exception:
        return None


def _apply_volume() -> None:
    if _channel is None:
        return
    if _MUTED or not _ENABLED:
        volume = 0.0
    elif _DUCKED:
        volume = VOLUME_DUCK
    else:
        volume = VOLUME_BED
    try:
        _channel.set_volume(volume)
        if _sound is not None:
            _sound.set_volume(volume)
    except Exception:
        return


def _pause() -> None:
    if _channel is None:
        return
    try:
        _channel.pause()
    except Exception:
        return


def _unpause() -> None:
    if _channel is None:
        return
    try:
        _channel.unpause()
    except Exception:
        return
