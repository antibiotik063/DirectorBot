from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime

from app.google_sheets import GoogleSheetsService

logger = logging.getLogger(__name__)


def _normalize_text(value: object) -> str:
    text = str(value or "").strip().replace("ё", "е").replace("Ё", "Е")
    text = re.sub(r"\s+", " ", text)
    return text.casefold()


def _normalize_compact(value: object) -> str:
    return _normalize_text(value).replace(":", "")


def _parse_number(value: object) -> float | None:
    text = str(value or "").strip().replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _format_number(value: object) -> str:
    number = _parse_number(value)
    if number is None:
        return "не найдено"
    if number.is_integer():
        return f"{int(number):,}".replace(",", " ") + " ₽"
    return f"{number:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def _format_date(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "не найдено"
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).strftime("%d.%m.%Y")
        except ValueError:
            continue
    return text


def _format_plain_value(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "не найдено"

    number = _parse_number(text)
    if number is not None:
        if number.is_integer():
            return f"{int(number)}"
        return f"{number}".replace(".", ",")
    return text


@dataclass(slots=True)
class ReportData:
    text: str


class SheetGrid:
    def __init__(self, values: list[list[str]]) -> None:
        self.values = values
        self.row_count = len(values)
        self.col_count = max((len(row) for row in values), default=0)

    def cell(self, row: int, col: int) -> str:
        if row < 0 or col < 0:
            return ""
        if row >= self.row_count:
            return ""
        current_row = self.values[row]
        if col >= len(current_row):
            return ""
        return str(current_row[col]).strip()

    def find_label(
        self,
        labels: str | list[str],
        *,
        row_range: tuple[int, int] | None = None,
        col_range: tuple[int, int] | None = None,
    ) -> tuple[int, int] | None:
        aliases = [_normalize_compact(label) for label in ([labels] if isinstance(labels, str) else labels)]
        row_start, row_end = row_range or (0, self.row_count)
        col_start, col_end = col_range or (0, self.col_count)

        for row in range(max(row_start, 0), min(row_end, self.row_count)):
            for col in range(max(col_start, 0), min(col_end, self.col_count)):
                if _normalize_compact(self.cell(row, col)) in aliases:
                    return row, col
        return None

    def find_all_labels(
        self,
        labels: str | list[str],
        *,
        row_range: tuple[int, int] | None = None,
        col_range: tuple[int, int] | None = None,
    ) -> list[tuple[int, int]]:
        aliases = [_normalize_compact(label) for label in ([labels] if isinstance(labels, str) else labels)]
        row_start, row_end = row_range or (0, self.row_count)
        col_start, col_end = col_range or (0, self.col_count)
        results: list[tuple[int, int]] = []

        for row in range(max(row_start, 0), min(row_end, self.row_count)):
            for col in range(max(col_start, 0), min(col_end, self.col_count)):
                if _normalize_compact(self.cell(row, col)) in aliases:
                    results.append((row, col))
        return results

    def find_value_near_label(self, label: str, *, numeric_only: bool = False) -> str | None:
        location = self.find_label(label)
        if not location:
            logger.warning("Не найдена подпись '%s'", label)
            return None

        row, col = location
        max_right_offset = 2 if numeric_only else 4
        for offset in range(1, max_right_offset + 1):
            value = self.cell(row, col + offset)
            if value and (not numeric_only or _parse_number(value) is not None):
                return value

        for row_offset in range(1, 4):
            for col_offset in range(0, 3):
                value = self.cell(row + row_offset, col + col_offset)
                if (
                    value
                    and _normalize_compact(value) != _normalize_compact(label)
                    and (not numeric_only or _parse_number(value) is not None)
                ):
                    return value

        logger.warning("Не найдено значение рядом с подписью '%s'", label)
        return None

    def find_value_in_block(
        self,
        block_labels: list[str],
        field_label: str,
        *,
        max_rows: int = 8,
        numeric_only: bool = False,
    ) -> str | None:
        block_positions = self.find_all_labels(block_labels)
        if not block_positions:
            logger.warning("Не найден блок '%s'", "/".join(block_labels))
            return None

        field_alias = _normalize_compact(field_label)

        for block_row, block_col in block_positions:
            for row in range(block_row + 1, min(block_row + max_rows + 1, self.row_count)):
                for col in range(max(0, block_col - 1), min(self.col_count, block_col + 3)):
                    if _normalize_compact(self.cell(row, col)) != field_alias:
                        continue
                    for value_col in range(col + 1, min(col + 5, self.col_count)):
                        value = self.cell(row, value_col)
                        if value and (not numeric_only or _parse_number(value) is not None):
                            return value

        logger.warning("Не найдено поле '%s' в блоке '%s'", field_label, "/".join(block_labels))
        return None

    def get_bar_sales(self) -> list[tuple[str, str]]:
        header = self.find_label("Товар")
        if not header:
            logger.warning("Не найден блок продаж бара с заголовком 'Товар'")
            return []

        header_row, item_col = header
        cash_col = item_col + 1
        card_col = item_col + 2

        sales: list[tuple[str, str]] = []
        empty_rows = 0

        for row in range(header_row + 1, self.row_count):
            item_name = self.cell(row, item_col)
            cash_value = self.cell(row, cash_col)
            card_value = self.cell(row, card_col)

            if not item_name and not cash_value and not card_value:
                empty_rows += 1
                if empty_rows >= 2 and sales:
                    break
                continue

            empty_rows = 0
            if not item_name:
                continue

            amount = (_parse_number(cash_value) or 0.0) + (_parse_number(card_value) or 0.0)
            if amount <= 0:
                logger.info("Пропускаю товар '%s' без суммы продажи", item_name)
                continue
            sales.append((item_name, _format_number(amount)))

        if not sales:
            logger.warning("Список продаж бара не найден или пуст")
        return sales


class ReportService:
    def __init__(self, sheets: GoogleSheetsService) -> None:
        self.sheets = sheets

    def build_report(self) -> ReportData:
        grid = SheetGrid(self.sheets.get_report_values())

        date_value = _format_date(grid.find_value_near_label("Дата"))
        admin_value = grid.find_value_near_label("Админ") or "не найдено"
        shift_value = grid.find_value_near_label("Смена") or "не найдено"
        people_value = _format_plain_value(grid.find_value_near_label("Количество людей", numeric_only=True))

        profit = self._build_money_block(grid, ["Прибыль за смену"])
        pc_rental = self._build_money_block(grid, ["Аренда ПК", "Аренда Пк"], include_bonus=True)
        food = self._build_money_block(grid, ["Еда и напитки", "Еда и Напитки"])
        ps5 = self._build_money_block(grid, ["PS5", "PlayStation 5"])
        hookah = self._build_money_block(grid, ["Кальян"])

        bar_sales = grid.get_bar_sales()
        bar_sales_text = "\n".join(f"{name} — {amount}" for name, amount in bar_sales) if bar_sales else "не найдено"

        report = (
            "🎮 Отчёт клуба\n\n"
            f"📅 Дата: {date_value}\n"
            f"👤 Админ: {admin_value}\n"
            f"☀️ Смена: {shift_value}\n\n"
            f"👥 Количество людей: {people_value}\n\n"
            "💰 Прибыль за смену:\n"
            f"Наличные: {profit['cash']}\n"
            f"Безнал: {profit['card']}\n"
            f"Итого: {profit['total']}\n\n"
            "🖥 Аренда ПК:\n"
            f"Наличные: {pc_rental['cash']}\n"
            f"Безнал: {pc_rental['card']}\n"
            f"Итого: {pc_rental['total']}\n"
            f"Бонусы: {pc_rental['bonus']}\n\n"
            "🍔 Еда и напитки:\n"
            f"Наличные: {food['cash']}\n"
            f"Безнал: {food['card']}\n"
            f"Итого: {food['total']}\n\n"
            "🎮 PS5:\n"
            f"Наличные: {ps5['cash']}\n"
            f"Безнал: {ps5['card']}\n"
            f"Итого: {ps5['total']}\n\n"
            "💨 Кальян:\n"
            f"Наличные: {hookah['cash']}\n"
            f"Безнал: {hookah['card']}\n"
            f"Итого: {hookah['total']}\n\n"
            "📦 Продажи бара:\n"
            f"{bar_sales_text}\n\n"
            '⚠️ Данные взяты из существующего листа "Кибер 2.0". Таблица не изменялась.'
        )

        logger.info("Отчёт по листу 'Кибер 2.0' сформирован")
        return ReportData(text=report)

    def _build_money_block(self, grid: SheetGrid, block_labels: list[str], *, include_bonus: bool = False) -> dict[str, str]:
        values = {
            "cash": _format_number(grid.find_value_in_block(block_labels, "Нал:", numeric_only=True)),
            "card": _format_number(grid.find_value_in_block(block_labels, "Б/Н:", numeric_only=True)),
            "total": _format_number(grid.find_value_in_block(block_labels, "Итого:", numeric_only=True)),
        }
        if include_bonus:
            values["bonus"] = _format_number(grid.find_value_in_block(block_labels, "Бонусы:", numeric_only=True))
        return values
