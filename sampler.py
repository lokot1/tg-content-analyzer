"""
sampler.py — группировка постов по месяцам и случайная выборка.
"""

import random
import logging
from collections import defaultdict
from datetime import datetime

from utils import month_key

logger = logging.getLogger("tg_analyzer")


def group_by_month(posts: list[dict]) -> dict[str, list[dict]]:
    """
    Группирует список постов по ключу YYYY-MM.
    Каждый пост должен содержать поле 'post_date' типа datetime.
    """
    grouped = defaultdict(list)
    for post in posts:
        dt = post["post_date"]
        key = month_key(dt)
        grouped[key].append(post)
    return dict(grouped)


def sample_posts(
    posts: list[dict],
    channel_username: str,
    posts_per_month: int,
    seed: int,
) -> list[dict]:
    """
    Для каждого месяца случайно выбирает posts_per_month постов.

    Args:
        posts: все посты канала за период.
        channel_username: имя канала (для логов).
        posts_per_month: количество постов, которое нужно выбрать из каждого месяца.
        seed: seed для воспроизводимой выборки.

    Returns:
        Список выбранных постов с добавленными полями
        'random_seed' и 'sample_order'.
    """
    grouped = group_by_month(posts)
    result = []

    for month in sorted(grouped.keys()):
        month_posts = grouped[month]
        available = len(month_posts)

        if available == 0:
            logger.warning(
                f"[{channel_username}] {month}: нет постов — пропускаем месяц"
            )
            continue

        if available < posts_per_month:
            logger.warning(
                f"[{channel_username}] {month}: доступно только {available} "
                f"постов (запрошено {posts_per_month}) — берём все"
            )

        # Воспроизводимая выборка: seed зависит от канала и месяца
        month_seed = _derive_seed(seed, channel_username, month)
        rng = random.Random(month_seed)

        n = min(posts_per_month, available)
        chosen = rng.sample(month_posts, n)

        # Сортируем выбранные по дате для стабильного порядка
        chosen.sort(key=lambda p: p["post_date"])

        for order, post in enumerate(chosen, start=1):
            post = dict(post)  # копируем, чтобы не мутировать оригинал
            post["random_seed"] = month_seed
            post["sample_order"] = order
            result.append(post)

    return result


def _derive_seed(base_seed: int, channel_username: str, month: str) -> int:
    """
    Создаёт детерминированный seed для конкретного канала и месяца,
    чтобы выборка в каждом (канал, месяц) была независимой,
    но воспроизводимой при одном и том же base_seed.
    """
    combined = f"{base_seed}:{channel_username}:{month}"
    return hash(combined) & 0xFFFFFFFF
