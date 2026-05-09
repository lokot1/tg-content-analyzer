"""
utils.py — вспомогательные функции: нормализация ссылок, логирование, работа с датами.
"""

import logging
import re
from datetime import datetime, timezone
from pathlib import Path


def setup_logger(log_path: str = "logs.txt") -> logging.Logger:
    logger = logging.getLogger("tg_analyzer")
    logger.setLevel(logging.DEBUG)

    # Файловый обработчик
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)

    # Консольный обработчик
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    if not logger.handlers:
        logger.addHandler(fh)
        logger.addHandler(ch)

    return logger


def normalize_channel_url(raw: str) -> str:
    """
    Приводит ссылку или username к формату https://t.me/username.
    Поддерживает:
      - https://t.me/channel
      - http://t.me/channel
      - t.me/channel
      - @channel
      - channel
    """
    raw = raw.strip()
    if not raw:
        raise ValueError("Пустая строка канала")

    # Уже полная ссылка
    if raw.startswith("https://t.me/") or raw.startswith("http://t.me/"):
        return raw.rstrip("/")

    # t.me/...
    if raw.startswith("t.me/"):
        return "https://" + raw.rstrip("/")

    # @username
    if raw.startswith("@"):
        return f"https://t.me/{raw[1:].rstrip('/')}"

    # Просто username без @
    if re.match(r'^[A-Za-z0-9_]+$', raw):
        return f"https://t.me/{raw}"

    raise ValueError(f"Не удалось распознать ссылку на канал: {raw!r}")


def extract_username(channel_url: str) -> str:
    """Извлекает username из URL вида https://t.me/username."""
    parts = channel_url.rstrip("/").split("/")
    username = parts[-1]
    if username.startswith("+"):
        # Приватная инвайт-ссылка — не поддерживается
        raise ValueError(f"Приватные инвайт-ссылки не поддерживаются: {channel_url}")
    return username


def make_post_url(channel_username: str, post_id: int) -> str:
    return f"https://t.me/{channel_username}/{post_id}"


def load_channels_from_file(path: str) -> list[str]:
    """Читает файл с каналами (по одной ссылке на строку)."""
    file = Path(path)
    if not file.exists():
        raise FileNotFoundError(f"Файл каналов не найден: {path}")

    channels = []
    with open(file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                channels.append(line)
    return channels


def make_aware(dt: datetime) -> datetime:
    """Делает datetime timezone-aware (UTC), если он naive."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def month_key(dt: datetime) -> str:
    """Возвращает строку вида YYYY-MM для группировки по месяцам."""
    return dt.strftime("%Y-%m")


def parse_reactions(reactions) -> str:
    """
    Парсит объект реакций Telethon в читаемую строку.
    Возвращает, например: "👍:10, ❤️:5"
    """
    if reactions is None:
        return ""
    try:
        parts = []
        for result in reactions.results:
            emoji = getattr(result.reaction, "emoticon", "?")
            count = result.count
            parts.append(f"{emoji}:{count}")
        return ", ".join(parts)
    except Exception:
        return ""
