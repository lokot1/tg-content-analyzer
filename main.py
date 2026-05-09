"""
main.py — точка входа.

Ключевые исправления:
1. Медиа-анализ (OCR/STT/vision) выполняется ТОЛЬКО для выбранных постов,
   а не для всех постов канала. Ускорение в 10-20 раз.
2. Имя файла результата автоматически включает дату и время запуска.
"""

import argparse
import asyncio
import csv
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import config
from utils import setup_logger, normalize_channel_url
from telegram_client import TelegramAnalyzerClient
from sampler import sample_posts
from type_classifier import classify_type
from media_analyzer import MediaAnalyzer
from report_builder import build_report, build_manual_review, recalculate_with_manual

SEGMENT_NAMES = {"fashion": "Мода", "beauty": "Красота"}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Telegram Post Analyzer v2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--channels",        metavar="FILE")
    parser.add_argument("--start-date",      metavar="YYYY-MM-DD")
    parser.add_argument("--end-date",        metavar="YYYY-MM-DD")
    parser.add_argument("--posts-per-month", type=int, default=2)
    parser.add_argument("--seed",            type=int, default=42)
    parser.add_argument("--output",          default="result.xlsx")
    parser.add_argument("--log",             default="logs.txt")

    parser.add_argument("--type-classification-mode",
                        choices=["rules", "llm", "hybrid"],
                        default="hybrid", dest="type_mode")
    parser.add_argument("--manual-review-threshold",
                        type=float, default=0.65, dest="review_threshold")

    parser.add_argument("--llm-provider", default="",
                        choices=["anthropic", "openai", "none", ""],
                        dest="llm_provider")
    parser.add_argument("--llm-model", default="", dest="llm_model")

    parser.add_argument("--enable-ocr",
                        type=lambda x: x.lower() == "true",
                        default=False, dest="enable_ocr")
    parser.add_argument("--enable-media-download",
                        type=lambda x: x.lower() == "true",
                        default=False, dest="enable_media_download")
    parser.add_argument("--enable-audio-transcription",
                        type=lambda x: x.lower() == "true",
                        default=False, dest="enable_audio_transcription")
    parser.add_argument("--enable-vision",
                        type=lambda x: x.lower() == "true",
                        default=False, dest="enable_vision")
    parser.add_argument("--keep-media",
                        type=lambda x: x.lower() == "true",
                        default=False, dest="keep_media")
    parser.add_argument("--media-dir", default="media_tmp", dest="media_dir")

    parser.add_argument("--local-vision-provider",
                        default="ollama",
                        choices=["ollama", "anthropic", "openai"],
                        dest="local_vision_provider")
    parser.add_argument("--local-vision-model",
                        default="qwen2.5vl:7b",
                        dest="local_vision_model")
    parser.add_argument("--video-frame-interval",
                        type=int, default=10, dest="video_frame_interval")
    parser.add_argument("--max-video-frames",
                        type=int, default=5, dest="max_video_frames")
    parser.add_argument("--whisper-model", default="", dest="whisper_model")

    parser.add_argument("--input-classified",      default="", dest="input_classified")
    parser.add_argument("--manual-review",         default="", dest="manual_review")
    parser.add_argument("--recalculate-analytics", action="store_true", dest="recalculate")

    return parser.parse_args()


def parse_date(date_str: str, arg_name: str) -> datetime:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        print(f"Ошибка: неверный формат даты {arg_name}: {date_str!r}. Ожидается YYYY-MM-DD")
        sys.exit(1)


def load_channels_csv(path: str) -> list[dict]:
    file = Path(path)
    if not file.exists():
        raise FileNotFoundError(f"Файл каналов не найден: {path}")
    channels = []
    with open(file, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            url     = row.get("channel_url", "").strip()
            segment = row.get("segment", "").strip().lower()
            if url and not url.startswith("#"):
                try:
                    channels.append({"url": normalize_channel_url(url), "segment": segment})
                except ValueError as e:
                    logging.getLogger("tg_analyzer").warning(f"Пропуск: {url} — {e}")
    return channels


def _get_llm_api_key(provider: str) -> str:
    if provider == "anthropic":
        return os.getenv("ANTHROPIC_API_KEY") or os.getenv("LLM_API_KEY", "")
    if provider == "openai":
        return os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY", "")
    return ""


def _make_output_path(base_output: str, start_date: datetime, end_date: datetime) -> str:
    """
    Генерирует имя файла с датами периода и временем запуска.
    Например: result_2025-11_2026-04_run20260504_1900.xlsx
    """
    p = Path(base_output)
    stem = p.stem  # имя без расширения
    ext  = p.suffix or ".xlsx"

    start_str = start_date.strftime("%Y-%m")
    end_str   = end_date.strftime("%Y-%m")
    run_str   = datetime.now().strftime("%Y%m%d_%H%M")

    new_name = f"{stem}_{start_str}_{end_str}_run{run_str}{ext}"
    return str(p.parent / new_name)


async def run(args):
    logger = setup_logger(args.log)
    logger.info("=" * 60)
    logger.info("Telegram Post Analyzer v2")
    logger.info("=" * 60)

    # Режим пересчёта аналитики
    if args.recalculate and args.input_classified and args.manual_review:
        logger.info("Режим: пересчёт после ручной проверки")
        recalculate_with_manual(
            classified_path=args.input_classified,
            manual_review_path=args.manual_review,
            output_path=args.output,
        )
        print(f"\n✅ Пересчитанный отчёт: {args.output}")
        return

    if not args.channels or not args.start_date or not args.end_date:
        print("Ошибка: укажите --channels, --start-date и --end-date")
        sys.exit(1)

    start_date = parse_date(args.start_date, "--start-date")
    end_date   = parse_date(args.end_date,   "--end-date")

    if start_date > end_date:
        print("Ошибка: дата начала позже даты окончания")
        sys.exit(1)

    # Автоматическое имя файла с датами и временем запуска
    output_path = _make_output_path(args.output, start_date, end_date)
    logger.info(f"Файл результата: {output_path}")

    try:
        channels = load_channels_csv(args.channels)
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)

    if not channels:
        logger.error("Нет валидных каналов")
        sys.exit(1)

    # Vision и LLM настройки
    vision_provider = args.local_vision_provider
    vision_model    = args.local_vision_model
    vision_api_key  = _get_llm_api_key(vision_provider) if vision_provider in ("anthropic", "openai") else ""

    llm_provider = args.llm_provider or os.getenv("LLM_PROVIDER", "none")
    llm_model    = args.llm_model    or os.getenv("LLM_MODEL", "")

    # Если llm_provider не задан явно, но vision = ollama → используем ollama для hybrid тоже
    if (not args.llm_provider and llm_provider == "none"
            and args.enable_vision and args.local_vision_provider == "ollama"):
        llm_provider = "ollama"
        llm_model    = llm_model or args.local_vision_model
        logger.info(f"LLM провайдер автоматически: ollama/{llm_model}")

    llm_api_key  = _get_llm_api_key(llm_provider) if llm_provider not in ("none", "ollama", "") else ""

    whisper_model = args.whisper_model or os.getenv("WHISPER_MODEL", "small")

    logger.info(f"Период: {start_date.date()} — {end_date.date()}")
    logger.info(f"Каналов: {len(channels)}, постов в месяц: {args.posts_per_month}, seed: {args.seed}")
    logger.info(f"Режим типов: {args.type_mode}")
    logger.info(f"OCR: {args.enable_ocr}, STT: {args.enable_audio_transcription}, "
                f"Vision: {args.enable_vision} ({vision_provider}/{vision_model})")
    logger.info("Медиа-анализ выполняется ТОЛЬКО для выбранных постов ✓")

    # Медиа-анализатор
    media_analyzer = MediaAnalyzer(
        enable_ocr=args.enable_ocr,
        enable_audio_transcription=args.enable_audio_transcription,
        enable_vision=args.enable_vision,
        enable_media_download=args.enable_media_download,
        keep_media=args.keep_media,
        media_dir=args.media_dir,
        tesseract_cmd=os.getenv("TESSERACT_CMD", ""),
        whisper_model_name=whisper_model,
        vision_provider=vision_provider,
        vision_api_key=vision_api_key,
        vision_model=vision_model,
        video_frame_interval=args.video_frame_interval,
        max_video_frames=args.max_video_frames,
    )

    # Telegram клиент
    try:
        api_id   = config.get_api_id()
        api_hash = config.get_api_hash()
        phone    = config.get_phone()
        session  = config.get_session_name()
    except EnvironmentError as e:
        logger.error(str(e))
        sys.exit(1)

    client = TelegramAnalyzerClient(session, api_id, api_hash, phone)

    all_posts = []
    channel_monthly_counts = {}

    stats = {
        "total_collected": 0,
        "total_sampled": 0,
        "format_classified": 0,
        "type_classified": 0,
        "ocr_used": 0,
        "stt_used": 0,
        "vision_used": 0,
        "llm_used": 0,
        "manual_review": 0,
    }

    try:
        await client.start()

        for idx, ch in enumerate(channels, start=1):
            channel_url = ch["url"]
            segment     = ch["segment"]
            logger.info(f"[{idx}/{len(channels)}] {channel_url} [{segment}]")

            # ШАГ 1: Получаем все посты — БЕЗ медиа-анализа (быстро)
            posts = await client.fetch_posts(
                channel_url=channel_url,
                start_date=start_date,
                end_date=end_date,
            )

            if not posts:
                logger.warning(f"Нет постов: {channel_url}")
                continue

            stats["total_collected"] += len(posts)
            username = posts[0]["channel_username"]

            # Подсчёт реальной активности
            from collections import defaultdict as dd
            month_cnt = dd(int)
            for p in posts:
                month_cnt[p["month"]] += 1
            channel_monthly_counts[username] = dict(month_cnt)

            # ШАГ 2: Выборка — только N постов из каждого месяца
            sampled = sample_posts(posts, username, args.posts_per_month, args.seed)
            stats["total_sampled"] += len(sampled)

            logger.info(f"  Собрано: {len(posts)}, выбрано: {len(sampled)} — "
                        f"медиа-анализ только для {len(sampled)} постов")

            # ШАГ 3: Медиа-анализ ТОЛЬКО для выбранных постов
            if args.enable_media_download:
                for i, post in enumerate(sampled, start=1):
                    has_media = any([
                        post.get("has_photo"),
                        post.get("has_video"),
                        post.get("has_video_note"),
                        post.get("has_voice"),
                    ])
                    if has_media:
                        logger.debug(
                            f"  [{i}/{len(sampled)}] Медиа-анализ поста {post['post_id']}"
                        )
                        post = await client.analyze_media_for_post(post, media_analyzer)
                        sampled[i - 1] = post

            # ШАГ 4: Классификация типа для выбранных постов
            for post in sampled:
                post["segment"]      = segment
                post["segment_name"] = SEGMENT_NAMES.get(segment, segment)

                if post.get("image_ocr_text") or post.get("video_frame_ocr_text"):
                    stats["ocr_used"] += 1
                if post.get("voice_transcript") or post.get("audio_transcript"):
                    stats["stt_used"] += 1
                if post.get("image_description") or post.get("video_description"):
                    stats["vision_used"] += 1

                extra_text = " ".join(filter(None, [
                    post.get("image_ocr_text", ""),
                    post.get("video_frame_ocr_text", ""),
                    post.get("audio_transcript", ""),
                    post.get("voice_transcript", ""),
                ]))
                img_desc = " ".join(filter(None, [
                    post.get("image_description", ""),
                    post.get("video_description", ""),
                ]))

                type_result = classify_type(
                    text=post.get("text", ""),
                    format_name=post.get("format_name", ""),
                    extra_text=extra_text,
                    image_description=img_desc,
                    has_poll=post.get("has_poll", False),
                    has_gif=post.get("has_gif", False),
                    has_sticker=post.get("has_sticker", False),
                    mode=args.type_mode,
                    threshold=args.review_threshold,
                    provider=llm_provider,
                    model=llm_model,
                    api_key=llm_api_key,
                )

                post["type_code"]              = type_result.type_code
                post["type_name"]              = type_result.type_name
                post["type_confidence"]        = type_result.type_confidence
                post["type_reason"]            = type_result.type_reason
                post["type_evidence"]          = type_result.type_evidence
                post["analysis_basis"]         = type_result.analysis_basis
                post["llm_used"]               = type_result.llm_used
                post["manual_review_required"] = type_result.manual_review_required

                fc = post.get("format_code")
                tc = post.get("type_code")
                post["combo_code"] = f"{fc if fc is not None else '?'}.{tc if tc is not None else '?'}"
                post["combo_name"] = f"{post.get('format_name','')} + {post.get('type_name','')}"

                # Убираем служебное поле перед экспортом
                post.pop("_message", None)

                if type_result.llm_used:
                    stats["llm_used"] += 1
                if type_result.manual_review_required:
                    stats["manual_review"] += 1

                stats["type_classified"]   += 1
                stats["format_classified"] += 1

            all_posts.extend(sampled)

    except KeyboardInterrupt:
        logger.warning("Прерывание (Ctrl+C)")
    finally:
        await client.stop()

    # Итоги
    logger.info("=" * 60)
    logger.info(f"Собрано постов:          {stats['total_collected']}")
    logger.info(f"Выбрано постов:          {stats['total_sampled']}")
    logger.info(f"Медиа-анализ (OCR):      {stats['ocr_used']}")
    logger.info(f"Медиа-анализ (STT):      {stats['stt_used']}")
    logger.info(f"Медиа-анализ (Vision):   {stats['vision_used']}")
    logger.info(f"Использовано LLM:        {stats['llm_used']}")
    logger.info(f"Требуют проверки:        {stats['manual_review']}")
    logger.info("=" * 60)

    if not all_posts:
        logger.error("Нет постов для экспорта")
        return

    fashion_channels = sum(1 for ch in channels if ch["segment"] == "fashion")
    beauty_channels  = sum(1 for ch in channels if ch["segment"] == "beauty")
    fashion_posts_n  = sum(1 for p in all_posts if p.get("segment") == "fashion")
    beauty_posts_n   = sum(1 for p in all_posts if p.get("segment") == "beauty")

    method_meta = {
        "Период анализа":               f"{start_date.date()} — {end_date.date()}",
        "Всего каналов":                len(channels),
        "Каналов (Мода)":               fashion_channels,
        "Каналов (Красота)":            beauty_channels,
        "Постов в выборке":             len(all_posts),
        "Постов (Мода)":                fashion_posts_n,
        "Постов (Красота)":             beauty_posts_n,
        "Постов в месяц":               args.posts_per_month,
        "Seed":                         args.seed,
        "Режим классификации типов":    args.type_mode,
        "Vision провайдер":             vision_provider,
        "Vision модель":                vision_model,
        "OCR включён":                  args.enable_ocr,
        "STT включён":                  args.enable_audio_transcription,
        "Vision включён":               args.enable_vision,
        "Медиа только для выборки":     True,
        "Использовано OCR (постов)":    stats["ocr_used"],
        "Использовано STT (постов)":    stats["stt_used"],
        "Использовано Vision (постов)": stats["vision_used"],
        "Требуют ручной проверки":      stats["manual_review"],
    }

    build_report(all_posts, output_path, method_meta)

    manual_path = Path(output_path).with_name(
        Path(output_path).stem + "_manual_review.xlsx"
    )
    build_manual_review(all_posts, str(manual_path))

    print(f"\n✅ Готово!")
    print(f"   Отчёт:            {output_path}")
    print(f"   Ручная проверка:  {manual_path}")
    print(f"   Логи:             {args.log}")
    print(f"\n   Постов в выборке:   {len(all_posts)}")
    print(f"   Требуют проверки:   {stats['manual_review']}")
    print(f"   OCR использован:    {stats['ocr_used']} постов")
    print(f"   STT использован:    {stats['stt_used']} постов")
    print(f"   Vision использован: {stats['vision_used']} постов")


def main():
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
