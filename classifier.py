"""
classifier.py — определение ФОРМАТА поста (коды 1–9).

Кодификатор форматов:
  1 — Текстовый пост
  2 — Текстовый пост с фото
  3 — Текстовый пост с видео
  4 — Фото без текста
  5 — Видео без текста
  6 — Кружок (video note)
  7 — Голосовое сообщение
  8 — Смешанный формат (несколько разных медиа-типов)
  9 — Иной формат (опрос, GIF, стикер, файл, документ)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from telethon.tl.types import (
    MessageMediaPhoto,
    MessageMediaDocument,
    MessageMediaWebPage,
    MessageMediaPoll,
    DocumentAttributeVideo,
    DocumentAttributeAudio,
    DocumentAttributeSticker,
    DocumentAttributeAnimated,
)

FORMAT_NAMES = {
    1: "Текстовый пост",
    2: "Текстовый пост с фото",
    3: "Текстовый пост с видео",
    4: "Фото без текста",
    5: "Видео без текста",
    6: "Кружок",
    7: "Голосовое сообщение",
    8: "Смешанный формат",
    9: "Иной формат",
}


@dataclass
class FormatResult:
    format_code: Optional[int]
    format_name: str
    classification_note: str
    has_text: bool
    has_photo: bool
    has_video: bool
    has_video_note: bool
    has_voice: bool
    has_audio: bool
    has_poll: bool
    has_gif: bool
    has_sticker: bool
    has_file: bool
    media_count: int


def _detect_media_flags(message) -> dict:
    """
    Анализирует медиа-вложения одного сообщения Telethon.
    Возвращает словарь флагов.
    """
    flags = {
        "has_photo": False,
        "has_video": False,
        "has_video_note": False,
        "has_voice": False,
        "has_audio": False,
        "has_poll": False,
        "has_gif": False,
        "has_sticker": False,
        "has_file": False,
        "media_count": 0,
    }

    media = message.media

    if media is None:
        return flags

    # Веб-превью — не считаем медиа
    if isinstance(media, MessageMediaWebPage):
        return flags

    # Опрос
    if isinstance(media, MessageMediaPoll):
        flags["has_poll"] = True
        flags["media_count"] = 1
        return flags

    # Фото
    if isinstance(media, MessageMediaPhoto):
        flags["has_photo"] = True
        flags["media_count"] = 1
        return flags

    # Документ — разбираем по атрибутам
    if isinstance(media, MessageMediaDocument):
        doc = media.document
        if doc is None:
            return flags

        attrs = doc.attributes or []
        identified = False

        for attr in attrs:
            # Стикер
            if isinstance(attr, DocumentAttributeSticker):
                flags["has_sticker"] = True
                flags["media_count"] += 1
                identified = True

            # GIF (анимированный документ)
            elif isinstance(attr, DocumentAttributeAnimated):
                flags["has_gif"] = True
                flags["media_count"] += 1
                identified = True

            # Видео или кружок
            elif isinstance(attr, DocumentAttributeVideo):
                if getattr(attr, "round_message", False):
                    flags["has_video_note"] = True
                else:
                    flags["has_video"] = True
                flags["media_count"] += 1
                identified = True

            # Аудио или голосовое
            elif isinstance(attr, DocumentAttributeAudio):
                if getattr(attr, "voice", False):
                    flags["has_voice"] = True
                else:
                    flags["has_audio"] = True
                flags["media_count"] += 1
                identified = True

        # Не опознанный документ/файл
        if not identified:
            flags["has_file"] = True
            flags["media_count"] += 1

        return flags

    # Любое другое медиа — файл
    flags["has_file"] = True
    flags["media_count"] = 1
    return flags


def classify_post(message, accumulated_flags: dict | None = None) -> FormatResult:
    """
    Классифицирует формат одного сообщения Telethon.

    Args:
        message: объект Telethon Message.
        accumulated_flags: объединённые флаги группы медиа (для альбомов).

    Returns:
        FormatResult с кодом формата и метаданными.
    """
    text = (message.text or message.message or "").strip()
    has_text = len(text) > 0

    flags = accumulated_flags if accumulated_flags is not None else _detect_media_flags(message)

    has_photo      = flags.get("has_photo", False)
    has_video      = flags.get("has_video", False)
    has_video_note = flags.get("has_video_note", False)
    has_voice      = flags.get("has_voice", False)
    has_audio      = flags.get("has_audio", False)
    has_poll       = flags.get("has_poll", False)
    has_gif        = flags.get("has_gif", False)
    has_sticker    = flags.get("has_sticker", False)
    has_file       = flags.get("has_file", False)
    media_count    = flags.get("media_count", 0)

    note = ""

    # --- Иной формат (код 9): опрос, GIF, стикер, файл ---
    if has_poll or has_gif or has_sticker or has_file:
        if has_poll:
            note = "опрос"
        elif has_gif:
            note = "GIF"
        elif has_sticker:
            note = "стикер"
        else:
            note = "файл/документ"
        return _result(9, has_text, has_photo, has_video, has_video_note,
                       has_voice, has_audio, has_poll, has_gif, has_sticker,
                       has_file, media_count, note)

    # --- Кружок (код 6) ---
    if has_video_note:
        return _result(6, has_text, has_photo, has_video, has_video_note,
                       has_voice, has_audio, has_poll, has_gif, has_sticker,
                       has_file, media_count, note)

    # --- Голосовое (код 7) ---
    if has_voice:
        return _result(7, has_text, has_photo, has_video, has_video_note,
                       has_voice, has_audio, has_poll, has_gif, has_sticker,
                       has_file, media_count, note)

    # --- Смешанный (код 8): фото + видео ---
    if has_photo and has_video:
        note = "смешанный медиаформат: фото и видео"
        return _result(8, has_text, has_photo, has_video, has_video_note,
                       has_voice, has_audio, has_poll, has_gif, has_sticker,
                       has_file, media_count, note)

    # --- С текстом ---
    if has_text:
        if has_video:
            return _result(3, has_text, has_photo, has_video, has_video_note,
                           has_voice, has_audio, has_poll, has_gif, has_sticker,
                           has_file, media_count, note)
        if has_photo:
            return _result(2, has_text, has_photo, has_video, has_video_note,
                           has_voice, has_audio, has_poll, has_gif, has_sticker,
                           has_file, media_count, note)
        # Только текст (в т.ч. с веб-превью)
        return _result(1, has_text, has_photo, has_video, has_video_note,
                       has_voice, has_audio, has_poll, has_gif, has_sticker,
                       has_file, media_count, note)

    # --- Без текста ---
    else:
        if has_video:
            return _result(5, has_text, has_photo, has_video, has_video_note,
                           has_voice, has_audio, has_poll, has_gif, has_sticker,
                           has_file, media_count, note)
        if has_photo:
            return _result(4, has_text, has_photo, has_video, has_video_note,
                           has_voice, has_audio, has_poll, has_gif, has_sticker,
                           has_file, media_count, note)

        # Ничего не опознано
        note = "нет текста и не удалось определить медиаформат"
        return FormatResult(
            format_code=9,
            format_name=FORMAT_NAMES[9],
            classification_note=note,
            has_text=has_text,
            has_photo=has_photo,
            has_video=has_video,
            has_video_note=has_video_note,
            has_voice=has_voice,
            has_audio=has_audio,
            has_poll=has_poll,
            has_gif=has_gif,
            has_sticker=has_sticker,
            has_file=has_file,
            media_count=media_count,
        )


def _result(code, has_text, has_photo, has_video, has_video_note,
            has_voice, has_audio, has_poll, has_gif, has_sticker,
            has_file, media_count, note) -> FormatResult:
    return FormatResult(
        format_code=code,
        format_name=FORMAT_NAMES[code],
        classification_note=note,
        has_text=has_text,
        has_photo=has_photo,
        has_video=has_video,
        has_video_note=has_video_note,
        has_voice=has_voice,
        has_audio=has_audio,
        has_poll=has_poll,
        has_gif=has_gif,
        has_sticker=has_sticker,
        has_file=has_file,
        media_count=media_count,
    )
