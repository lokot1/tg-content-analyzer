"""
config.py — загрузка переменных окружения и настройки приложения.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def get_api_id() -> int:
    val = os.getenv("API_ID")
    if not val:
        raise EnvironmentError("API_ID не задан в .env файле")
    return int(val)


def get_api_hash() -> str:
    val = os.getenv("API_HASH")
    if not val:
        raise EnvironmentError("API_HASH не задан в .env файле")
    return val


def get_phone() -> str:
    val = os.getenv("PHONE")
    if not val:
        raise EnvironmentError("PHONE не задан в .env файле")
    return val


def get_session_name() -> str:
    return os.getenv("SESSION_NAME", "tg_analyzer_session")
