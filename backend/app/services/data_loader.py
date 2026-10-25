"""Load the case dataset once and normalize bank operations."""

from __future__ import annotations

import csv
import io
import logging
import hashlib
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd

from app.core.config import DATA_DIR

LOGGER = logging.getLogger(__name__)
OPERATION_ALIASES = {
    "company_id": ("company_id", "идентификатор компании", "id компании"),
    "operation_id": ("operation_id", "идентификатор операции", "id операции"),
    "operation_date": ("operation_date", "дата операции", "дата"),
    "amount": ("amount", "сумма"),
    "direction": ("direction", "направление"),
    "counterparty_inn": ("counterparty_inn", "инн контрагента"),
    "counterparty_name": ("counterparty_name", "контрагент"),
    "payment_purpose": ("payment_purpose", "назначение платежа"),
    "balance_eod": ("balance_eod", "остаток на конец дня", "остаток"),
    "event_type": ("event_type", "тип события"),
}
COMPANY_ALIASES = {
    "company_id": ("company_id", "идентификатор компании", "id компании"),
    "name": ("name", "company_name", "название", "наименование"),
    "inn": ("inn", "company_inn", "инн"),
    "legal_form": ("legal_form", "organizational_form", "организационно-правовая форма", "опф"),
    "industry": ("industry", "activity", "вид деятельности", "отрасль"),
    "first_operation_date": ("first_operation_date", "дата первой операции"),
    "last_operation_date": ("last_operation_date", "дата последней операции"),
}
REQUIRED_OPERATIONS = ("company_id", "operation_date", "amount", "direction", "balance_eod")


def _generated_company_inn(company_id: str) -> str:
    match = re.fullmatch(r"C(\d{3})", company_id)
    if match is not None:
        number = int(match.group(1))
        return f"770100{number * 1001 % 10000:04d}"
    suffix = int.from_bytes(hashlib.sha256(company_id.encode("utf-8")).digest()[:4], "big") % 1_000_000
    return f"770{suffix:07d}"


def _column_map(columns: list[object], aliases: dict[str, tuple[str, ...]]) -> dict[str, str]:
    lookup = {str(column).strip().lower().replace("ё", "е"): str(column) for column in columns}
    result = {}
    for target, variants in aliases.items():
        for variant in variants:
            column = lookup.get(variant.lower().replace("ё", "е"))
            if column is not None:
                result[target] = column
                break
    return result


def read_csv(path: Path, dtypes: dict[str, str] | None = None) -> pd.DataFrame:
    """Read CSV files with common Russian encodings and delimiters."""
    resolved = path.resolve()
    stat = resolved.stat()
    dtype_key = tuple(sorted((dtypes or {}).items()))
    return _read_csv_cached(str(resolved), stat.st_mtime_ns, stat.st_size, dtype_key).copy(deep=True)


@lru_cache(maxsize=128)
def _read_csv_cached(
    path: str,
    _modified_ns: int,
    _size: int,
    dtypes: tuple[tuple[str, str], ...],
) -> pd.DataFrame:
    content = Path(path).read_bytes()
    decoded = None
    selected_encoding = None
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            decoded = content.decode(encoding)
            selected_encoding = encoding
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise UnicodeError(f"Не удалось определить кодировку CSV: {path}")

    sample = decoded[:65536]
    try:
        detected_delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        detected_delimiter = None

    delimiters = [detected_delimiter, ";", ",", "\t", None]
    candidates = []
    seen_delimiters = set()
    header_line = next((line for line in sample.splitlines() if line.strip()), "")
    for delimiter in delimiters:
        if delimiter in seen_delimiters:
            continue
        seen_delimiters.add(delimiter)
        try:
            header_columns = next(csv.reader(
                [header_line],
                delimiter=delimiter or ",",
            ))
        except (csv.Error, StopIteration, TypeError):
            continue

        normalized_columns = {
            str(column).strip().lower().replace("ё", "е")
            for column in header_columns
        }
        aliases = COMPANY_ALIASES if Path(path).name == "companies.csv" else OPERATION_ALIASES
        recognized_columns = {
            alias.strip().lower().replace("ё", "е")
            for variants in aliases.values()
            for alias in variants
        }
        score = len(normalized_columns & recognized_columns)
        candidates.append((score, len(header_columns), delimiter))
    if candidates:
        _, _, selected_delimiter = max(candidates, key=lambda candidate: (candidate[0], candidate[1]))
        frame = pd.read_csv(
            io.StringIO(decoded),
            sep=selected_delimiter,
            engine="python",
            dtype="string",
        )
        for column, dtype in dtypes:
            if column in frame.columns:
                frame[column] = frame[column].astype(dtype)
        return frame
    raise ValueError(f"Не удалось прочитать CSV: {path} ({selected_encoding})")


@dataclass
class Dataset:
    companies: pd.DataFrame
    operations: pd.DataFrame
    status: str
    message: str
    errors: list[str]
    daily_flows: dict[str, pd.DataFrame] = field(default_factory=dict)

    def company_operations(self, company_id: str) -> pd.DataFrame:
        if self.operations.empty:
            return self.operations.copy()
        return self.operations.loc[self.operations["company_id"] == str(company_id)].copy()

    def company(self, company_id: str) -> dict | None:
        rows = self.companies.loc[self.companies["company_id"] == str(company_id)]
        return None if rows.empty else rows.iloc[0].to_dict()


def load_dataset(data_dir: Path = DATA_DIR) -> Dataset:
    resolved_dir = data_dir.resolve()
    signature = _dataset_signature(resolved_dir)
    cached = _load_dataset_cached(str(resolved_dir), signature)
    return Dataset(
        cached.companies.copy(deep=True),
        cached.operations.copy(deep=True),
        cached.status,
        cached.message,
        list(cached.errors),
        {company_id: flows.copy(deep=True) for company_id, flows in cached.daily_flows.items()},
    )


def _dataset_signature(data_dir: Path) -> tuple[tuple[str, int, int], ...]:
    companies_path = data_dir / "companies.csv"
    combined_path = data_dir / "all_operations.csv"
    paths = [companies_path, combined_path]
    if not combined_path.is_file():
        paths.extend(sorted((data_dir / "statements").glob("*.csv")))
    signature = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            signature.append((str(path), -1, -1))
        else:
            signature.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(signature)


@lru_cache(maxsize=1)
def _load_dataset_cached(data_dir: str, _signature: tuple[tuple[str, int, int], ...]) -> Dataset:
    return _load_dataset_uncached(Path(data_dir))


def clear_dataset_caches() -> None:
    """Drop normalized CSV and dataset snapshots before an explicit reload."""
    _read_csv_cached.cache_clear()
    _load_dataset_cached.cache_clear()
    _load_operations_file_cached.cache_clear()
    from src.data.loader import _read_statement_file

    _read_statement_file.cache_clear()


def _load_dataset_uncached(data_dir: Path = DATA_DIR) -> Dataset:
    """Load company catalog and either combined OR per-company statements."""
    companies_path = data_dir / "companies.csv"
    combined_path = data_dir / "all_operations.csv"
    statements_dir = data_dir / "statements"
    errors: list[str] = []
    if not companies_path.is_file():
        return Dataset(pd.DataFrame(), pd.DataFrame(), "missing", f"Не найден справочник компаний: {companies_path}", errors)
    try:
        raw_companies = read_csv(companies_path, {"company_id": "string", "inn": "string", "company_inn": "string"})
        company_map = _column_map(list(raw_companies.columns), COMPANY_ALIASES)
        if "company_id" not in company_map:
            raise ValueError("В companies.csv отсутствует company_id.")
        companies = raw_companies.rename(columns={value: key for key, value in company_map.items()})
        companies["company_id"] = companies["company_id"].astype("string").str.strip()
        for column in ("name", "inn", "legal_form", "industry", "first_operation_date", "last_operation_date"):
            if column not in companies:
                companies[column] = ""
        companies["name"] = companies["name"].fillna(companies["company_id"]).astype(str)
        companies["inn"] = companies["inn"].fillna("").astype(str)
        companies["inn"] = companies.apply(
            lambda company: company["inn"].strip()
            if re.fullmatch(r"\d{10}|\d{12}", company["inn"].strip())
            else _generated_company_inn(str(company["company_id"])),
            axis=1,
        )
    except (OSError, UnicodeError, pd.errors.ParserError, ValueError) as error:
        LOGGER.error("Unable to load company catalog from %s (%s)", companies_path, type(error).__name__)
        return Dataset(pd.DataFrame(), pd.DataFrame(), "invalid", f"Ошибка чтения справочника компаний: {error}", [str(error)])

    try:
        if combined_path.is_file():
            operations = _load_operations_file(combined_path)
        elif statements_dir.is_dir():
            frames = []
            for statement_path in sorted(statements_dir.glob("*.csv")):
                try:
                    frames.append(_load_operations_file(statement_path))
                except (OSError, UnicodeError, pd.errors.ParserError, ValueError) as error:
                    errors.append(f"{statement_path.name}: {error}")
            operations = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        else:
            return Dataset(companies, pd.DataFrame(), "incomplete",
                           f"Не найдены all_operations.csv или каталог statements в {data_dir}.", errors)
    except (OSError, UnicodeError, pd.errors.ParserError, ValueError) as error:
        LOGGER.error("Unable to load operations from %s (%s)", data_dir, type(error).__name__)
        return Dataset(companies, pd.DataFrame(), "invalid", f"Ошибка чтения операций: {error}", [*errors, str(error)])

    if operations.empty:
        return Dataset(companies, operations, "incomplete", "Файлы операций пусты или отсутствуют.", errors)
    operations = operations.drop_duplicates(["company_id", "operation_id"], keep="first")
    known_ids = set(companies["company_id"].astype(str))
    operations = operations.loc[operations["company_id"].astype(str).isin(known_ids)].copy()
    companies = companies.drop_duplicates("company_id", keep="first").reset_index(drop=True)
    daily_flows = {
        str(company_id): _daily_flows(company_operations)
        for company_id, company_operations in operations.groupby("company_id", sort=False)
    }
    status = "ready" if len(companies) else "incomplete"
    return Dataset(companies, operations.reset_index(drop=True), status,
                   f"Загружено компаний: {len(companies)}; операций: {len(operations)}.", errors, daily_flows)


def _daily_flows(operations: pd.DataFrame) -> pd.DataFrame:
    if operations.empty:
        return pd.DataFrame(columns=["date", "inflow", "outflow", "net_flow"])
    daily = operations.groupby("date")["amount"].agg(
        inflow=lambda amounts: amounts[amounts > 0].sum(),
        outflow=lambda amounts: -amounts[amounts < 0].sum(),
        net_flow="sum",
    )
    daily = daily.asfreq("D", fill_value=0).fillna(0)
    daily.index.name = "date"
    return daily.reset_index()


def _load_operations_file(path: Path) -> pd.DataFrame:
    resolved = path.resolve()
    stat = resolved.stat()
    return _load_operations_file_cached(str(resolved), stat.st_mtime_ns, stat.st_size).copy(deep=True)


@lru_cache(maxsize=128)
def _load_operations_file_cached(path: str, _modified_ns: int, _size: int) -> pd.DataFrame:
    source_path = Path(path)
    raw = read_csv(source_path, {"company_id": "string", "operation_id": "string", "counterparty_inn": "string"})
    mapped = _column_map(list(raw.columns), OPERATION_ALIASES)
    missing = [field for field in REQUIRED_OPERATIONS if field not in mapped]
    if missing:
        if "company_id" not in mapped and source_path.parent.name == "statements":
            raw["company_id"] = source_path.stem
            mapped["company_id"] = "company_id"
            missing.remove("company_id")
        if missing:
            raise ValueError("Не хватает полей: " + ", ".join(missing))
    operations = raw.rename(columns={value: key for key, value in mapped.items()}).copy()
    if "operation_id" not in operations:
        operations["operation_id"] = [f"{source_path.stem}-{index}" for index in range(len(operations))]
    operations["company_id"] = operations["company_id"].astype("string").str.strip()
    if "operation_id" in operations:
        operations["operation_id"] = operations["operation_id"].astype("string").str.strip()
    else:
        operations["operation_id"] = pd.Series(pd.NA, index=operations.index, dtype="string")
    operations["operation_date"] = pd.to_datetime(operations["operation_date"], errors="coerce")
    operations["amount"] = pd.to_numeric(operations["amount"], errors="coerce").abs()
    direction = operations["direction"].astype("string").str.strip().str.lower()
    incoming = direction.isin(["поступление", "income", "credit", "входящее"])
    outgoing = direction.isin(["списание", "расход", "expense", "debit", "исходящее"])
    operations["signed_amount"] = operations["amount"].where(incoming, -operations["amount"])
    operations["balance_eod"] = pd.to_numeric(operations["balance_eod"], errors="coerce")
    for field in ("counterparty_inn", "counterparty_name", "payment_purpose"):
        if field not in operations:
            operations[field] = ""
        operations[field] = operations[field].fillna("").astype("string").str.strip()
    valid_direction = incoming | outgoing
    operations = operations.loc[valid_direction].copy()
    operations["operation_id"] = operations["operation_id"].fillna("")
    missing_operation_id = operations["operation_id"].eq("")
    operations.loc[missing_operation_id, "operation_id"] = [
        f"{source_path.stem}-{index}" for index in operations.index[missing_operation_id]
    ]
    operations = operations.dropna(subset=["company_id", "operation_date", "amount", "balance_eod"])
    operations = operations.loc[operations["amount"] > 0]
    operations["date"] = operations["operation_date"].dt.normalize()
    operations["account"] = operations["company_id"].astype(str)
    operations["counterparty"] = operations["counterparty_name"].astype(str)
    operations["inn"] = operations["counterparty_inn"].astype(str)
    operations["purpose"] = operations["payment_purpose"].astype(str)
    operations["amount"] = operations["signed_amount"]
    operations["balance"] = operations["balance_eod"]
    operations["direction"] = operations["signed_amount"].gt(0).map({True: "поступление", False: "списание"})
    operations["source_row_id"] = operations["operation_id"].astype(str)
    return operations.reset_index(drop=True)


def validate_daily_balances(operations: pd.DataFrame) -> pd.DataFrame:
    """One EOD balance per date and day opening balances from signed transaction sums."""
    if operations.empty:
        return pd.DataFrame(columns=["company_id", "date", "net_flow", "closing_balance", "opening_balance", "operations"])
    grouped = operations.groupby(["company_id", "date"], as_index=False).agg(
        net_flow=("signed_amount", "sum"),
        closing_balance=("balance_eod", "last"),
        operations=("operation_id", "count"),
    ).sort_values(["company_id", "date"])
    grouped["opening_balance"] = grouped["closing_balance"] - grouped["net_flow"]
    previous_close = grouped.groupby("company_id")["closing_balance"].shift()
    consecutive = grouped.groupby("company_id")["date"].diff().dt.days.eq(1)
    grouped["balance_consistent"] = (~consecutive) | (
        (grouped["closing_balance"] - previous_close - grouped["net_flow"]).abs() < 0.01
    )
    return grouped.reset_index(drop=True)
