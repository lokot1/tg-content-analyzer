"""
media_analyzer.py — анализ медиа: OCR, расшифровка аудио, извлечение кадров видео,
локальный vision через Ollama (qwen2.5vl:7b и др.).

Исправления:
- Tesseract: путь устанавливается ДО любых OCR-вызовов, не зависит от PATH
- Ollama: увеличенное время ожидания загрузки модели в VRAM
"""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("tg_analyzer")

# ---------------------------------------------------------------------------
# Опциональные зависимости — импортируем без проверки пути к tesseract
# ---------------------------------------------------------------------------

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.debug("Pillow не установлен — OCR недоступен")

try:
    import pytesseract
    PYTESSERACT_AVAILABLE = True
except ImportError:
    PYTESSERACT_AVAILABLE = False
    logger.debug("pytesseract не установлен — OCR недоступен")

try:
    import moviepy.editor as mp
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False
    logger.debug("moviepy не установлен — извлечение кадров недоступно")

try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    logger.debug("whisper не установлен — STT недоступен")

try:
    import ollama as ollama_client
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    logger.debug("ollama не установлен — локальный vision недоступен")


# ---------------------------------------------------------------------------
# Результат анализа медиа
# ---------------------------------------------------------------------------

@dataclass
class MediaAnalysisResult:
    image_ocr_text: str = ""
    image_description: str = ""
    video_frame_ocr_text: str = ""
    video_description: str = ""
    audio_transcript: str = ""
    voice_transcript: str = ""
    analysis_level: str = "basic"
    analysis_basis: str = "basic"
    errors: list[str] = field(default_factory=list)

    def get_all_text(self) -> str:
        parts = [
            self.image_ocr_text,
            self.video_frame_ocr_text,
            self.audio_transcript,
            self.voice_transcript,
        ]
        return " ".join(p for p in parts if p).strip()

    def get_description(self) -> str:
        parts = [self.image_description, self.video_description]
        return " ".join(p for p in parts if p).strip()

    def build_basis(self, has_text: bool) -> str:
        parts = ["text"] if has_text else []
        if self.image_ocr_text or self.video_frame_ocr_text:
            parts.append("ocr")
        if self.audio_transcript or self.voice_transcript:
            parts.append("stt")
        if self.image_description or self.video_description:
            parts.append("local_vision")
        return "+".join(parts) if parts else "basic"


# ---------------------------------------------------------------------------
# Основной класс
# ---------------------------------------------------------------------------

class MediaAnalyzer:

    def __init__(
        self,
        enable_ocr: bool = False,
        enable_audio_transcription: bool = False,
        enable_vision: bool = False,
        enable_media_download: bool = False,
        keep_media: bool = False,
        media_dir: str = "media_tmp",
        tesseract_cmd: str = "",
        whisper_model_name: str = "small",
        vision_provider: str = "ollama",
        vision_api_key: str = "",
        vision_model: str = "qwen2.5vl:7b",
        video_frame_interval: int = 10,
        max_video_frames: int = 5,
    ):
        self.enable_media_download = enable_media_download
        self.keep_media = keep_media
        self.media_dir = Path(media_dir)
        self.vision_provider = vision_provider
        self.vision_api_key = vision_api_key
        self.vision_model = vision_model
        self.video_frame_interval = video_frame_interval
        self.max_video_frames = max_video_frames

        # ----------------------------------------------------------------
        # TESSERACT: устанавливаем путь ПЕРВЫМ делом, до любых OCR-вызовов
        # Это ключевое исправление — раньше путь устанавливался после проверки
        # ----------------------------------------------------------------
        self._tesseract_ok = False

        # Приоритет 1: явный путь из .env / аргумента
        if tesseract_cmd and os.path.isfile(tesseract_cmd):
            if PYTESSERACT_AVAILABLE:
                pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
                self._tesseract_ok = True
                logger.info(f"Tesseract: путь установлен → {tesseract_cmd}")

        # Приоритет 2: стандартный путь Windows если .env не задан
        if not self._tesseract_ok:
            default_win = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
            if os.path.isfile(default_win) and PYTESSERACT_AVAILABLE:
                pytesseract.pytesseract.tesseract_cmd = default_win
                self._tesseract_ok = True
                logger.info(f"Tesseract: найден по умолчанию → {default_win}")

        # Приоритет 3: проверяем что tesseract есть в PATH
        if not self._tesseract_ok and PYTESSERACT_AVAILABLE:
            try:
                subprocess.run(
                    ["tesseract", "--version"],
                    capture_output=True, timeout=5
                )
                self._tesseract_ok = True
                logger.info("Tesseract: найден в PATH")
            except Exception:
                pass

        if not self._tesseract_ok:
            logger.warning(
                "Tesseract не найден. OCR будет отключён. "
                "Добавьте в .env: TESSERACT_CMD=C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
            )

        self.enable_ocr = enable_ocr and PIL_AVAILABLE and PYTESSERACT_AVAILABLE and self._tesseract_ok

        # ----------------------------------------------------------------
        # OLLAMA: проверяем доступность
        # ----------------------------------------------------------------
        self.enable_vision = enable_vision
        if enable_vision and vision_provider == "ollama":
            if not OLLAMA_AVAILABLE:
                logger.warning("Библиотека ollama не установлена: pip install ollama")
                self.enable_vision = False
            else:
                self._warmup_ollama()

        # ----------------------------------------------------------------
        # WHISPER
        # ----------------------------------------------------------------
        self._whisper_model = None
        self.enable_audio_transcription = False
        if enable_audio_transcription:
            if not WHISPER_AVAILABLE:
                logger.warning("openai-whisper не установлен: pip install openai-whisper")
            else:
                try:
                    logger.info(f"Загрузка Whisper модели '{whisper_model_name}'...")
                    self._whisper_model = whisper.load_model(whisper_model_name)
                    self.enable_audio_transcription = True
                    logger.info("Whisper модель загружена")
                except Exception as e:
                    logger.error(f"Не удалось загрузить Whisper: {e}")

        # Создаём папку для медиа
        if self.enable_media_download:
            self.media_dir.mkdir(parents=True, exist_ok=True)

        # Итоговый статус
        logger.info(
            f"MediaAnalyzer готов — OCR: {self.enable_ocr}, "
            f"STT: {self.enable_audio_transcription}, "
            f"Vision: {self.enable_vision}"
        )

    def _warmup_ollama(self):
        """Прогревает Ollama через прямой HTTP запрос."""
        import urllib.request
        import json as _json
        logger.info(f"Ollama: проверка доступности модели {self.vision_model}...")
        payload = _json.dumps({
            "model": self.vision_model,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        }).encode("utf-8")
        max_attempts = 8
        wait_seconds = 15
        for attempt in range(1, max_attempts + 1):
            try:
                req = urllib.request.Request(
                    "http://localhost:11434/api/chat",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp = urllib.request.urlopen(req, timeout=30)
                _json.loads(resp.read())
                logger.info(f"Ollama: модель {self.vision_model} готова ✓")
                return
            except Exception as e:
                err_str = str(e)
                if "503" in err_str or "loading" in err_str.lower():
                    logger.info(f"Ollama загружает модель, попытка {attempt}/{max_attempts}, жду {wait_seconds} сек...")
                    time.sleep(wait_seconds)
                else:
                    logger.warning(f"Ollama недоступна: {e}")
                    self.enable_vision = False
                    return
        logger.warning(f"Ollama не ответила за {max_attempts * wait_seconds} сек. Vision отключён.")
        self.enable_vision = False

    def _check_ollama_list(self):
        """Проверяет что модель скачана."""
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True, text=True, timeout=5
            )
            if self.vision_model in result.stdout:
                logger.info(f"Ollama: модель {self.vision_model} найдена ✓")
            else:
                logger.warning(
                    f"Ollama: модель {self.vision_model} не найдена. "
                    f"Запустите: ollama pull {self.vision_model}"
                )
        except Exception as e:
            logger.warning(f"Не удалось проверить список моделей Ollama: {e}")

    # ------------------------------------------------------------------
    # Главный метод
    # ------------------------------------------------------------------

    async def analyze(
        self,
        message,
        telegram_client,
        has_photo: bool = False,
        has_video: bool = False,
        has_video_note: bool = False,
        has_voice: bool = False,
        download_func=None,
    ) -> MediaAnalysisResult:
        result = MediaAnalysisResult()

        if not self.enable_media_download:
            result.analysis_level = "basic"
            return result

        if not any([has_photo, has_video, has_video_note, has_voice]):
            result.analysis_level = "basic"
            return result

        if message is None or not hasattr(message, 'media') or message.media is None:
            result.analysis_level = "basic"
            return result

        try:
            if has_photo:
                await self._analyze_photo(message, telegram_client, result, download_func)
            elif has_video_note:
                await self._analyze_video(message, telegram_client, result, is_note=True, download_func=download_func)
            elif has_video:
                await self._analyze_video(message, telegram_client, result, is_note=False, download_func=download_func)
            elif has_voice:
                await self._analyze_voice(message, telegram_client, result, download_func)
        except Exception as e:
            post_id = getattr(message, 'id', '?')
            logger.error(f"Ошибка анализа медиа поста {post_id}: {e}")
            result.errors.append(str(e))

        return result

    # ------------------------------------------------------------------
    # Анализ фото
    # ------------------------------------------------------------------

    async def _analyze_photo(self, message, client, result: MediaAnalysisResult, download_func=None):
        post_id = getattr(message, 'id', 'unknown')
        tmp_path = self.media_dir / f"photo_{post_id}.jpg"
        try:
            if download_func:
                ok = await download_func(client, message, str(tmp_path))
            else:
                await client.download_media(message, str(tmp_path))
                ok = tmp_path.exists() and tmp_path.stat().st_size > 0
            if not ok:
                result.errors.append(f"photo_{post_id}: не удалось скачать")
                return

            if self.enable_ocr:
                ocr_text = self._run_ocr(str(tmp_path))
                result.image_ocr_text = ocr_text
                result.analysis_level = "ocr"
                if ocr_text:
                    logger.debug(f"OCR фото {post_id}: {ocr_text[:60]}...")

            if self.enable_vision:
                description = self._run_vision_image(str(tmp_path))
                result.image_description = description
                result.analysis_level = "vision"
                if description:
                    logger.debug(f"Vision фото {post_id}: {description[:60]}...")

        except Exception as e:
            logger.warning(f"Ошибка анализа фото (пост {post_id}): {e}")
            result.errors.append(f"photo: {e}")
        finally:
            if not self.keep_media and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Анализ видео и кружков
    # ------------------------------------------------------------------

    async def _analyze_video(
        self, message, client, result: MediaAnalysisResult, is_note: bool = False, download_func=None
    ):
        post_id = getattr(message, 'id', 'unknown')
        suffix = "note" if is_note else "video"
        tmp_video = self.media_dir / f"{suffix}_{post_id}.mp4"
        try:
            if download_func:
                ok = await download_func(client, message, str(tmp_video))
            else:
                await client.download_media(message, str(tmp_video))
                ok = tmp_video.exists() and tmp_video.stat().st_size > 0
            if not ok:
                result.errors.append(f"{suffix}_{post_id}: не удалось скачать")
                return

            if self.enable_ocr and MOVIEPY_AVAILABLE:
                frames_text = self._extract_frames_ocr(str(tmp_video), post_id)
                result.video_frame_ocr_text = frames_text
                result.analysis_level = "ocr"

            if self.enable_audio_transcription:
                transcript = self._transcribe_video(str(tmp_video))
                if is_note:
                    result.voice_transcript = transcript
                else:
                    result.audio_transcript = transcript
                if transcript:
                    result.analysis_level = "stt"

            if self.enable_vision and MOVIEPY_AVAILABLE:
                description = self._run_vision_video(str(tmp_video), post_id)
                result.video_description = description
                result.analysis_level = "vision"

        except Exception as e:
            logger.warning(f"Ошибка анализа видео (пост {post_id}): {e}")
            result.errors.append(f"video: {e}")
        finally:
            if not self.keep_media and tmp_video.exists():
                tmp_video.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Анализ голосовых
    # ------------------------------------------------------------------

    async def _analyze_voice(self, message, client, result: MediaAnalysisResult, download_func=None):
        post_id = getattr(message, 'id', 'unknown')
        tmp_voice = self.media_dir / f"voice_{post_id}.ogg"
        try:
            if download_func:
                ok = await download_func(client, message, str(tmp_voice))
            else:
                await client.download_media(message, str(tmp_voice))
                ok = tmp_voice.exists() and tmp_voice.stat().st_size > 0
            if not ok:
                result.errors.append(f"voice_{post_id}: не удалось скачать")
                return

            if self.enable_audio_transcription:
                transcript = self._transcribe_audio(str(tmp_voice))
                result.voice_transcript = transcript
                if transcript:
                    result.analysis_level = "stt"

        except Exception as e:
            logger.warning(f"Ошибка анализа голосового (пост {post_id}): {e}")
            result.errors.append(f"voice: {e}")
        finally:
            if not self.keep_media and tmp_voice.exists():
                tmp_voice.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # OCR
    # ------------------------------------------------------------------

    def _run_ocr(self, image_path: str) -> str:
        if not self.enable_ocr:
            return ""
        try:
            img = Image.open(image_path)
            # Конвертируем в RGB если нужно (PNG с прозрачностью и т.д.)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            text = pytesseract.image_to_string(img, lang="rus+eng")
            return text.strip()
        except Exception as e:
            logger.warning(f"OCR ошибка ({image_path}): {e}")
            return ""

    def _extract_frames_ocr(self, video_path: str, post_id) -> str:
        if not self.enable_ocr or not MOVIEPY_AVAILABLE:
            return ""
        try:
            clip = mp.VideoFileClip(video_path)
            duration = clip.duration
            timestamps = []
            t = 0
            while t < duration and len(timestamps) < self.max_video_frames:
                timestamps.append(t)
                t += self.video_frame_interval
            if not timestamps:
                timestamps = [duration * 0.5]

            texts = []
            for i, ts in enumerate(timestamps):
                frame_path = self.media_dir / f"frame_{post_id}_{i}.jpg"
                try:
                    clip.save_frame(str(frame_path), t=min(ts, duration - 0.01))
                    text = self._run_ocr(str(frame_path))
                    if text:
                        texts.append(text)
                finally:
                    if frame_path.exists() and not self.keep_media:
                        frame_path.unlink(missing_ok=True)
            clip.close()
            return " ".join(texts)
        except Exception as e:
            logger.warning(f"Извлечение кадров ошибка ({video_path}): {e}")
            return ""

    # ------------------------------------------------------------------
    # STT (Whisper)
    # ------------------------------------------------------------------

    def _transcribe_audio(self, audio_path: str) -> str:
        if not self._whisper_model:
            return ""
        try:
            res = self._whisper_model.transcribe(audio_path, language="ru")
            return res.get("text", "").strip()
        except Exception as e:
            logger.warning(f"STT ошибка ({audio_path}): {e}")
            return ""

    def _has_audio_stream(self, video_path: str) -> bool:
        """Проверяет наличие аудиодорожки через ffprobe. Если нет — Whisper не запускается."""
        try:
            import subprocess
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-select_streams", "a",
                 "-show_entries", "stream=codec_type", "-of", "csv=p=0", video_path],
                capture_output=True, text=True, timeout=10
            )
            return "audio" in result.stdout
        except Exception:
            return True  # если ffprobe недоступен — пробуем расшифровать

    def _transcribe_video(self, video_path: str) -> str:
        if not self._whisper_model:
            return ""
        # Проверяем наличие аудиодорожки — не тратим время на немые видео
        if not self._has_audio_stream(video_path):
            logger.debug(f"Видео без аудиодорожки — STT пропущен")
            return ""
        try:
            res = self._whisper_model.transcribe(video_path, language="ru")
            return res.get("text", "").strip()
        except Exception as e:
            logger.warning(f"STT видео ошибка ({video_path}): {e}")
            return ""

    # ------------------------------------------------------------------
    # Vision
    # ------------------------------------------------------------------

    def _run_vision_image(self, image_path: str) -> str:
        if self.vision_provider == "ollama":
            return self._ollama_vision(image_path)
        elif self.vision_provider == "anthropic":
            return self._anthropic_vision(image_path)
        elif self.vision_provider == "openai":
            return self._openai_vision(image_path)
        return ""

    def _run_vision_video(self, video_path: str, post_id) -> str:
        if not MOVIEPY_AVAILABLE:
            return ""
        frame_path = self.media_dir / f"vframe_{post_id}.jpg"
        try:
            clip = mp.VideoFileClip(video_path)
            clip.save_frame(str(frame_path), t=clip.duration * 0.5)
            clip.close()
            return self._run_vision_image(str(frame_path))
        except Exception as e:
            logger.warning(f"Vision видео ошибка ({video_path}): {e}")
            return ""
        finally:
            if frame_path.exists() and not self.keep_media:
                frame_path.unlink(missing_ok=True)

    def _ollama_vision(self, image_path: str) -> str:
        """
        Отправляет изображение в Ollama через прямой HTTP запрос.
        Используем urllib вместо библиотеки ollama — она некорректно
        передаёт изображения в версии 0.6.x.
        """
        import urllib.request
        import json as _json
        try:
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()
            prompt = (
                "Ты анализируешь изображение из поста Telegram-канала бренда (мода или косметика). "
                "Опиши кратко (2-3 предложения) на русском языке: "
                "что изображено, есть ли цена, скидка или призыв к покупке, "
                "общий характер: продающее, имиджевое, образовательное, развлекательное или анонс."
            )
            payload = _json.dumps({
                "model": self.vision_model,
                "messages": [{"role": "user", "content": prompt, "images": [img_b64]}],
                "stream": False,
            }).encode("utf-8")
            req = urllib.request.Request(
                "http://localhost:11434/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=60)
            result = _json.loads(resp.read())
            return result["message"]["content"].strip()
        except Exception as e:
            logger.warning(f"Ollama vision ошибка ({image_path}): {e}")
            return ""

    def _anthropic_vision(self, image_path: str) -> str:
        if not self.vision_api_key:
            return ""
        try:
            import anthropic
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode()
            client = anthropic.Anthropic(api_key=self.vision_api_key)
            response = client.messages.create(
                model=self.vision_model or "claude-sonnet-4-20250514",
                max_tokens=256,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/jpeg",
                        "data": image_data,
                    }},
                    {"type": "text", "text": "Опиши это изображение кратко для маркетингового анализа."},
                ]}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.warning(f"Anthropic vision ошибка: {e}")
            return ""

    def _openai_vision(self, image_path: str) -> str:
        if not self.vision_api_key:
            return ""
        try:
            import openai
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode()
            client = openai.OpenAI(api_key=self.vision_api_key)
            response = client.chat.completions.create(
                model=self.vision_model or "gpt-4o",
                max_tokens=256,
                messages=[{"role": "user", "content": [
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{image_data}"
                    }},
                    {"type": "text", "text": "Опиши это изображение кратко для маркетингового анализа."},
                ]}],
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"OpenAI vision ошибка: {e}")
            return ""
