"""
type_classifier.py — классификация ТИПА контента (коды 1–7).

Типология по доминирующей функции (Приложение 2 ВКР):
  1 — Информационный      — передать сведения без побуждения к действию
  2 — Образовательный     — научить, сформировать экспертный статус
  3 — Анонсовый           — создать ожидание будущего события
  4 — Продающий           — стимулировать покупку (прямо или косвенно)
  5 — Вовлекающий         — получить обратную связь, активизировать диалог
  6 — Развлекательный     — лёгкий эмоциональный фон, «человечивание» бренда
  7 — Имиджево-вдохновляющий — транслировать философию и ценности бренда

Правила приоритета доминирующей функции:
  Вовлекающий > Продающий > Анонсовый > Образовательный >
  Информационный > Имиджево-вдохновляющий > Развлекательный

  Примеры:
  - Гайд по уходу + ссылка на покупку в конце → Образовательный
    (основной посыл — научить; ссылка вторична)
  - Анонс конкурса → Вовлекающий (не анонсовый)
  - Информация о новинке + ссылка на WB → Продающий
  - Красивые фото без цены/даты/вопроса → Имиджево-вдохновляющий

Режимы:
  rules  — только словари и правила
  llm    — только Ollama / Anthropic / OpenAI
  hybrid — сначала rules, при низкой уверенности → LLM
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("tg_analyzer")

# ---------------------------------------------------------------------------
# Модель результата
# ---------------------------------------------------------------------------

TYPE_NAMES = {
    1: "Информационный",
    2: "Образовательный",
    3: "Анонсовый",
    4: "Продающий",
    5: "Вовлекающий",
    6: "Развлекательный",
    7: "Имиджево-вдохновляющий",
}

TYPE_REASONS = {
    1: "Пост передаёт актуальные сведения или новости без побуждения к немедленному действию.",
    2: "Пост обучает аудиторию — содержит инструкцию, совет, разбор или пошаговое объяснение.",
    3: "Пост анонсирует предстоящее событие — создаёт ожидание и подталкивает к планированию.",
    4: "Пост стимулирует покупку — содержит явное коммерческое предложение, цену или призыв к заказу.",
    5: "Пост вовлекает аудиторию в диалог — содержит вопрос, опрос, конкурс или призыв к реакции.",
    6: "Пост создаёт лёгкий эмоциональный фон — юмор, мем или ситуативный контент без утилитарной ценности.",
    7: "Пост транслирует философию и ценности бренда — эстетика, вдохновение, backstage без продающего посыла.",
}

# Правила приоритета — чем выше индекс, тем выше приоритет
TYPE_PRIORITY = {5: 7, 4: 6, 3: 5, 2: 4, 1: 3, 7: 2, 6: 1}


@dataclass
class TypeResult:
    type_code: Optional[int]
    type_name: str
    type_confidence: float
    type_reason: str
    type_evidence: list[str]
    analysis_basis: str
    llm_used: bool
    manual_review_required: bool


# ---------------------------------------------------------------------------
# Расширенные словари индикаторов
# ---------------------------------------------------------------------------

INDICATORS: dict[int, list[str]] = {

    # ------------------------------------------------------------------
    # 1 — ИНФОРМАЦИОННЫЙ
    # Новости, факты, достижения — без побуждения к действию
    # ------------------------------------------------------------------
    1: [
        # Новостные маркеры
        "сообщаем", "стало известно", "представляем", "подводим итоги",
        "итоги", "результаты", "достижени", "лауреат", "премия", "награда",
        "вышел", "вышла", "вышло", "релиз", "запустили", "открылся",
        "открылась", "обновление", "изменени", "новость", "анонсируем",
        # Факты и данные
        "по данным", "согласно", "установлено", "выяснилось",
        "оказывается", "как выяснилось", "стало понятно",
        "статистика", "данные", "исследование", "отчёт", "рейтинг",
        "факт:", "кстати,",
        # Коллаборации и партнёрства
        "коллаборация", "партнёрство", "сотрудничество", "совместно с",
        "вместе с брендом", "специальный проект",
        # Достижения бренда
        "получили награду", "стали победителями", "вошли в топ",
        "вошли в список", "признаны лучшими", "сертификат", "сертификация",
        "протестировано", "одобрено", "рекомендовано",
        # Нейтральная подача новостей
        "сегодня расскажем", "делимся новостью", "спешим поделиться",
        "у нас новость", "важная новость", "небольшой апдейт", "апдейт",
        "новинка уже", "уже доступно", "уже в продаже",
        "уже появилась", "уже появился",
        # Новости производства и бренда
        "производство", "фабрика", "завод", "команда бренда",
        "наша команда создала", "мы разработали", "мы создали",
    ],

    # ------------------------------------------------------------------
    # 2 — ОБРАЗОВАТЕЛЬНЫЙ
    # Учит, объясняет, формирует экспертность — даже если есть ссылка
    # ------------------------------------------------------------------
    2: [
        # Прямые образовательные маркеры
        "как правильно", "пошаговая инструкция", "лайфхак", "лайф-хак",
        "совет стилиста", "совет эксперта", "разбираем", "объясняем",
        "инструкция", "советы", "рекомендации", "разбор", "гид", "гайд",
        # Как использовать
        "как использовать", "как наносить", "как выбрать", "как сочетать",
        "как работает", "нужно ли", "можно ли", "зачем нужен",
        "почему важно", "чем отличается",
        "как правильно использовать", "как правильно наносить",
        # Структурные маркеры (нумерация, последовательность)
        "шаг 1", "шаг 2", "шаг 3", "во-первых", "во-вторых", "в-третьих",
        "сначала", "затем", "потом", "после этого",
        "пошагово", "по шагам", "шаг за шагом",
        "пункт 1", "пункт 2",
        # Объяснительная логика
        "потому что", "это значит", "то есть", "иными словами",
        "разберёмся", "объясним", "рассказываем", "делимся знаниями",
        "расскажем как", "покажем как", "расскажем о",
        "подробнее о", "разложим по полочкам",
        # Состав и формула
        "в составе", "в составах", "ищем в составах", "состав",
        "активные компоненты", "ингредиенты", "формула",
        "гиалуроновая", "ретинол", "ниацинамид", "сквалан",
        "кислота", "витамин", "масло", "экстракт", "пептиды",
        # Уход и рутина
        "уход за", "рутина", "routine", "бьюти-рутина",
        "утренний уход", "вечерний уход", "уход для",
        "подходит для", "подойдёт для", "рекомендуется для",
        # Вопросительная образовательная форма
        "знаете ли вы", "а вы знали", "вы знали что",
        "задумывались ли", "а знаешь ли ты",
        # Топы и списки советов
        "топ советов", "топ ошибок", "частые ошибки",
        "правила ухода", "правила нанесения",
        "держи совет", "держи лайфхак", "делимся секретом",
        "полный гайд", "полная инструкция",
        "5 советов", "3 совета", "7 правил",
    ],

    # ------------------------------------------------------------------
    # 3 — АНОНСОВЫЙ
    # Всегда смотрит в будущее — дата/время обязательны или подразумеваются
    # ------------------------------------------------------------------
    3: [
        # Прямые анонсы
        "уже завтра", "скоро", "готовимся к запуску", "не пропустите",
        "сохраняйте дату", "сохрани дату", "save the date",
        "будет", "состоится", "запланировано", "предстоит",
        "анонс", "preview", "тизер", "teaser", "coming soon",
        # Временные маркеры будущего
        "в ближайшее время", "уже скоро", "совсем скоро",
        "через две недели", "через неделю", "через несколько дней",
        "в эти выходные", "на этой неделе", "на следующей неделе",
        "с 12 по", "с 15 по", "с 1 по",
        # Конкретные даты и время (без продажи)
        "в 19:00", "в 18:00", "в 20:00", "в 12:00",
        # Прямые эфиры и события
        "прямой эфир", "ждите нас в эфире", "встретимся в эфире",
        "онлайн-встреча", "онлайн-лекция", "онлайн-практика",
        "мероприятие", "ивент", "event", "вебинар", "мастер-класс",
        # Новые продукты — только если нет цены/ссылки
        "скоро в продаже", "скоро появится", "появится в продаже",
        "готовится к выходу", "выйдет совсем скоро",
        "первыми узнаете", "первыми увидите",
        # Ожидание и интрига
        "ждите", "следите за обновлениями", "следи за каналом",
        "оставайтесь с нами", "не переключайтесь",
        "скоро расскажем", "скоро покажем", "готовим сюрприз",
        "есть кое-что интересное", "есть новости",
    ],

    # ------------------------------------------------------------------
    # 4 — ПРОДАЮЩИЙ
    # Явное коммерческое предложение — главный критерий
    # ------------------------------------------------------------------
    4: [
        # Цены и скидки
        "цена", "стоимость", "руб", "₽", "скидка", "скидки", "%",
        "−30%", "−20%", "−50%", "минус 30", "минус 20",
        "2000 рублей", "3500 рублей", "стоит 2000", "стоит 3500",
        "за 2000", "за 3500", "от 990", "от 1490",
        # Промокоды и акции
        "промокод", "promo", "промо", "по промокоду",
        "акция", "распродажа", "sale", "выгода", "выгодно",
        "специальное предложение", "лимитированное предложение",
        "только сегодня", "только до", "успей", "последний шанс",
        "ограниченное количество", "пока есть в наличии",
        # Призывы к покупке
        "купить", "заказать", "оформить заказ", "оформить подписку",
        "добавить в корзину", "в корзину", "купи сейчас",
        "заказывай", "покупай", "приобрести",
        # Маркетплейсы и ссылки на покупку
        "по ссылке", "переходи по ссылке", "ссылка в шапке",
        "ссылка в описании", "ссылка в био",
        "уже на wb", "уже на wildberries", "уже на ozon",
        "уже на озон", "уже на золотом яблоке",
        "wb", "wildberries", "ozon", "озон",
        "доступно на сайте", "в наличии", "в нашем магазине",
        "держи ссылки", "держи ссылку", "забрать по ссылке",
        # Доставка и бонусы
        "бесплатная доставка", "подарок при заказе", "кешбэк",
        "бонусы", "баллы", "пришлют", "доставим",
        # Товарные подборки
        "набор для", "сет из", "готовый сет", "подарочный бокс",
        "подарочный набор", "заказать набор", "собрали набор",
        "идеальный подарок", "отличный подарок",
        # Мягкие продающие конструкции
        "вы знаете что делать", "уже ждёт вас",
        "уже можно заказать", "теперь доступно",
        "попробуй", "попробуйте",
    ],

    # ------------------------------------------------------------------
    # 5 — ВОВЛЕКАЮЩИЙ
    # Высший приоритет — если есть хоть один признак, это вовлекающий
    # ------------------------------------------------------------------
    5: [
        # Опросы и голосования
        "опрос", "голосование", "голосуйте", "голосуй",
        "проголосуй", "выбери", "выбирай",
        # Вопросы к аудитории
        "какой оттенок", "какой вариант", "что выберете",
        "а вы", "а у тебя", "что ты думаешь",
        "как вы относитесь", "как ты относишься",
        "что предпочитаешь", "что предпочитаете",
        "твоё мнение", "ваше мнение",
        "как тебе", "как вам",
        # Призывы к комментариям
        "пишите в комментариях", "напишите в комментарии",
        "пиши в комментах", "пишите в комментах",
        "оставь комментарий", "напишите нам",
        "делитесь мнением", "поделитесь", "расскажите",
        "стикер в комментариях", "оставь стикер",
        "жду ваших ответов", "жду ответов",
        "напишите в комментах", "пишите нам",
        # Конкурсы и розыгрыши
        "конкурс", "розыгрыш", "giveaway", "условия участия",
        "участвуй", "участвуйте", "выиграй", "выиграйте",
        "разыгрываем", "разыгрываем приз", "приз",
        "победитель", "победители", "итоги конкурса",
        # Отметки и шеры
        "отметьте друга", "отметь друга", "тегните",
        "поделись с подругой", "перешли подруге",
        "отправляйте своим", "покажи подруге",
        # Реакции
        "поставьте реакцию", "поставь реакцию",
        "ставь 🔥", "ставь ❤️", "ставь +", "ставь лайк",
        "лайк если", "огонь если", "сердечко если",
        "ставь огонь", "ставь сердечко",
        # Сообщества
        "хочу вступить", "комьюнити", "community", "safe space",
        "наше сообщество", "вступай в клуб", "присоединяйся",
        "стань частью", "быть частью",
        # Интерактивные призывы
        "присылай", "присылайте", "покажи нам", "покажите нам",
        "поделись фото", "поделитесь фото",
        "фоткай и присылай", "снимай и присылай",
        "ждём ваши", "ждём твои",
        # Открытые вопросы без ответа
        "а что у тебя", "а что вы", "а ты",
        "расскажи в паре слов", "напиши нам",
        "что думаешь", "что скажешь",
    ],

    # ------------------------------------------------------------------
    # 6 — РАЗВЛЕКАТЕЛЬНЫЙ
    # Без утилитарной ценности — только эмоция и развлечение
    # ------------------------------------------------------------------
    6: [
        # Мемные конструкции
        "когда нанесла", "когда сделала", "когда купила",
        "когда", "я когда", "мы когда", "ситуация когда",
        "это я", "это мы", "узнаёшь себя", "это про меня",
        "ну и что", "ну и ладно",
        # Мемы про выход из группы
        "покинул(а) группу", "покинул группу", "покинула группу",
        "вышел из чата", "вышла из чата",
        "добавился в группу", "зашёл в чат",
        # Юмор и ирония
        "мем", "шутка", "смешно", "смеёмся", "ха-ха", "хаха",
        "лол", "lol", "ирония", "юмор", "сарказм", "иронично",
        "в шутку", "шутим", "не серьёзно",
        # Ситуативный контент
        "знакомо?", "узнаёте?", "бывало?", "случалось?",
        "только у меня или", "это нормально что",
        "скажите мне что я не одна", "скажите что не одна",
        # Лёгкие развлекательные форматы
        "обои", "обои для рабочего стола", "обои на телефон",
        "файлы в комментариях", "забирайте в комментариях",
        "гороскоп", "тест на",
        # Ситуативный юмор про дни недели
        "пятница", "понедельник", "выходные", "выходной",
        "наконец-то пятница", "дожили до пятницы",
        "понедельник снова", "снова понедельник",
        # Разговорные восклицания без продукта
        "чиллишь", "чилл", "chill",
        "вот это да!", "ну и дела!", "мы в шоке от",
    ],

    # ------------------------------------------------------------------
    # 7 — ИМИДЖЕВО-ВДОХНОВЛЯЮЩИЙ
    # Ценности, эстетика, философия — без цены, даты, вопроса
    # ------------------------------------------------------------------
    7: [
        # Мудборды и визуал
        "мудборд", "moodboard", "визуальная подборка",
        "атмосфера", "настроение", "mood", "эстетика",
        "aesthetic", "вдохновение", "вдохновляет",
        "вдохновляемся", "вдохновлён", "вдохновлена",
        # Закулисье и процесс
        "backstage", "закулисье", "за кадром", "за кулисами",
        "съёмки", "со съёмок", "кадры со съёмок",
        "процесс создания", "как создавался", "как мы делаем",
        # Ценности бренда
        "философия", "ценности", "миссия", "vision",
        "мы верим", "мы считаем", "наша позиция",
        "наш принцип", "принципы бренда",
        "бренд для", "мы — это",
        # Экология и ответственность
        "экологичность", "устойчивость", "sustainability",
        "eco", "эко", "забота о природе", "осознанность",
        "переработка", "без пластика", "натуральный состав",
        # Инклюзивность
        "инклюзивность", "inclusivity", "для всех",
        "любое тело", "любой тип кожи", "все оттенки",
        "разнообразие", "diversity", "принятие себя",
        "бодипозитив", "body positive",
        # Благотворительность
        "благотворительность", "благотворительный",
        "помогаем", "поддерживаем", "жертвуем",
        "часть средств идёт", "донейшн", "donation",
        # Образ и самовыражение
        "образ жизни", "lifestyle", "быть собой",
        "быть настоящей", "внутренний свет",
        "красота — это", "красота это",
        "внутренняя красота", "сила женщины",
        # Новые коллекции как искусство (БЕЗ цены и ссылок)
        "вдохновлён природой", "вдохновлён городом",
        "вдохновлён искусством", "вдохновлён тишиной",
        "за этим стоит история",
        # Арт-съёмка и нарратив
        "арт-съёмка", "арт съёмка", "арт-фото",
        "визуальный нарратив", "наш образ",
        "то, кто мы есть", "кто мы есть",
    ],
}

# ---------------------------------------------------------------------------
# Regex паттерны (весовой бонус +1.5 за каждое совпадение)
# ---------------------------------------------------------------------------

REGEX_PATTERNS: dict[int, list[str]] = {
    3: [  # Анонсовый — конкретные даты и время
        r"\d{1,2}\s*(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)",
        r"\d{1,2}[\.\/]\d{1,2}([\.\/]\d{2,4})?",
        r"в\s+\d{1,2}[:h]\d{2}",
        r"\d{1,2}\s+\w+\s+в\s+\d{1,2}[:h]\d{2}",
    ],
    4: [  # Продающий — цены
        r"\d+\s*[%процент]",
        r"\d[\d\s]*[₽руб]",
        r"от\s+\d+\s*₽",
        r"за\s+\d+\s*₽",
        r"−\d+%",
        r"\d+\s*руб",
    ],
    5: [  # Вовлекающий — вопросительные знаки в конце предложений
        r"\?{1,3}\s*$",
        r"\?\s+[А-ЯЁ]",
    ],
}

# ---------------------------------------------------------------------------
# Системный промпт для LLM — с кодификатором и примерами
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Ты эксперт по контент-анализу Telegram-каналов российских брендов моды и косметики.
Определи ДОМИНИРУЮЩИЙ тип контента поста по его коммуникативной функции.

ГЛАВНОЕ ПРАВИЛО: смотри на ЧЕМ ЗАНЯТ пост по содержанию — что занимает большую часть текста и внимания.
Маскировка не меняет тип: пост может быть оформлен как гайд, но если главная цель — продать, это продающий.

КОДИФИКАТОР ТИПОВ:

1 — ИНФОРМАЦИОННЫЙ
Функция: передать актуальные сведения без побуждения к действию.
Признаки: новости бренда, достижения, факты, аналитика трендов. Нейтральный тон.
Примеры: «Наш бренд получил премию», «Запустили новую линейку», «Итоги года»
НЕ информационный: если есть ссылка на покупку → продающий

2 — ОБРАЗОВАТЕЛЬНЫЙ
Функция: научить, сформировать экспертный статус бренда.
Признаки: инструкции, советы, разборы составов, как использовать продукт. Нумерация шагов.
Примеры: «5 правил ухода за кожей зимой», «Как правильно наносить патчи»
ВАЖНО: 80% текста обучение + 20% ссылка в конце → ОБРАЗОВАТЕЛЬНЫЙ
50% обучение + 50% продажа → ПРОДАЮЩИЙ

3 — АНОНСОВЫЙ
Функция: создать ожидание предстоящего события.
Признаки: конкретная дата или «скоро/завтра/на этой неделе», анонс запуска/эфира/акции.
ВАЖНО: анонс ВСЕГДА смотрит в будущее. Анонс скидки = анонсовый (не продающий).
Примеры: «15 мая в 19:00 прямой эфир», «Скоро запускаем новую коллекцию»

4 — ПРОДАЮЩИЙ
Функция: стимулировать покупку прямо сейчас.
Признаки: цена, ссылка на WB/Ozon/сайт, промокод, «купить», «заказать».
Примеры: «Скидка 30% по промокоду BEAUTY30», «Уже на WB по ссылке»
Пограничные случаи:
- Гайд + ссылки на все упомянутые товары → ПРОДАЮЩИЙ
- Конкурс с условием купить товар → ПРОДАЮЩИЙ

5 — ВОВЛЕКАЮЩИЙ
Функция: получить обратную связь, активизировать диалог.
Признаки: вопросы к аудитории, опросы, конкурсы БЕЗ условия покупки.
Примеры: «Какой оттенок выбрать? Голосуйте!», «Расскажите в комментариях»
ВАЖНО: пост незакончен без реакции читателя — вот главный признак.

6 — РАЗВЛЕКАТЕЛЬНЫЙ
Функция: лёгкий эмоциональный фон, юмор.
Признаки: мемы, шутки, ситуативный юмор. Пост не несёт утилитарной ценности.
Примеры мем-форматов:
- «[что-то] покинул(а) группу» — мем в формате уведомления
- «Когда [ситуация]... Знакомо?» — ситуативный юмор
- Короткие эмоциональные фразы без полезной информации
- Посты только с эмодзи или гифкой
НЕ развлекательный: если есть полезный совет → образовательный

7 — ИМИДЖЕВО-ВДОХНОВЛЯЮЩИЙ
Функция: транслировать ценности, философию, эстетику бренда.
Признаки: мудборды, backstage, посты о ценностях бренда.
Примеры: «Новый дроп вдохновлён тишиной леса», закулисье съёмок
НЕ имиджевый: если есть цена → продающий; если есть вопрос → вовлекающий

ДЛЯ КОРОТКИХ ПОСТОВ (менее 10 слов):
- Опирайся на формат поста и описание медиа если они есть
- Кружок/голосовое без текста → смотри описание медиа
- Если только эмодзи или 1-2 слова без контекста → тип 6 (развлекательный) или 7 (имиджевый)
- НЕ придумывай смысл которого нет — лучше снизь уверенность до 0.4-0.5

ВАЖНО: Отвечай ТОЛЬКО на русском языке. Не используй китайский или другие языки.

Верни СТРОГО JSON без markdown:
{
  "type_code": <число 1-7>,
  "type_name": "<название типа на русском>",
  "type_confidence": <число от 0.0 до 1.0>,
  "type_reason": "<1-2 предложения на русском: чем занят пост и почему этот тип>",
  "type_evidence": ["<ключевая фраза из текста поста>"]
}"""

VISION_PROMPT = """Describe this image from a Russian brand Telegram post in 1-2 sentences in Russian.
Focus on: what is shown, is there a product, price, discount, or call to action visible.
Be brief and factual."""


# ---------------------------------------------------------------------------
# Rule-based классификатор с весами позиций
# ---------------------------------------------------------------------------

def _score_text_weighted(text: str) -> dict[int, tuple[float, list[str]]]:
    """
    Подсчёт очков с учётом позиции в тексте.
    Начало текста (первые 30%) — вес ×2.
    Конец текста (последние 20%) — вес ×0.5.
    Середина — вес ×1.
    """
    if not text:
        return {t: (0.0, []) for t in INDICATORS}

    total_len = len(text)
    start_boundary = int(total_len * 0.30)
    end_boundary = int(total_len * 0.80)

    text_lower = text.lower()
    scores: dict[int, tuple[float, list[str]]] = {}

    for type_code, keywords in INDICATORS.items():
        total_score = 0.0
        hits = []

        for kw in keywords:
            kw_lower = kw.lower()
            pos = text_lower.find(kw_lower)
            while pos != -1:
                # Определяем вес по позиции
                if pos < start_boundary:
                    weight = 2.0
                elif pos >= end_boundary:
                    weight = 0.5
                else:
                    weight = 1.0

                total_score += weight
                if kw not in hits:
                    hits.append(kw)
                pos = text_lower.find(kw_lower, pos + 1)

        # Regex паттерны — всегда вес 1.5
        if type_code in REGEX_PATTERNS:
            for pattern in REGEX_PATTERNS[type_code]:
                if re.search(pattern, text_lower):
                    total_score += 1.5

        scores[type_code] = (total_score, hits)

    return scores


def _apply_priority_rules(
    scores: dict[int, tuple[float, list[str]]],
    has_poll: bool = False,
    has_gif: bool = False,
    has_sticker: bool = False,
) -> dict[int, tuple[float, list[str]]]:
    """
    Мягкие контекстные правила — без жёсткой иерархии.
    Победитель определяется по соотношению весовых очков.
    Небольшие корректировки только там где нужна подсказка.
    """
    # Опрос — сильный сигнал вовлечения
    if has_poll:
        scores[5] = (scores[5][0] + 8.0, scores[5][1] + ["опрос"])

    # GIF/стикер — сигнал развлекательного
    if has_gif:
        scores[6] = (scores[6][0] + 3.0, scores[6][1] + ["gif"])
    if has_sticker:
        scores[6] = (scores[6][0] + 2.0, scores[6][1] + ["стикер"])

    # Если продающих сигналов намного больше чем образовательных —
    # небольшой буст продающему (гайд с 5 ссылками это продающий)
    sell_score = scores.get(4, (0.0, []))[0]
    edu_score  = scores.get(2, (0.0, []))[0]
    if sell_score > 0 and edu_score > 0 and sell_score >= edu_score * 1.5:
        scores[4] = (scores[4][0] * 1.2, scores[4][1])

    return scores


def classify_by_rules(
    text: str,
    has_poll: bool = False,
    has_gif: bool = False,
    has_sticker: bool = False,
    extra_text: str = "",
) -> TypeResult:
    """Rule-based классификация по расширенным словарям с весами позиций."""

    # Опрос → немедленно вовлекающий
    if has_poll:
        return TypeResult(
            type_code=5, type_name=TYPE_NAMES[5],
            type_confidence=0.97,
            type_reason="Пост содержит опрос — классический вовлекающий формат взаимодействия с аудиторией.",
            type_evidence=["опрос"],
            analysis_basis="rules", llm_used=False, manual_review_required=False,
        )

    # GIF/стикер без текста → развлекательный
    if (has_gif or has_sticker) and not text.strip():
        return TypeResult(
            type_code=6, type_name=TYPE_NAMES[6],
            type_confidence=0.65,
            type_reason="GIF или стикер без подписи — вероятно развлекательный контент без утилитарной ценности.",
            type_evidence=["gif" if has_gif else "стикер"],
            analysis_basis="rules", llm_used=False, manual_review_required=False,
        )

    combined = f"{text} {extra_text}".strip()

    if not combined:
        return TypeResult(
            type_code=None, type_name="Не определено",
            type_confidence=0.0,
            type_reason="Нет текста для анализа — требуется ручная проверка.",
            type_evidence=[],
            analysis_basis="rules", llm_used=False, manual_review_required=True,
        )

    scores = _score_text_weighted(combined)
    scores = _apply_priority_rules(scores, has_poll, has_gif, has_sticker)

    # Находим тип с максимальным весовым счётом
    best_type = max(scores, key=lambda t: (scores[t][0], TYPE_PRIORITY.get(t, 0)))
    best_score, best_evidence = scores[best_type]

    if best_score == 0:
        return TypeResult(
            type_code=None, type_name="Не определено",
            type_confidence=0.0,
            type_reason="Ключевых слов-индикаторов не найдено. Рекомендуется проверка вручную или через LLM.",
            type_evidence=[],
            analysis_basis="rules", llm_used=False, manual_review_required=True,
        )

    total_score = sum(s for s, _ in scores.values())
    confidence = round(best_score / total_score, 2) if total_score > 0 else 0.0

    base_reason = TYPE_REASONS.get(best_type, "")
    if best_evidence:
        reason = f"{base_reason} Ключевые индикаторы: {', '.join(best_evidence[:5])}."
    else:
        reason = base_reason

    basis = "text+ocr" if extra_text else "rules"

    return TypeResult(
        type_code=best_type, type_name=TYPE_NAMES[best_type],
        type_confidence=min(confidence, 0.99),
        type_reason=reason,
        type_evidence=best_evidence[:10],
        analysis_basis=basis, llm_used=False,
        manual_review_required=(confidence < 0.40),
    )


# ---------------------------------------------------------------------------
# Парсер ответа LLM
# ---------------------------------------------------------------------------

def _parse_llm_response(raw: str) -> TypeResult:
    # Шаг 1: убираем markdown обёртки
    import re as _re
    raw = _re.sub(r"```[a-zA-Z]*", "", raw).strip()
    # Шаг 2: убираем мусор типа trick_type= перед {
    raw = _re.sub(r"[a-zA-Z_]+ *= *(?=\{)", "", raw).strip()
    # Шаг 3: извлекаем JSON от { до }
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start:end+1]
    # Шаг 4: исправляем невалидные escape
    chars = []
    i = 0
    while i < len(raw):
        if raw[i] == "\\" and i + 1 < len(raw):
            nxt = raw[i+1]
            if nxt in '"\\/bfnrtu ':
                chars.append(raw[i])
                chars.append(nxt)
                i += 2
            else:
                chars.append(nxt)
                i += 2
        else:
            chars.append(raw[i])
            i += 1
    raw = "".join(chars)
    try:
        data = json.loads(raw)
        code = data.get("type_code")
        if code is not None:
            code = int(code)
        name = data.get("type_name") or (TYPE_NAMES.get(code, "Не определено") if code else "Не определено")
        confidence = float(data.get("type_confidence", 0.5))
        reason = data.get("type_reason", "")
        evidence = data.get("type_evidence", [])
        return TypeResult(
            type_code=code, type_name=name,
            type_confidence=round(min(confidence, 0.99), 2),
            type_reason=reason,
            type_evidence=evidence if isinstance(evidence, list) else [],
            analysis_basis="llm", llm_used=True,
            manual_review_required=(confidence < 0.50 or code is None),
        )
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.debug(f"JSON парсинг не удался ({e}), пробуем извлечь тип из текста")
        return _extract_type_from_text(raw)


def _extract_type_from_text(raw: str) -> TypeResult:
    """Запасной парсер — извлекает тип из текстового ответа Ollama."""
    raw_lower = raw.lower()
    # Нормализуем варианты написания типов от qwen
    name_variants = {
        "продаж": 4, "продаю": 4, "продав": 4, "selling": 4, "sales": 4,
        "вовлек": 5, "engaging": 5,
        "образов": 2, "educational": 2,
        "информ": 1, "informational": 1,
        "анонс": 3, "announcement": 3,
        "развлек": 6, "разлук": 6, "entertainment": 6,
        "имидж": 7, "вдохновл": 7, "brand": 7,
    }
    for substr, code in name_variants.items():
        if substr in raw_lower:
            return TypeResult(
                type_code=code, type_name=TYPE_NAMES[code],
                type_confidence=0.55,
                type_reason=f"Тип определён из текстового ответа модели.",
                type_evidence=[],
                analysis_basis="hybrid(local_ollama)", llm_used=True,
                manual_review_required=False,
            )
    # Ищем упоминание кода типа
    for code, name in TYPE_NAMES.items():
        if str(code) in raw or name.lower() in raw_lower:
            return TypeResult(
                type_code=code, type_name=name,
                type_confidence=0.55,
                type_reason=f"Тип определён из текстового ответа модели: {name}.",
                type_evidence=[],
                analysis_basis="hybrid(local_ollama)", llm_used=True,
                manual_review_required=False,
            )
    return TypeResult(
        type_code=None, type_name="Не определено",
        type_confidence=0.0,
        type_reason="Не удалось извлечь тип из ответа модели.",
        type_evidence=[],
        analysis_basis="llm", llm_used=True, manual_review_required=True,
    )


# ---------------------------------------------------------------------------
# Ollama классификатор
# ---------------------------------------------------------------------------

def _ollama_request(model: str, prompt: str, timeout: int = 60):
    """Отправляет запрос в Ollama и возвращает текст ответа."""
    import urllib.request
    import json as _json
    payload = _json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        "http://localhost:11434/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=timeout)
    result = _json.loads(resp.read())
    return result["message"]["content"].strip()


def _describe_image_with_llava(image_path: str, vision_model: str = "llava:7b") -> str:
    """Описывает изображение через llava — используется только если нет текста."""
    import urllib.request, json as _json, base64
    try:
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        payload = _json.dumps({
            "model": vision_model,
            "messages": [{"role": "user", "content": VISION_PROMPT, "images": [img_b64]}],
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
        logger.warning(f"llava описание изображения: {e}")
        return ""


def _classify_by_ollama(
    text: str,
    format_name: str = "",
    extra_text: str = "",
    image_description: str = "",
    model: str = "qwen2.5:7b",
) -> TypeResult:
    """
    Классификация типа через Ollama.
    Использует qwen2.5:7b для текста (лучше понимает русский).
    image_description передаётся если был описан llava заранее.
    """
    parts = []
    if text:
        parts.append(f"Post text:\n{text}")
    if format_name:
        parts.append(f"Post format: {format_name}")
    if extra_text:
        parts.append(f"Text from media (OCR/STT):\n{extra_text}")
    if image_description:
        parts.append(f"Image description:\n{image_description}")

    if not parts:
        return TypeResult(
            type_code=None, type_name="Не определено",
            type_confidence=0.0,
            type_reason="Нет данных для классификации.",
            type_evidence=[],
            analysis_basis="ollama", llm_used=True, manual_review_required=True,
        )

    full_prompt = SYSTEM_PROMPT + "\n\n" + "\n\n".join(parts)

    try:
        raw = _ollama_request(model, full_prompt)
        parsed = _parse_llm_response(raw)
        if parsed.type_code is None:
            logger.debug(f"Ollama не смогла классифицировать. Ответ: {raw[:150]}")
        parsed.analysis_basis = "hybrid(local_ollama)"
        return parsed
    except Exception as e:
        logger.warning(f"Ollama классификация типа: {e}")
        return TypeResult(
            type_code=None, type_name="Не определено",
            type_confidence=0.0,
            type_reason=f"Ollama недоступна: {e}",
            type_evidence=[],
            analysis_basis="ollama_error", llm_used=True, manual_review_required=True,
        )


# ---------------------------------------------------------------------------
# Anthropic / OpenAI
# ---------------------------------------------------------------------------

_warned_providers: set[str] = set()


def _classify_by_anthropic(
    text: str, format_name: str, extra_text: str,
    image_description: str, model: str, api_key: str,
) -> Optional[TypeResult]:
    try:
        import anthropic
    except ImportError:
        if "anthropic_not_installed" not in _warned_providers:
            logger.warning("Anthropic не установлен: pip install anthropic")
            _warned_providers.add("anthropic_not_installed")
        return None

    parts = []
    if text:        parts.append(f"Текст поста:\n{text}")
    if format_name: parts.append(f"Формат: {format_name}")
    if extra_text:  parts.append(f"Текст из медиа:\n{extra_text}")
    if image_description: parts.append(f"Описание медиа:\n{image_description}")
    if not parts:   return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model or "claude-sonnet-4-20250514",
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "\n\n".join(parts)}],
        )
        raw = response.content[0].text.strip()
        result = _parse_llm_response(raw)
        result.analysis_basis = "hybrid(anthropic)"
        return result
    except Exception as e:
        logger.warning(f"Anthropic API ошибка: {e}")
        return None


def _classify_by_openai(
    text: str, format_name: str, extra_text: str,
    image_description: str, model: str, api_key: str,
) -> Optional[TypeResult]:
    try:
        import openai
    except ImportError:
        if "openai_not_installed" not in _warned_providers:
            logger.warning("OpenAI не установлен: pip install openai")
            _warned_providers.add("openai_not_installed")
        return None

    parts = []
    if text:        parts.append(f"Текст поста:\n{text}")
    if format_name: parts.append(f"Формат: {format_name}")
    if extra_text:  parts.append(f"Текст из медиа:\n{extra_text}")
    if image_description: parts.append(f"Описание медиа:\n{image_description}")
    if not parts:   return None

    try:
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model or "gpt-4o-mini",
            max_tokens=512,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "\n\n".join(parts)},
            ],
        )
        raw = response.choices[0].message.content.strip()
        result = _parse_llm_response(raw)
        result.analysis_basis = "hybrid(openai)"
        return result
    except Exception as e:
        logger.warning(f"OpenAI API ошибка: {e}")
        return None


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------

def classify_type(
    text: str,
    format_name: str = "",
    extra_text: str = "",
    image_description: str = "",
    has_poll: bool = False,
    has_gif: bool = False,
    has_sticker: bool = False,
    mode: str = "hybrid",
    threshold: float = 0.65,
    provider: str = "none",
    model: str = "",
    api_key: str = "",
) -> TypeResult:
    """
    Главная функция классификации типа контента.

    provider: "none" | "ollama" | "anthropic" | "openai"
    mode: "rules" | "llm" | "hybrid"
    """
    # Только rules
    if mode == "rules":
        result = classify_by_rules(text, has_poll, has_gif, has_sticker, extra_text)
        if image_description and result.analysis_basis == "rules":
            result.analysis_basis = "text+local_vision"
        return result

    # provider=none — без LLM
    if provider == "none" or not provider:
        result = classify_by_rules(text, has_poll, has_gif, has_sticker, extra_text)
        if image_description:
            result.analysis_basis = "text+local_vision"
        return result

    # Сначала rules
    rules_result = classify_by_rules(text, has_poll, has_gif, has_sticker, extra_text)

    # В hybrid режиме — если уверенность высокая, LLM не нужен
    if mode == "hybrid" and rules_result.type_confidence >= threshold:
        if image_description:
            rules_result.analysis_basis = "text+local_vision"
        return rules_result

    # Вызываем LLM
    llm_result = None

    if provider == "ollama":
        llm_result = _classify_by_ollama(
            text, format_name, extra_text, image_description,
            model or "llava:7b"
        )
    elif provider == "anthropic":
        if not api_key:
            if "anthropic_no_key" not in _warned_providers:
                logger.warning("provider=anthropic, но API ключ не указан → fallback на rules")
                _warned_providers.add("anthropic_no_key")
            if image_description:
                rules_result.analysis_basis = "text+local_vision"
            return rules_result
        else:
            llm_result = _classify_by_anthropic(
                text, format_name, extra_text, image_description, model, api_key
            )
    elif provider == "openai":
        if not api_key:
            if "openai_no_key" not in _warned_providers:
                logger.warning("provider=openai, но API ключ не указан → fallback на rules")
                _warned_providers.add("openai_no_key")
            return rules_result
        else:
            llm_result = _classify_by_openai(
                text, format_name, extra_text, image_description, model, api_key
            )

    # Если LLM дал результат — возвращаем его
    if llm_result is not None and llm_result.type_code is not None:
        return llm_result

    # Fallback на rules
    rules_result.analysis_basis = "hybrid(rules_fallback)"
    rules_result.manual_review_required = True
    return rules_result
