"""Shared musical key normalization helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass


NOTE_OFFSETS = {
    "C": 0,
    "D": 2,
    "E": 4,
    "F": 5,
    "G": 7,
    "A": 9,
    "B": 11,
}
CANONICAL_NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
KEY_RE = re.compile(
    r"(?<![A-Za-z])([A-Ga-g])\s*([#♯＃b♭]?)(?:\s*(minor|min|major|maj|m))?(?![A-Za-z#♯＃b♭])",
    re.IGNORECASE,
)
TRAILING_TEMPO_RE = re.compile(r"(?:^|\s)([1-9]\d{1,2}(?:\.\d+)?)\s*(?:bpm)?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class NormalizedKeyFields:
    key_of: str
    mode: str
    tempo: str


def compact(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_mode(value: object) -> str:
    lowered = compact(value).casefold()
    if lowered in {"m", "min", "minor"}:
        return "minor"
    if lowered in {"maj", "major"}:
        return "major"
    return ""


def normalize_note(note: str, accidental: str = "") -> str:
    base = note.upper()
    if base not in NOTE_OFFSETS:
        return ""
    offset = NOTE_OFFSETS[base]
    accidental = accidental.replace("♯", "#").replace("＃", "#").replace("♭", "b")
    if accidental == "#":
        offset += 1
    elif accidental.casefold() == "b":
        offset -= 1
    return CANONICAL_NOTES[offset % 12]


def embedded_tempo(value: object) -> str:
    raw = compact(value)
    match = TRAILING_TEMPO_RE.search(raw)
    if not match:
        return ""
    tempo = match.group(1)
    try:
        value_float = float(tempo)
    except ValueError:
        return ""
    if not 20 <= value_float <= 999:
        return ""
    return tempo


def normalize_key_mode(key_of: object, mode: object = "") -> tuple[str, str]:
    raw = compact(key_of)
    mode_hint = normalize_mode(mode)
    if not raw:
        return "", mode_hint

    raw_mode = normalize_mode(raw)
    if raw_mode:
        return "", raw_mode

    match = KEY_RE.search(raw)
    if not match:
        return "", mode_hint

    note, accidental, inline_mode = match.groups()
    normalized_key = normalize_note(note, accidental)
    normalized_mode = normalize_mode(inline_mode) or mode_hint or "major"
    return normalized_key, normalized_mode


def normalize_key_fields(key_of: object, mode: object = "", tempo: object = "") -> NormalizedKeyFields:
    normalized_key, normalized_mode = normalize_key_mode(key_of, mode)
    normalized_tempo = compact(tempo)
    if not normalized_tempo:
        normalized_tempo = embedded_tempo(key_of)
    return NormalizedKeyFields(normalized_key, normalized_mode, normalized_tempo)
