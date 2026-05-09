"""
telegram_client.py — подключение к Telegram, сбор постов.

Медиа-анализ выполняется в main.py ПОСЛЕ выборки — только для выбранных постов.
Скачивание медиа защищено retry-механикой (3-5 попыток, пауза 3-7 сек).
"""

import asyncio
import logging
import os
import random
from datetime import datetime
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
    FloodWaitError,
    AuthKeyError,
    RPCError,
)

from utils import make_aware, make_post_url, parse_reactions, extract_username
from classifier import classify_post, _detect_media_flags

logger = logging.getLogger("tg_analyzer")

# Параметры retry для скачивания медиа
DOWNLOAD_RETRIES = 2
DOWNLOAD_RETRY_MIN = 2   # секунды
DOWNLOAD_RETRY_MAX = 4   # секунды


async def _download_with_retry(
    client,
    message,
    dest_path: str,
    retries: int = DOWNLOAD_RETRIES,
) -> bool:
    """
    Скачивает медиафайл с retry-механикой.

    Returns:
        True если файл успешно скачан и валиден, False иначе.
    """
    path = Path(dest_path)

    for attempt in range(1, retries + 1):
        # Удаляем частичный файл перед попыткой
        if path.exists():
            path.unlink(missing_ok=True)

        try:
            await client.download_media(message, str(path))

            # Проверяем что файл существует и не пустой
            if not path.exists() or path.stat().st_size == 0:
                raise ValueError("Файл пустой или не создан")

            # Для фото проверяем валидность через PIL
            if str(path).lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                try:
                    from PIL import Image
                    with Image.open(str(path)) as img:
                        img.verify()
                    # После verify нужно заново открыть для использования
                except Exception as e:
                    raise ValueError(f"Повреждённый файл изображения: {e}")

            return True

        except Exception as e:
            err_msg = str(e)
            # Удаляем частичный файл
            if path.exists():
                path.unlink(missing_ok=True)

            if attempt < retries:
                wait = random.uniform(DOWNLOAD_RETRY_MIN, DOWNLOAD_RETRY_MAX)
                logger.debug(
                    f"Попытка {attempt}/{retries} не удалась ({err_msg[:60]}), "
                    f"повтор через {wait:.1f} сек..."
                )
                await asyncio.sleep(wait)
            else:
                logger.warning(
                    f"Медиа скачать не удалось после {retries} попыток — пропущено. "
                    f"Пост: {getattr(message, 'id', '?')}"
                )

    return False


class TelegramAnalyzerClient:
    def __init__(self, session_name: str, api_id: int, api_hash: str, phone: str):
        self.session_name = session_name
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.client = TelegramClient(session_name, api_id, api_hash)

    async def start(self):
        await self.client.start(phone=self.phone)
        logger.info("Авторизация в Telegram выполнена успешно")

    async def stop(self):
        await self.client.disconnect()
        logger.info("Соединение с Telegram закрыто")

    async def fetch_posts(
        self,
        channel_url: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict]:
        """
        Получает все посты канала за период БЕЗ медиа-анализа.
        Оригинальный объект Message сохраняется в поле _message.
        """
        try:
            username = extract_username(channel_url)
        except ValueError as e:
            logger.error(f"Неверная ссылка: {channel_url} — {e}")
            return []

        start_aware = make_aware(start_date)
        end_inclusive = make_aware(end_date).replace(
            hour=23, minute=59, second=59, microsecond=999999
        )

        posts = []

        try:
            entity = await self.client.get_entity(username)
            logger.info(f"[{username}] Получаем сообщения за период "
                        f"{start_aware.date()} — {end_inclusive.date()}")

            grouped_messages: dict[int, list] = {}
            standalone_messages = []

            async for message in self.client.iter_messages(
                entity,
                offset_date=end_inclusive,
                reverse=False,
            ):
                msg_date = make_aware(message.date)
                if msg_date < start_aware:
                    break
                if msg_date > end_inclusive:
                    continue
                if message.action is not None:
                    continue

                if message.grouped_id is not None:
                    grouped_messages.setdefault(message.grouped_id, []).append(message)
                else:
                    standalone_messages.append(message)

            for msg in standalone_messages:
                posts.append(self._normalize_message(msg, username))

            for group_msgs in grouped_messages.values():
                group_msgs.sort(key=lambda m: m.id)
                accumulated = _accumulate_group_flags(group_msgs)
                main_msg = _pick_main_message(group_msgs)
                posts.append(self._normalize_message(
                    main_msg, username,
                    accumulated_flags=accumulated,
                    media_count=accumulated["media_count"],
                ))

            logger.info(f"[{username}] Получено {len(posts)} постов")

        except ChannelPrivateError:
            logger.error(f"[{username}] Канал приватный")
        except (UsernameInvalidError, UsernameNotOccupiedError):
            logger.error(f"[{username}] Канал не найден")
        except FloodWaitError as e:
            logger.error(f"[{username}] FloodWait: подождите {e.seconds} сек.")
        except AuthKeyError:
            logger.error("Ошибка авторизации")
        except RPCError as e:
            logger.error(f"[{username}] Telegram API ошибка: {e}")
        except Exception as e:
            logger.error(f"[{username}] Неожиданная ошибка: {e}", exc_info=True)

        return posts

    def _normalize_message(
        self,
        message,
        channel_username: str,
        accumulated_flags: dict | None = None,
        media_count: int | None = None,
    ) -> dict:
        msg_date = make_aware(message.date)
        text = (message.text or message.message or "").strip()
        reactions_str = parse_reactions(getattr(message, "reactions", None))

        replies = None
        if message.replies:
            replies = message.replies.replies

        fmt = classify_post(message, accumulated_flags)
        actual_media_count = media_count if media_count is not None else fmt.media_count

        return {
            "channel_url": f"https://t.me/{channel_username}",
            "channel_username": channel_username,
            "post_id": message.id,
            "post_url": make_post_url(channel_username, message.id),
            "post_date": msg_date,
            "month": msg_date.strftime("%Y-%m"),
            "text": text,
            "has_text": fmt.has_text,
            "has_photo": fmt.has_photo,
            "has_video": fmt.has_video,
            "has_video_note": fmt.has_video_note,
            "has_voice": fmt.has_voice,
            "has_audio": fmt.has_audio,
            "has_poll": fmt.has_poll,
            "has_gif": fmt.has_gif,
            "has_sticker": fmt.has_sticker,
            "has_file": fmt.has_file,
            "media_count": actual_media_count,
            "format_code": fmt.format_code,
            "format_name": fmt.format_name,
            "classification_note": fmt.classification_note,
            "image_ocr_text": "",
            "image_description": "",
            "video_frame_ocr_text": "",
            "video_description": "",
            "audio_transcript": "",
            "voice_transcript": "",
            "analysis_level": "basic",
            "views": getattr(message, "views", None),
            "forwards": getattr(message, "forwards", None),
            "replies": replies,
            "reactions": reactions_str,
            "random_seed": None,
            "sample_order": None,
            "_message": message,
        }

    async def analyze_media_for_post(
        self,
        post: dict,
        media_analyzer,
    ) -> dict:
        """
        Выполняет медиа-анализ для одного выбранного поста.
        Использует retry-механику при скачивании.
        Ошибка одного поста не останавливает обработку остальных.
        """
        message = post.get("_message")
        if message is None or media_analyzer is None:
            return post

        try:
            # Передаём функцию скачивания с retry в media_analyzer
            media_result = await media_analyzer.analyze(
                message=message,
                telegram_client=self.client,
                has_photo=post.get("has_photo", False),
                has_video=post.get("has_video", False),
                has_video_note=post.get("has_video_note", False),
                has_voice=post.get("has_voice", False),
                download_func=_download_with_retry,
            )
            post["image_ocr_text"]       = media_result.image_ocr_text
            post["image_description"]    = media_result.image_description
            post["video_frame_ocr_text"] = media_result.video_frame_ocr_text
            post["video_description"]    = media_result.video_description
            post["audio_transcript"]     = media_result.audio_transcript
            post["voice_transcript"]     = media_result.voice_transcript
            post["analysis_level"]       = media_result.analysis_level

            if media_result.errors:
                post["classification_note"] = (
                    post.get("classification_note", "") +
                    " | Ошибки медиа: " + "; ".join(media_result.errors[:2])
                ).strip(" |")

        except Exception as e:
            logger.warning(
                f"Медиа-анализ поста {post.get('post_id')} пропущен: {e}"
            )

        return post


def _accumulate_group_flags(messages: list) -> dict:
    result = {
        "has_photo": False, "has_video": False, "has_video_note": False,
        "has_voice": False, "has_audio": False, "has_poll": False,
        "has_gif": False, "has_sticker": False, "has_file": False,
        "media_count": 0,
    }
    for msg in messages:
        flags = _detect_media_flags(msg)
        for key in result:
            if key == "media_count":
                result["media_count"] += flags.get("media_count", 0)
            else:
                result[key] = result[key] or flags.get(key, False)
    return result


def _pick_main_message(messages: list):
    for msg in messages:
        if msg.text or msg.message:
            return msg
    return messages[0]
