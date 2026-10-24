"""Bank statement ingestion with conservative column detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from io import BytesIO, StringIO
import math
from pathlib import Path
from typing import BinaryIO, TextIO

import pandas as pd


ALIASES = {
    "date": ("дата", "дата операции", "дата платежа", "operation date", "date", "дата проведения"),
    "amount": ("сумма", "сумма операции", "сумма платежа", "amount", "сумма в валюте"),
    "direction": ("направление", "тип операции", "вид операции", "operation type", "direction", "тип"),
    "counterparty": ("контрагент", "получатель/плательщик", "получатель", "плательщик", "counterparty"),
    "inn": ("инн", "инн контрагента", "inn"),
    "purpose": ("назначение платежа", "назначение", "описание", "комментарий", "purpose", "детали операции"),
    "balance": ("остаток", "остаток на счете", "остаток на счёте", "баланс", "balance", "остаток на конец дня"),
    "account": ("счет", "счёт", "номер счета", "номер счёта", "account", "счет/карта"),
    "category": ("категория", "категория операции", "category"),
    "status": ("статус", "состояние", "status"),
    "source": ("источник", "source"),
    "description": ("описание события", "описание", "description"),
    "event_type": ("тип события", "event type", "event_type"),
}
REQUIRED = ("date", "amount")
INCOMING_WORDS = ("поступ", "приход", "зачисл", "входящ", "кредит", "income", "credit", "внесение")
OUTGOING_WORDS = ("спис", "расход", "исходящ", "дебет", "оплата", "перечисл", "expense", "debit")


@dataclass
class LoadResult:
    """Normalized statement and a transparent report of rejected records."""

    operations: pd.DataFrame
    rejected: pd.DataFrame
    detected_columns: dict[str, str]
    duplicate_count: int = 0
    warnings: list[str] = field(default_factory=list)


def _norm(value: object) -> str:
    return " ".join(str(value).strip().lower().replace("ё", "е").split())


def detect_columns(columns: list[object]) -> dict[str, str]:
    """Match common Russian/English headings to internal field names."""
    normalized = {_norm(column): str(column) for column in columns}
    result: dict[str, str] = {}
    for canonical, aliases in ALIASES.items():
        for alias in aliases:
            match = normalized.get(_norm(alias))
            if match is not None:
                result[canonical] = match
                break
        if canonical not in result:
            for label, original in normalized.items():
                if any(_norm(alias) in label for alias in aliases if len(_norm(alias)) > 3):
                    result[canonical] = original
                    break
    return result


def read_statement(source: str | bytes | BinaryIO | TextIO, filename: str = "") -> pd.DataFrame:
    """Read CSV or Excel input, inferring CSV delimiter and encoding."""
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if isinstance(source, str):
        path = Path(source)
        try:
            stat = path.stat()
        except (OSError, ValueError):
            pass
        else:
            if path.is_file():
                return _read_statement_file(str(path.resolve()), stat.st_mtime_ns, stat.st_size, suffix).copy(deep=True)
    if suffix in {"xlsx", "xls"}:
        return pd.read_excel(source)
    if isinstance(source, bytes):
        source = BytesIO(source)
    if hasattr(source, "seek"):
        source.seek(0)
    try:
        return pd.read_csv(source, sep=None, engine="python", encoding="utf-8-sig", decimal=",")
    except UnicodeDecodeError:
        if hasattr(source, "seek"):
            source.seek(0)
        return pd.read_csv(source, sep=None, engine="python", encoding="cp1251", decimal=",")


@lru_cache(maxsize=64)
def _read_statement_file(path: str, _modified_ns: int, _size: int, suffix: str) -> pd.DataFrame:
    if suffix in {"xlsx", "xls"}:
        return pd.read_excel(path)
    try:
        return pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig", decimal=",")
    except UnicodeDecodeError:
        return pd.read_csv(path, sep=None, engine="python", encoding="cp1251", decimal=",")


def parse_money(value: object) -> float:
    if pd.isna(value):
        raise ValueError("не указана сумма")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("\u00a0", "").replace(" ", "").replace("₽", "").replace("руб.", "")
    if not text:
        raise ValueError("не указана сумма")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    return float(text)


def _direction(value: object) -> int | None:
    text = _norm(value) if not pd.isna(value) else ""
    if any(word in text for word in INCOMING_WORDS):
        return 1
    if any(word in text for word in OUTGOING_WORDS):
        return -1
    return None


def _parse_date(value: object) -> pd.Timestamp:
    """Parse common Russian dates and ISO dates without day-first ambiguity."""
    text = str(value).strip()
    year_first = len(text) >= 10 and text[0:4].isdigit() and text[4] in "-./"
    return pd.to_datetime(value, dayfirst=not year_first, errors="raise")


def normalize_statement(frame: pd.DataFrame, mapping: dict[str, str] | None = None) -> LoadResult:
    """Normalize records to signed operations; never applies a direction sign twice."""
    columns = detect_columns(list(frame.columns))
    if mapping:
        columns.update({key: value for key, value in mapping.items() if value in frame.columns})
    missing = [key for key in REQUIRED if key not in columns]
    if missing:
        raise ValueError("Не удалось сопоставить обязательные поля: " + ", ".join(missing))

    records: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    source_frame = frame.copy()
    for row_number, (_, raw) in enumerate(source_frame.iterrows(), start=2):
        try:
            date = _parse_date(raw[columns["date"]])
            amount = parse_money(raw[columns["amount"]])
            if not pd.notna(date) or not math.isfinite(amount) or amount == 0:
                raise ValueError("дата не распознана или сумма равна нулю")
            explicit = _direction(raw[columns["direction"]]) if "direction" in columns else None
            signed = (abs(amount) * explicit) if explicit is not None else amount
            records.append({
                "date": pd.Timestamp(date).normalize(),
                "amount": float(signed),
                "direction": "поступление" if signed > 0 else "списание",
                "counterparty": str(raw[columns["counterparty"]]).strip() if "counterparty" in columns and pd.notna(raw[columns["counterparty"]]) else "",
                "inn": str(raw[columns["inn"]]).strip() if "inn" in columns and pd.notna(raw[columns["inn"]]) else "",
                "purpose": str(raw[columns["purpose"]]).strip() if "purpose" in columns and pd.notna(raw[columns["purpose"]]) else "",
                "balance": parse_money(raw[columns["balance"]]) if "balance" in columns and pd.notna(raw[columns["balance"]]) else float("nan"),
                "account": str(raw[columns["account"]]).strip() if "account" in columns and pd.notna(raw[columns["account"]]) else "Основной счёт",
                "category": str(raw[columns["category"]]).strip() if "category" in columns and pd.notna(raw[columns["category"]]) else "",
                "source_row": row_number,
            })
        except (ValueError, TypeError, OverflowError) as error:
            rejected.append({"source_row": row_number, "reason": str(error)})

    operations = pd.DataFrame(records, columns=["date", "amount", "direction", "counterparty", "inn", "purpose", "balance", "account", "category", "source_row"])
    rejected_frame = pd.DataFrame(rejected, columns=["source_row", "reason"])
    duplicate_count = 0
    if not operations.empty:
        duplicate_keys = ["date", "amount", "counterparty", "inn", "purpose", "account"]
        duplicates = operations.duplicated(duplicate_keys, keep="first")
        duplicate_count = int(duplicates.sum())
        if duplicate_count:
            duplicate_rows = operations.loc[duplicates, "source_row"]
            rejected_frame = pd.concat([rejected_frame, pd.DataFrame({
                "source_row": duplicate_rows, "reason": "дубликат операции",
            })], ignore_index=True)
            operations = operations.loc[~duplicates].reset_index(drop=True)
        operations = operations.sort_values(["account", "date", "source_row"]).reset_index(drop=True)
    warnings: list[str] = []
    if operations.empty:
        warnings.append("После проверки не осталось корректных операций.")
    return LoadResult(operations, rejected_frame, columns, duplicate_count, warnings)


def daily_balances(operations: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Recover opening cash from end-of-day balances and validate daily movement."""
    if operations.empty:
        return pd.DataFrame(columns=["date", "account", "net_flow", "closing_balance", "opening_balance"]), []
    daily = operations.groupby(["account", "date"], as_index=False).agg(
        net_flow=("amount", "sum"),
        closing_balance=("balance", "last"),
    ).sort_values(["account", "date"])
    daily["opening_balance"] = daily["closing_balance"] - daily["net_flow"]
    warnings: list[str] = []
    for account, group in daily.groupby("account"):
        group = group.dropna(subset=["closing_balance"])
        previous = None
        for row in group.itertuples():
            if previous is not None and row.date == previous.date + pd.Timedelta(days=1):
                expected = previous.closing_balance + row.net_flow
                if abs(expected - row.closing_balance) > max(1.0, abs(row.closing_balance) * 0.005):
                    warnings.append(f"Остаток счёта «{account}» не сходится на {row.date:%d.%m.%Y}.")
            previous = row
    return daily.reset_index(drop=True), warnings
