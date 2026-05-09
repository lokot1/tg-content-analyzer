"""
analytics.py — аналитика частот форматов, типов, комбинаций.
Строит все сводные таблицы для report_builder.py.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Вспомогательные структуры
# ---------------------------------------------------------------------------

@dataclass
class ComboStats:
    combo_code: str
    combo_name: str
    format_code: Optional[int]
    format_name: str
    type_code: Optional[int]
    type_name: str
    count: int
    percent: float


@dataclass
class SegmentComparison:
    combo_code: str
    combo_name: str
    fashion_count: int
    fashion_percent: float
    beauty_count: int
    beauty_percent: float
    difference_pp: float          # fashion_percent - beauty_percent
    intersection_status: str      # "both_segments" | "fashion_only" | "beauty_only"


# ---------------------------------------------------------------------------
# Главный класс аналитики
# ---------------------------------------------------------------------------

class Analytics:
    """
    Принимает список постов и строит все аналитические таблицы.
    Каждый пост — словарь с полями format_code, type_code, segment и т.д.
    """

    def __init__(self, posts: list[dict]):
        self.posts = posts
        self.total = len(posts)

        self.fashion_posts = [p for p in posts if p.get("segment") == "fashion"]
        self.beauty_posts  = [p for p in posts if p.get("segment") == "beauty"]

        self.total_fashion = len(self.fashion_posts)
        self.total_beauty  = len(self.beauty_posts)

    # ------------------------------------------------------------------
    # Утилиты
    # ------------------------------------------------------------------

    @staticmethod
    def _pct(count: int, total: int) -> float:
        if total == 0:
            return 0.0
        return round(count / total * 100, 2)

    @staticmethod
    def _combo_code(format_code, type_code) -> str:
        fc = str(format_code) if format_code is not None else "?"
        tc = str(type_code)   if type_code   is not None else "?"
        return f"{fc}.{tc}"

    @staticmethod
    def _combo_name(format_name: str, type_name: str) -> str:
        return f"{format_name} + {type_name}"

    # ------------------------------------------------------------------
    # Статистика форматов
    # ------------------------------------------------------------------

    def format_stats(self, posts: list[dict] | None = None) -> list[dict]:
        """Частоты форматов для списка постов."""
        if posts is None:
            posts = self.posts
        total = len(posts)
        counter = Counter(p.get("format_code") for p in posts)
        rows = []
        for code, count in sorted(counter.items(), key=lambda x: -x[1]):
            rows.append({
                "format_code": code,
                "format_name": posts[0].get("format_name", "") if posts else "",
                "count": count,
                "percent_total": self._pct(count, total),
            })
        # Добавляем format_name из постов
        code_to_name = {p.get("format_code"): p.get("format_name", "") for p in posts}
        for row in rows:
            row["format_name"] = code_to_name.get(row["format_code"], "")
        return rows

    def format_stats_total(self) -> list[dict]:
        return self.format_stats(self.posts)

    def format_stats_by_segment(self) -> list[dict]:
        rows = []
        for segment, seg_posts, seg_name in [
            ("fashion", self.fashion_posts, "Мода"),
            ("beauty",  self.beauty_posts,  "Красота"),
        ]:
            total = len(seg_posts)
            counter = Counter(p.get("format_code") for p in seg_posts)
            code_to_name = {p.get("format_code"): p.get("format_name", "") for p in seg_posts}
            for code, count in sorted(counter.items(), key=lambda x: -x[1]):
                rows.append({
                    "segment": segment,
                    "segment_name": seg_name,
                    "format_code": code,
                    "format_name": code_to_name.get(code, ""),
                    "count": count,
                    "percent_within_segment": self._pct(count, total),
                })
        return rows

    # ------------------------------------------------------------------
    # Статистика типов
    # ------------------------------------------------------------------

    def type_stats(self, posts: list[dict] | None = None) -> list[dict]:
        if posts is None:
            posts = self.posts
        total = len(posts)
        counter = Counter(p.get("type_code") for p in posts)
        code_to_name = {p.get("type_code"): p.get("type_name", "") for p in posts}
        rows = []
        for code, count in sorted(counter.items(), key=lambda x: -x[1]):
            rows.append({
                "type_code": code,
                "type_name": code_to_name.get(code, ""),
                "count": count,
                "percent_total": self._pct(count, total),
            })
        return rows

    def type_stats_total(self) -> list[dict]:
        return self.type_stats(self.posts)

    def type_stats_by_segment(self) -> list[dict]:
        rows = []
        for segment, seg_posts, seg_name in [
            ("fashion", self.fashion_posts, "Мода"),
            ("beauty",  self.beauty_posts,  "Красота"),
        ]:
            total = len(seg_posts)
            counter = Counter(p.get("type_code") for p in seg_posts)
            code_to_name = {p.get("type_code"): p.get("type_name", "") for p in seg_posts}
            for code, count in sorted(counter.items(), key=lambda x: -x[1]):
                rows.append({
                    "segment": segment,
                    "segment_name": seg_name,
                    "type_code": code,
                    "type_name": code_to_name.get(code, ""),
                    "count": count,
                    "percent_within_segment": self._pct(count, total),
                })
        return rows

    # ------------------------------------------------------------------
    # Статистика комбинаций
    # ------------------------------------------------------------------

    def _combo_rows(self, posts: list[dict], total: int, segment: str = "", seg_name: str = "") -> list[dict]:
        counter: Counter = Counter()
        meta: dict = {}
        for p in posts:
            cc = self._combo_code(p.get("format_code"), p.get("type_code"))
            cn = self._combo_name(p.get("format_name", ""), p.get("type_name", ""))
            counter[cc] += 1
            meta[cc] = {
                "combo_name": cn,
                "format_code": p.get("format_code"),
                "format_name": p.get("format_name", ""),
                "type_code": p.get("type_code"),
                "type_name": p.get("type_name", ""),
            }
        rows = []
        for cc, count in sorted(counter.items(), key=lambda x: -x[1]):
            row = {
                "combo_code": cc,
                "combo_name": meta[cc]["combo_name"],
                "format_code": meta[cc]["format_code"],
                "format_name": meta[cc]["format_name"],
                "type_code": meta[cc]["type_code"],
                "type_name": meta[cc]["type_name"],
                "count": count,
            }
            if segment:
                row["segment"] = segment
                row["segment_name"] = seg_name
                row["percent_within_segment"] = self._pct(count, total)
            else:
                row["percent_total"] = self._pct(count, total)
            rows.append(row)
        return rows

    def combo_stats_total(self) -> list[dict]:
        return self._combo_rows(self.posts, self.total)

    def combo_stats_by_segment(self) -> list[dict]:
        rows = []
        for segment, seg_posts, seg_name in [
            ("fashion", self.fashion_posts, "Мода"),
            ("beauty",  self.beauty_posts,  "Красота"),
        ]:
            rows.extend(self._combo_rows(seg_posts, len(seg_posts), segment, seg_name))
        return rows

    # ------------------------------------------------------------------
    # Сводные таблицы (pivot)
    # ------------------------------------------------------------------

    def _pivot(self, posts: list[dict]) -> dict:
        """
        Строит сводную таблицу форматы × типы.
        Возвращает:
          {
            "formats": [sorted format codes],
            "types":   [sorted type codes],
            "counts":  {format_code: {type_code: count}},
            "format_names": {code: name},
            "type_names":   {code: name},
          }
        """
        counts: dict = defaultdict(lambda: defaultdict(int))
        format_names: dict = {}
        type_names: dict = {}
        for p in posts:
            fc = p.get("format_code")
            tc = p.get("type_code")
            counts[fc][tc] += 1
            format_names[fc] = p.get("format_name", str(fc))
            type_names[tc]   = p.get("type_name",   str(tc))

        return {
            "formats": sorted(counts.keys(), key=lambda x: (x is None, x)),
            "types":   sorted(type_names.keys(), key=lambda x: (x is None, x)),
            "counts":  dict(counts),
            "format_names": format_names,
            "type_names":   type_names,
            "total": len(posts),
        }

    def pivot_total(self)   -> dict: return self._pivot(self.posts)
    def pivot_fashion(self) -> dict: return self._pivot(self.fashion_posts)
    def pivot_beauty(self)  -> dict: return self._pivot(self.beauty_posts)

    # ------------------------------------------------------------------
    # Сравнение сегментов
    # ------------------------------------------------------------------

    def segment_comparison(self) -> list[dict]:
        """Сравнение комбинаций между модой и красотой."""
        fashion_counter: Counter = Counter()
        beauty_counter:  Counter = Counter()
        meta: dict = {}

        for p in self.fashion_posts:
            cc = self._combo_code(p.get("format_code"), p.get("type_code"))
            fashion_counter[cc] += 1
            meta[cc] = self._combo_name(p.get("format_name", ""), p.get("type_name", ""))

        for p in self.beauty_posts:
            cc = self._combo_code(p.get("format_code"), p.get("type_code"))
            beauty_counter[cc] += 1
            meta[cc] = self._combo_name(p.get("format_name", ""), p.get("type_name", ""))

        all_combos = set(fashion_counter) | set(beauty_counter)
        rows = []
        for cc in sorted(all_combos):
            fc = fashion_counter.get(cc, 0)
            bc = beauty_counter.get(cc, 0)
            fp = self._pct(fc, self.total_fashion)
            bp = self._pct(bc, self.total_beauty)
            diff = round(fp - bp, 2)

            if fc > 0 and bc > 0:
                status = "both_segments"
            elif fc > 0:
                status = "fashion_only"
            else:
                status = "beauty_only"

            rows.append({
                "combo_code": cc,
                "combo_name": meta.get(cc, ""),
                "fashion_count": fc,
                "fashion_percent": fp,
                "beauty_count": bc,
                "beauty_percent": bp,
                "difference_percent_points": diff,
                "intersection_status": status,
            })

        rows.sort(key=lambda r: -abs(r["difference_percent_points"]))
        return rows

    # ------------------------------------------------------------------
    # Устойчивые и редкие комбинации
    # ------------------------------------------------------------------

    def stable_combinations(self, top_n: int = 5) -> list[dict]:
        """Топ-N комбинаций по частоте внутри каждого сегмента."""
        rows = []
        for segment, seg_posts, seg_name in [
            ("fashion", self.fashion_posts, "Мода"),
            ("beauty",  self.beauty_posts,  "Красота"),
        ]:
            total = len(seg_posts)
            combo_rows = self._combo_rows(seg_posts, total, segment, seg_name)
            for rank, row in enumerate(combo_rows[:top_n], start=1):
                rows.append({
                    "segment": segment,
                    "segment_name": seg_name,
                    "combo_code": row["combo_code"],
                    "combo_name": row["combo_name"],
                    "count": row["count"],
                    "percent_within_segment": row["percent_within_segment"],
                    "rank_within_segment": rank,
                })
        return rows

    def rare_combinations(self, bottom_n: int = 5) -> list[dict]:
        """Нижние-N комбинаций (встречаются редко / 1 раз)."""
        rows = []
        for segment, seg_posts, seg_name in [
            ("fashion", self.fashion_posts, "Мода"),
            ("beauty",  self.beauty_posts,  "Красота"),
        ]:
            total = len(seg_posts)
            combo_rows = self._combo_rows(seg_posts, total, segment, seg_name)
            bottom = combo_rows[-bottom_n:] if len(combo_rows) > bottom_n else combo_rows
            bottom = list(reversed(bottom))  # от самой редкой
            for rank, row in enumerate(bottom, start=1):
                rows.append({
                    "segment": segment,
                    "segment_name": seg_name,
                    "combo_code": row["combo_code"],
                    "combo_name": row["combo_name"],
                    "count": row["count"],
                    "percent_within_segment": row["percent_within_segment"],
                    "rank_from_bottom": rank,
                })
        return rows

    # ------------------------------------------------------------------
    # Автоматические текстовые выводы
    # ------------------------------------------------------------------

    def summary_text(self, meta: dict | None = None) -> list[dict]:
        """
        Генерирует нейтральные исследовательские выводы.
        Возвращает список строк {label, value}.
        """
        rows = []

        def _top(lst, key):
            if not lst:
                return "нет данных"
            return lst[0].get(key, "нет данных")

        fmt_total  = self.format_stats_total()
        type_total = self.type_stats_total()
        combo_total= self.combo_stats_total()

        fmt_fashion  = self.format_stats(self.fashion_posts)
        type_fashion = self.type_stats(self.fashion_posts)
        combo_fashion= self._combo_rows(self.fashion_posts, self.total_fashion)

        fmt_beauty  = self.format_stats(self.beauty_posts)
        type_beauty = self.type_stats(self.beauty_posts)
        combo_beauty= self._combo_rows(self.beauty_posts, self.total_beauty)

        comparison  = self.segment_comparison()
        both        = [r for r in comparison if r["intersection_status"] == "both_segments"]
        fashion_only= [r for r in comparison if r["intersection_status"] == "fashion_only"]
        beauty_only = [r for r in comparison if r["intersection_status"] == "beauty_only"]

        rows += [
            {"Показатель": "Самый частый формат в целом",
             "Значение": f"{_top(fmt_total, 'format_name')} (n={_top(fmt_total, 'count')}, {_top(fmt_total, 'percent_total')}%)"},
            {"Показатель": "Самый частый тип в целом",
             "Значение": f"{_top(type_total, 'type_name')} (n={_top(type_total, 'count')}, {_top(type_total, 'percent_total')}%)"},
            {"Показатель": "Самая частая комбинация в целом",
             "Значение": f"{_top(combo_total, 'combo_name')} [{_top(combo_total, 'combo_code')}] (n={_top(combo_total, 'count')}, {_top(combo_total, 'percent_total')}%)"},

            {"Показатель": "Самый частый формат в сегменте «Мода»",
             "Значение": f"{_top(fmt_fashion, 'format_name')} (n={_top(fmt_fashion, 'count')})"},
            {"Показатель": "Самый частый тип в сегменте «Мода»",
             "Значение": f"{_top(type_fashion, 'type_name')} (n={_top(type_fashion, 'count')})"},
            {"Показатель": "Самая частая комбинация в сегменте «Мода»",
             "Значение": f"{_top(combo_fashion, 'combo_name')} [{_top(combo_fashion, 'combo_code')}]"},

            {"Показатель": "Самый частый формат в сегменте «Красота»",
             "Значение": f"{_top(fmt_beauty, 'format_name')} (n={_top(fmt_beauty, 'count')})"},
            {"Показатель": "Самый частый тип в сегменте «Красота»",
             "Значение": f"{_top(type_beauty, 'type_name')} (n={_top(type_beauty, 'count')})"},
            {"Показатель": "Самая частая комбинация в сегменте «Красота»",
             "Значение": f"{_top(combo_beauty, 'combo_name')} [{_top(combo_beauty, 'combo_code')}]"},

            {"Показатель": "Комбинации, встречающиеся в обоих сегментах",
             "Значение": ", ".join(r["combo_code"] for r in both) or "нет"},
            {"Показатель": "Комбинации, характерные только для сегмента «Мода»",
             "Значение": ", ".join(r["combo_code"] for r in fashion_only) or "нет"},
            {"Показатель": "Комбинации, характерные только для сегмента «Красота»",
             "Значение": ", ".join(r["combo_code"] for r in beauty_only) or "нет"},
        ]

        # Методические параметры
        if meta:
            rows.append({"Показатель": "──── Параметры анализа ────", "Значение": ""})
            for k, v in meta.items():
                rows.append({"Показатель": k, "Значение": str(v)})

        return rows
