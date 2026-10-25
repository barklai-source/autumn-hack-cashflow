"""Company, operation, forecast, risk and future-event routes."""

from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import date
from pathlib import Path, PurePosixPath

import numpy as np
import pandas as pd
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from app.core.auth import (
    DEMO_INN_ORDINALS,
    authenticate_user,
    create_session_token,
    hash_password,
    verify_session_token,
)
from app.schemas.api import (
    AuthResponse, CategoryPatch, DatasetSwitchRequest, EventCreate, EventPatch, LoginRequest,
    RecurringPatch, RegisterRequest,
)
from app.services.categorization import categorize_operations
from app.services.cache import CompanyResultCache
from app.services.data_loader import clear_dataset_caches, load_dataset, validate_daily_balances
from app.services.forecasting import calculate_forecast, category_summary, evaluation_payload
from app.services.recurring import company_recurring
from src.data.loader import detect_columns, parse_money
from src.forecasting.prediction import apply_cash_flow_scenario

router = APIRouter(prefix="/api")
VALID_CATEGORIES = (
    "Выручка и поступления от клиентов", "Закупки и поставщики", "Фонд оплаты труда",
    "Налоги и обязательные платежи", "Аренда", "Маркетинг и реклама",
    "Логистика и транспорт", "Комиссии банка", "Кредиты и проценты", "Лизинг",
    "Оборудование и капитальные расходы", "Переводы между собственными счетами",
    "Прочие поступления", "Прочие расходы", "Требует проверки",
)


def _json_value(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _records(frame: pd.DataFrame) -> list[dict]:
    return [{key: _json_value(value) for key, value in row.items()} for row in frame.to_dict("records")]


def _current_user(request: Request, *, required: bool = False) -> dict[str, object]:
    authorization = request.headers.get("authorization")
    if not authorization:
        if required:
            raise HTTPException(status_code=401, detail="Требуется авторизация.")
        return {"role": "admin", "company_id": None, "display_name": "Администратор"}
    scheme, separator, token = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not separator or not token:
        raise HTTPException(status_code=401, detail="Некорректный токен авторизации.")
    user = verify_session_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Сессия недействительна или истекла.")
    return user


def _authorize_company(request: Request, company_id: str) -> dict[str, object]:
    user = _current_user(request)
    if user["role"] == "company" and user["company_id"] != company_id:
        raise HTTPException(status_code=403, detail="Нет доступа к данным этой компании.")
    return user


def _authorize_admin(request: Request) -> dict[str, object]:
    user = _current_user(request, required=True)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Для этой операции нужны права администратора.")
    return user


def _context(request: Request, company_id: str):
    _authorize_company(request, company_id)
    dataset = request.app.state.dataset
    company = dataset.company(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Компания не найдена в загруженном справочнике.")
    if dataset.operations.empty:
        raise HTTPException(status_code=503, detail="Датасет операций недоступен. Проверьте файлы companies.csv и all_operations.csv.")
    operations = dataset.company_operations(company_id)
    if operations.empty:
        raise HTTPException(status_code=404, detail="Для компании нет доступных операций.")
    return dataset, company, operations, request.app.state.store


def _cached_response(
    request: Request,
    endpoint: str,
    company_id: str,
    horizon: int,
    reserve: float,
    parameters: dict[str, object],
    compute,
):
    return request.app.state.result_cache.get_or_compute(
        company_id,
        horizon,
        reserve,
        {"endpoint": endpoint, "parameters": parameters},
        compute,
    )


def _cached_calculation(
    request: Request,
    company: dict,
    frame: pd.DataFrame,
    store,
    horizon: int,
    reserve: float,
    scenarios: int,
):
    company_id = str(company["company_id"])
    dataset = request.app.state.dataset
    daily_flows = getattr(dataset, "daily_flows", {}).get(company_id)
    return request.app.state.result_cache.get_or_compute(
        company_id,
        horizon,
        reserve,
        {"calculation": "forecast", "scenarios": scenarios},
        lambda: calculate_forecast(
            frame, company, store, horizon, reserve, scenarios, daily_flows=daily_flows,
        ),
    )


def _invalidate_company(request: Request, company_id: str) -> None:
    request.app.state.result_cache.invalidate(company_id)


@router.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest, request: Request):
    user = authenticate_user(
        request.app.state.dataset, payload.username, payload.password, request.app.state.store,
    )
    if user is None:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль.")
    return {"token": create_session_token(user), **user}


def _company_for_inn(request: Request, inn: str) -> dict | None:
    dataset = request.app.state.dataset
    if dataset.companies.empty:
        return None
    matches = dataset.companies.loc[dataset.companies["inn"].astype(str).str.strip() == inn]
    if matches.empty:
        demo_ordinal = DEMO_INN_ORDINALS.get(inn)
        if demo_ordinal is not None and demo_ordinal < len(dataset.companies):
            matches = dataset.companies.sort_values("company_id", kind="stable").iloc[[demo_ordinal]]
    return None if matches.empty else matches.iloc[0].to_dict()


@router.get("/auth/demo-companies")
def demo_companies(request: Request):
    companies = request.app.state.dataset.companies
    if companies.empty:
        return {"items": []}
    selected = companies.sort_values("company_id", kind="stable").head(3)
    return {"items": [
        {
            "company_id": str(row["company_id"]),
            "name": str(row["name"]),
            "inn": str(row["inn"]),
        }
        for row in selected.to_dict("records")
    ]}


@router.get("/auth/lookup-inn")
def lookup_inn(request: Request, inn: str = Query(pattern=r"^\d{10}(\d{2})?$")):
    company = _company_for_inn(request, inn)
    if company is None:
        return {"found": False, "inn": inn, "company_id": None, "name": None, "industry": None}
    return {
        "found": True,
        "inn": inn,
        "company_id": str(company["company_id"]),
        "name": str(company["name"]),
        "industry": str(company.get("industry", "")),
    }


@router.post("/auth/register", response_model=AuthResponse)
def register(payload: RegisterRequest, request: Request):
    store = request.app.state.store
    if store.get_user(payload.inn) is not None:
        raise HTTPException(status_code=409, detail="Пользователь с таким ИНН уже зарегистрирован.")
    company = _company_for_inn(request, payload.inn)
    if company is None:
        companies = request.app.state.dataset.companies
        if companies.empty:
            raise HTTPException(status_code=503, detail="Справочник компаний недоступен.")
        company = companies.sort_values("company_id", kind="stable").iloc[0].to_dict()
    company_id = str(company["company_id"])
    company_name = (payload.company_name or "").strip() or str(company["name"])
    user = {
        "role": "company",
        "company_id": company_id,
        "display_name": company_name,
        "inn": payload.inn,
    }
    try:
        store.create_user({
            "inn": payload.inn,
            "company_id": company_id,
            "company_name": company_name,
            "password": hash_password(payload.password),
            "role": "company",
        })
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="Пользователь с таким ИНН уже зарегистрирован.") from error
    return {"token": create_session_token(user), **user}


@router.get("/auth/me")
def auth_me(request: Request):
    user = _current_user(request, required=True)
    return {key: user.get(key) for key in ("role", "company_id", "display_name", "inn")}


@router.get("/health")
def health(request: Request):
    dataset = request.app.state.dataset
    return {
        "status": dataset.status,
        "data_available": not dataset.operations.empty,
        "companies": len(dataset.companies),
        "operations": len(dataset.operations),
        "data_directory": str(request.app.state.data_directory),
        "message": dataset.message,
        "errors": dataset.errors[:20],
    }


@router.post("/admin/reload-dataset")
def reload_dataset(request: Request):
    _authorize_admin(request)
    result = _activate_dataset(request, Path(request.app.state.data_directory))
    return {
        "status": result["status"],
        "message": result["message"],
        "companies": result["companies"],
        "total": result["companies_count"],
        "errors": request.app.state.dataset.errors,
    }


MAX_DATASET_UPLOAD_BYTES = 500 * 1024 * 1024


def _managed_dataset_root(request: Request) -> Path:
    default_directory = Path(getattr(
        request.app.state,
        "default_data_directory",
        request.app.state.data_directory,
    )).resolve()
    root = Path(getattr(
        request.app.state,
        "dataset_storage_root",
        default_directory.parent / ".managed-datasets",
    )).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _validate_dataset(directory: Path):
    if not (directory / "companies.csv").is_file():
        raise HTTPException(status_code=422, detail="В датасете отсутствует обязательный файл companies.csv.")
    if not (directory / "all_operations.csv").is_file():
        raise HTTPException(status_code=422, detail="В датасете отсутствует обязательный файл all_operations.csv.")
    clear_dataset_caches()
    try:
        candidate = load_dataset(directory)
    except (OSError, UnicodeError, ValueError, pd.errors.ParserError) as error:
        raise HTTPException(status_code=422, detail=f"Не удалось прочитать датасет: {error}") from error
    if candidate.status != "ready" or candidate.companies.empty or candidate.operations.empty:
        detail = "; ".join(candidate.errors) or candidate.message or "CSV не содержит пригодных данных."
        raise HTTPException(status_code=422, detail=f"Структура датасета некорректна: {detail}")
    return candidate


def _activate_dataset(request: Request, directory: Path):
    directory = directory.resolve()
    candidate = _validate_dataset(directory)
    return _publish_dataset(request, directory, candidate)


def _publish_dataset(request: Request, directory: Path, candidate):
    company_ids = candidate.companies["company_id"].astype(str).tolist()
    new_cache = CompanyResultCache(company_ids)
    last_dates = candidate.operations.groupby("company_id")["date"].max()
    for company_id, last_actual_date in last_dates.items():
        request.app.state.store.ensure_diverse_events(str(company_id), last_actual_date.date())
    request.app.state.dataset = candidate
    request.app.state.data_directory = directory.resolve()
    request.app.state.result_cache = new_cache
    return {
        "status": "ok",
        "message": candidate.message,
        "companies_count": len(candidate.companies),
        "operations_count": len(candidate.operations),
        "companies": _records(candidate.companies),
    }


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _dataset_presets(request: Request) -> dict[str, Path]:
    configured = os.getenv("CASHFLOW_DATASET_PRESETS", "")
    presets: dict[str, Path] = {}
    for entry in configured.split(","):
        name, separator, value = entry.partition("=")
        if separator and name.strip() and value.strip():
            presets[name.strip()] = Path(value.strip()).expanduser().resolve()
    default_directory = Path(getattr(
        request.app.state,
        "default_data_directory",
        request.app.state.data_directory,
    )).resolve()
    base = default_directory.parent
    presets.setdefault("default", default_directory)
    for name in ("preloaded_test", "jury", "defense"):
        presets.setdefault(name, (base / name).resolve())
    return presets


@router.post("/admin/dataset/switch")
def switch_dataset(payload: DatasetSwitchRequest, request: Request):
    _authorize_admin(request)
    requested = Path(payload.dataset_name).expanduser()
    presets = _dataset_presets(request)
    if payload.dataset_name in presets:
        directory = presets[payload.dataset_name]
    else:
        directory = requested.resolve()
        allowed_roots = [
            Path(getattr(
                request.app.state,
                "default_data_directory",
                request.app.state.data_directory,
            )).resolve().parent,
            _managed_dataset_root(request),
            *(path.parent for path in presets.values()),
        ]
        if not any(_is_within(directory, root) for root in allowed_roots):
            raise HTTPException(status_code=403, detail="Путь датасета находится вне разрешённых директорий.")
    if not directory.is_dir():
        raise HTTPException(status_code=404, detail=f"Директория датасета не найдена: {directory}")
    return _activate_dataset(request, directory)


async def _save_upload(upload: UploadFile, destination: Path) -> int:
    size = 0
    with destination.open("wb") as output:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_DATASET_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="Размер загрузки превышает лимит 500 МБ.")
            output.write(chunk)
    return size


def _extract_dataset_zip(archive_path: Path, destination: Path) -> None:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            selected: dict[str, zipfile.ZipInfo] = {}
            for member in archive.infolist():
                relative = PurePosixPath(member.filename)
                if relative.is_absolute() or ".." in relative.parts:
                    raise HTTPException(status_code=422, detail="ZIP содержит небезопасный путь.")
                if member.file_size > MAX_DATASET_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Файл внутри ZIP превышает лимит 500 МБ.")
                if member.filename.endswith("/") or member.is_dir():
                    continue
                name = relative.name
                if name in {"companies.csv", "all_operations.csv"}:
                    if name in selected:
                        raise HTTPException(status_code=422, detail=f"В ZIP найдено несколько файлов {name}.")
                    selected[name] = member
            required = {"companies.csv", "all_operations.csv"}
            missing = required - selected.keys()
            if missing:
                raise HTTPException(
                    status_code=422,
                    detail="В ZIP отсутствуют файлы: " + ", ".join(sorted(missing)),
                )
            total_size = sum(member.file_size for member in selected.values())
            if total_size > MAX_DATASET_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="Распакованный датасет превышает лимит 500 МБ.")
            for name, member in selected.items():
                with archive.open(member) as source, (destination / name).open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
    except zipfile.BadZipFile as error:
        raise HTTPException(status_code=422, detail="Загруженный ZIP-архив повреждён.") from error
    except (NotImplementedError, RuntimeError) as error:
        raise HTTPException(status_code=422, detail="ZIP использует неподдерживаемое или зашифрованное сжатие.") from error


@router.post("/admin/dataset/upload")
async def upload_dataset(
    request: Request,
    file: UploadFile | None = File(default=None),
    companies_file: UploadFile | None = File(default=None),
    all_operations_file: UploadFile | None = File(default=None),
):
    _authorize_admin(request)
    archive_upload = file
    if archive_upload is not None and archive_upload.filename and not archive_upload.filename.lower().endswith(".zip"):
        if companies_file is None and all_operations_file is None:
            companies_file, all_operations_file = archive_upload, None
            archive_upload = None
    if archive_upload is not None and (companies_file is not None or all_operations_file is not None):
        raise HTTPException(status_code=422, detail="Загрузите ZIP или пару CSV, не оба варианта сразу.")
    if archive_upload is None and (companies_file is None or all_operations_file is None):
        raise HTTPException(status_code=422, detail="Загрузите ZIP либо оба файла companies.csv и all_operations.csv.")

    managed_root = _managed_dataset_root(request)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=managed_root))
    final_directory = managed_root / f"dataset-{uuid.uuid4().hex}"
    try:
        if archive_upload is not None:
            archive_path = staging / "upload.zip"
            await _save_upload(archive_upload, archive_path)
            _extract_dataset_zip(archive_path, staging)
            archive_path.unlink()
        else:
            if companies_file is None or all_operations_file is None:
                raise HTTPException(status_code=422, detail="Необходимо передать оба CSV-файла.")
            if Path(companies_file.filename or "").name.casefold() != "companies.csv":
                raise HTTPException(status_code=422, detail="Первый CSV-файл должен называться companies.csv.")
            if Path(all_operations_file.filename or "").name.casefold() != "all_operations.csv":
                raise HTTPException(status_code=422, detail="Второй CSV-файл должен называться all_operations.csv.")
            await _save_upload(companies_file, staging / "companies.csv")
            await _save_upload(all_operations_file, staging / "all_operations.csv")
        candidate = _validate_dataset(staging)
        staging.rename(final_directory)
        return _publish_dataset(request, final_directory, candidate)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        if final_directory.exists() and request.app.state.data_directory != final_directory:
            shutil.rmtree(final_directory)
        raise


@router.get("/companies")
def companies(
    request: Request,
    search: str | None = None,
    industry: str | None = None,
    legal_form: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    frame = request.app.state.dataset.companies.copy()
    user = _current_user(request)
    if user["role"] == "company":
        frame = frame.loc[frame["company_id"].astype(str) == user["company_id"]]
    if not frame.empty:
        if search:
            query = search.casefold()
            mask = frame["company_id"].astype(str).str.casefold().str.contains(query, regex=False)
            mask |= frame["name"].astype(str).str.casefold().str.contains(query, regex=False)
            mask |= frame["inn"].astype(str).str.casefold().str.contains(query, regex=False)
            frame = frame.loc[mask]
        if industry:
            frame = frame.loc[frame["industry"].astype(str).str.contains(industry, case=False, regex=False)]
        if legal_form:
            frame = frame.loc[frame["legal_form"].astype(str).str.contains(legal_form, case=False, regex=False)]
    total = len(frame)
    result = frame.iloc[(page - 1) * page_size:page * page_size]
    return {"items": _records(result), "total": total, "page": page, "page_size": page_size}


@router.get("/companies/overview")
def companies_overview(request: Request):
    user = _current_user(request)
    cache_company_id = str(user["company_id"]) if user["role"] == "company" else "__all__"
    return _cached_response(
        request, "overview", cache_company_id, 0, 0, {},
        lambda: _companies_overview_payload(request, user),
    )


def _companies_overview_payload(request: Request, user: dict[str, object]):
    dataset = request.app.state.dataset
    companies_frame = dataset.companies.copy()
    operations = dataset.operations.copy()
    if user["role"] == "company":
        company_id = user["company_id"]
        companies_frame = companies_frame.loc[companies_frame["company_id"].astype(str) == company_id]
        operations = operations.loc[operations["company_id"].astype(str) == company_id]
    if companies_frame.empty:
        return {"companies": 0, "operations": 0, "rows": []}
    rows = []
    latest_by_company = {}
    operation_counts = operations.groupby("company_id").size().to_dict() if not operations.empty else {}
    if not operations.empty:
        latest_days = operations.groupby("company_id")["date"].max()
        for company_id, last_date in latest_days.items():
            last_rows = operations.loc[(operations["company_id"] == company_id) & (operations["date"] == last_date)]
            last = last_rows.iloc[-1]
            latest_by_company[str(company_id)] = {"date": last_date, "balance": last["balance_eod"]}
    for company in companies_frame.to_dict("records"):
        company_id = str(company["company_id"])
        last = latest_by_company.get(company_id)
        rows.append({
            **{key: _json_value(value) for key, value in company.items()},
            "operation_count": int(operation_counts.get(company_id, 0)),
            "last_balance": None if last is None else _json_value(last["balance"]),
            "balance_date": None if last is None else _json_value(last["date"]),
        })
    return {"companies": len(rows), "operations": len(operations), "rows": rows}


@router.get("/companies/{company_id}")
def company_detail(company_id: str, request: Request):
    _authorize_company(request, company_id)
    dataset = request.app.state.dataset
    company = dataset.company(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Компания не найдена.")
    result = {key: _json_value(value) for key, value in company.items()}
    result["operation_count"] = int(dataset.operations.groupby("company_id").size().get(company_id, 0)) if not dataset.operations.empty else 0
    return result


@router.get("/companies/{company_id}/operations")
def operations(
    company_id: str,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    start_date: date | None = None,
    end_date: date | None = None,
    category: str | None = None,
    direction: str | None = Query(default=None, pattern="^(поступление|списание)$"),
    counterparty: str | None = None,
    search: str | None = None,
    sort: str = Query(default="operation_date"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
):
    _, _, frame, store = _context(request, company_id)
    categorized = categorize_operations(frame, store)
    needs_review_count = int(categorized["needs_review"].fillna(False).astype(bool).sum())
    if start_date:
        categorized = categorized.loc[categorized["date"] >= pd.Timestamp(start_date)]
    if end_date:
        categorized = categorized.loc[categorized["date"] <= pd.Timestamp(end_date)]
    if direction:
        categorized = categorized.loc[categorized["direction"] == direction]
    if counterparty:
        categorized = categorized.loc[categorized["counterparty_name"].str.contains(counterparty, case=False, regex=False, na=False)]
    if search:
        categorized = categorized.loc[
            categorized["counterparty_name"].str.contains(search, case=False, regex=False, na=False) |
            categorized["payment_purpose"].str.contains(search, case=False, regex=False, na=False)
        ]
    if category:
        categorized = categorized.loc[categorized["category"] == category]
    allowed_sort = {"operation_date", "amount", "counterparty_name", "operation_id", "category"}
    if sort not in allowed_sort:
        raise HTTPException(status_code=422, detail=f"Сортировка по {sort!r} не поддерживается.")
    total = len(categorized)
    ordered = categorized.sort_values(sort, ascending=order == "asc", kind="stable")
    columns = ["operation_id", "company_id", "operation_date", "amount", "signed_amount", "direction",
               "counterparty_inn", "counterparty_name", "payment_purpose", "balance_eod", "category",
               "category_method", "confidence", "needs_review"]
    page_frame = ordered.iloc[(page - 1) * page_size:page * page_size][columns]
    return {"items": _records(page_frame), "total": total, "page": page, "page_size": page_size,
            "needs_review_count": needs_review_count}


@router.get("/companies/{company_id}/summary")
def summary(
    company_id: str,
    request: Request,
    horizon: int = Query(default=90, json_schema_extra={"enum": [30, 60, 90]}),
    reserve: float = Query(default=0, ge=0),
):
    if horizon not in (30, 60, 90):
        raise HTTPException(status_code=422, detail="Горизонт прогноза должен быть 30, 60 или 90 дней.")
    _authorize_company(request, company_id)

    def build():
        _, company, frame, store = _context(request, company_id)
        needs_review_count = int(categorize_operations(frame, store)["needs_review"].fillna(False).astype(bool).sum())
        forecast, details, risk = _cached_calculation(request, company, frame, store, horizon, reserve, 1000)
        balances = validate_daily_balances(frame)
        last = balances.iloc[-1]
        return {
            "company_id": company_id,
            "last_actual_date": _json_value(pd.Timestamp(frame["date"].max()).date()),
            "last_balance": _json_value(last["closing_balance"]),
            "balance_date": _json_value(last["date"]),
            "balance_is_current": bool(pd.Timestamp(last["date"]).normalize() >= pd.Timestamp.today().normalize()),
            "forecast_balance_7": _json_value(forecast.iloc[min(6, len(forecast) - 1)]["balance"]),
            "forecast_balance_30": _json_value(forecast.iloc[min(29, len(forecast) - 1)]["balance"]),
            "forecast_balance_90": _json_value(forecast.iloc[-1]["balance"]),
            "forecast_inflows": _json_value(forecast["inflow"].sum()),
            "forecast_outflows": _json_value(forecast["outflow"].sum()),
            "upcoming_obligations": int(sum(
                event["status"] in ("Ожидается", "Подтверждено")
                and event["direction"] == "списание"
                and pd.Timestamp(event["event_date"]) >= pd.Timestamp(forecast["date"].min())
                and pd.Timestamp(event["event_date"]) <= pd.Timestamp(forecast["date"].max())
                for event in store.list_events(company_id)
            )),
            "first_risk_date": _json_value(risk["first_breach"]),
            "max_deficit": _json_value(risk["max_deficit"]),
            "risk_level": risk["risk_level"],
            "risk_probability": risk["probability"],
            "selected_model": details["selected_method"],
            "history_days": int((frame["date"].max() - frame["date"].min()).days + 1),
            "observed_days": int(frame["date"].nunique()),
            "unobserved_calendar_days": int(max(0, (frame["date"].max() - frame["date"].min()).days + 1 - frame["date"].nunique())),
            "balance_consistency_errors": int((~balances["balance_consistent"]).sum()),
            "needs_review_count": needs_review_count,
        }

    return _cached_response(
        request,
        "summary",
        company_id,
        horizon,
        reserve,
        {"as_of": pd.Timestamp.today().normalize().date().isoformat()},
        build,
    )


@router.get("/companies/{company_id}/categories")
def categories(company_id: str, request: Request, start_date: date | None = None, end_date: date | None = None):
    _, _, frame, store = _context(request, company_id)
    summary_rows = category_summary(frame, store, start_date, end_date)
    monthly = categorize_operations(frame, store)
    monthly["month"] = monthly["date"].dt.to_period("M").astype(str)
    monthly["flow_amount"] = monthly["signed_amount"].abs()
    trends = monthly.groupby(["month", "direction", "category"], as_index=False)["flow_amount"].sum()
    normalized_summary = {
        direction: _records(pd.DataFrame(rows)) if rows else []
        for direction, rows in summary_rows.items()
    }
    return {"by_direction": normalized_summary, "monthly": _records(trends)}


@router.get("/companies/{company_id}/recurring")
def recurring(company_id: str, request: Request):
    _, _, frame, store = _context(request, company_id)
    rows = company_recurring(categorize_operations(frame, store), store)
    return {"items": _records(rows)}


@router.get("/companies/{company_id}/forecast")
def forecast(
    company_id: str,
    request: Request,
    horizon: int = Query(default=90, json_schema_extra={"enum": [30, 60, 90]}),
    reserve: float = Query(default=0, ge=0),
    scenarios: int = Query(default=1000, ge=100, le=10000),
    inflow_change_pct: float = Query(default=0, ge=-80, le=200),
    outflow_change_pct: float = Query(default=0, ge=-80, le=200),
    daily_net_adjustment: float = Query(default=0, ge=-500000, le=500000),
    delay_days: int = Query(default=0, ge=0, le=30),
    shock_amount: float = Query(default=0, ge=-1000000000, le=1000000000),
    shock_date: date | None = None,
):
    if horizon not in (30, 60, 90):
        raise HTTPException(status_code=422, detail="Горизонт прогноза должен быть 30, 60 или 90 дней.")
    _authorize_company(request, company_id)

    def build():
        _, company, frame, store = _context(request, company_id)
        result, details, risk = _cached_calculation(
            request, company, frame, store, horizon, reserve, scenarios,
        )
        if shock_amount and shock_date is None:
            raise HTTPException(status_code=422, detail="Для разового платежа укажите дату.")
        if shock_amount and shock_date is not None:
            forecast_dates = pd.to_datetime(result["date"]).dt.date
            if shock_date not in set(forecast_dates):
                raise HTTPException(status_code=422, detail="Дата разового платежа должна входить в горизонт прогноза.")
        current_balance = details["current_balance"]
        baseline_result = result
        scenario_result = apply_cash_flow_scenario(
            baseline_result,
            current_balance,
            inflow_change_pct=inflow_change_pct,
            outflow_change_pct=outflow_change_pct,
            daily_net_adjustment=daily_net_adjustment,
            delay_days=delay_days,
            shock_amount=shock_amount,
            shock_date=shock_date,
        )
        daily_history = frame.groupby("date", as_index=False).agg(
            balance=("balance_eod", "last"),
            inflow=("signed_amount", lambda values: values[values > 0].sum()),
            outflow=("signed_amount", lambda values: -values[values < 0].sum()),
        )
        return {
            "company_id": company_id, "horizon": horizon,
            "balance_date": _json_value(frame.loc[frame["balance"].notna(), "date"].max() if frame["balance"].notna().any() else None),
            "balance_source": details["balance_source"],
            "method": details["forecast_method"], "selected_model": details["selected_method"],
            "items": _records(scenario_result),
            "total_inflow": float(scenario_result["inflow"].sum()),
            "total_outflow": float(scenario_result["outflow"].sum()),
            "total_net_flow": float(scenario_result["net_flow"].sum()),
            "baseline_total_net_flow": float(baseline_result["baseline_net_flow"].sum()),
            "history": _records(daily_history),
            "uncertainty_note": "Дни без операций не доказывают нулевой поток; прогноз помечен как неопределённый, когда в истории есть календарные пробелы.",
            "risk": {key: _json_value(value) for key, value in risk.items() if key not in {"warning", "influencing_events"}},
            "warning": _records(pd.DataFrame([risk["warning"]]))[0] if risk.get("warning") else None,
            "influencing_events": risk.get("influencing_events", []),
        }

    return _cached_response(
        request,
        "forecast",
        company_id,
        horizon,
        reserve,
        {
            "scenarios": scenarios,
            "inflow_change_pct": inflow_change_pct,
            "outflow_change_pct": outflow_change_pct,
            "daily_net_adjustment": daily_net_adjustment,
            "delay_days": delay_days,
            "shock_amount": shock_amount,
            "shock_date": shock_date.isoformat() if shock_date else None,
        },
        build,
    )


@router.get("/companies/{company_id}/risks")
def risks(
    company_id: str,
    request: Request,
    horizon: int = Query(default=90, json_schema_extra={"enum": [30, 60, 90]}),
    reserve: float = Query(default=0, ge=0),
):
    if horizon not in (30, 60, 90):
        raise HTTPException(status_code=422, detail="Горизонт прогноза должен быть 30, 60 или 90 дней.")
    _authorize_company(request, company_id)

    def build():
        _, company, frame, store = _context(request, company_id)
        _, _, risk = _cached_calculation(request, company, frame, store, horizon, reserve, 1000)
        risk_payload = {
            key: _json_value(value)
            for key, value in risk.items()
            if key not in {"warning", "influencing_events"}
        }
        warning = _records(pd.DataFrame([risk["warning"]]))[0] if risk.get("warning") else None
        influencing_events = risk.get("influencing_events", [])
        return {
            "risk": risk_payload,
            "warning": warning,
            "influencing_events": influencing_events,
            "method": risk_payload["method"],
            "horizon_days": horizon,
        }

    return _cached_response(request, "risk", company_id, horizon, reserve, {}, build)


@router.get("/companies/{company_id}/model-evaluation")
def model_evaluation(company_id: str, request: Request):
    _authorize_company(request, company_id)

    def build():
        _, company, frame, store = _context(request, company_id)
        return evaluation_payload(
            _cached_calculation(request, company, frame, store, 90, 0, 1000)[1],
        )

    return _cached_response(
        request,
        "quality",
        company_id,
        90,
        0,
        {},
        build,
    )


@router.get("/companies/{company_id}/events")
def events(company_id: str, request: Request, include_cancelled: bool = False):
    _context(request, company_id)
    return {"items": [_json_event(event) for event in request.app.state.store.list_events(company_id, include_cancelled)]}


@router.post("/companies/{company_id}/events/reset-demo")
def reset_demo_events(company_id: str, request: Request):
    _, _, frame, store = _context(request, company_id)
    last_actual_date = pd.Timestamp(frame["date"].max()).date()
    items = store.reset_demo_events(company_id, last_actual_date)
    _invalidate_company(request, company_id)
    return {"items": [_json_event(event) for event in items]}


def _json_event(event: dict) -> dict:
    item = dict(event)
    item["event_date"] = item.pop("event_date")
    item["date"] = item["event_date"]
    item["direction"] = item["direction"]
    return {key: _json_value(value) for key, value in item.items()}


@router.post("/companies/{company_id}/events", status_code=201)
def create_event(company_id: str, payload: EventCreate, request: Request):
    _context(request, company_id)
    created = request.app.state.store.create_event(company_id, payload.model_dump())
    _invalidate_company(request, company_id)
    return _json_event(created)


@router.patch("/companies/{company_id}/events/{event_id}")
def update_event(company_id: str, event_id: int, payload: EventPatch, request: Request):
    _context(request, company_id)
    updated = request.app.state.store.update_event(company_id, event_id, payload.model_dump(exclude_unset=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="Будущее событие не найдено.")
    _invalidate_company(request, company_id)
    return _json_event(updated)


@router.delete("/companies/{company_id}/events/{event_id}")
def cancel_event(company_id: str, event_id: int, request: Request):
    _context(request, company_id)
    updated = request.app.state.store.cancel_event(company_id, event_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Будущее событие не найдено.")
    _invalidate_company(request, company_id)
    return _json_event(updated)


@router.post("/companies/{company_id}/events/import")
async def import_events(company_id: str, request: Request, file: UploadFile = File(...)):
    _context(request, company_id)
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=415, detail="Импорт событий поддерживает CSV.")
    try:
        raw = pd.read_csv(io.BytesIO(await file.read()), sep=None, engine="python", encoding="utf-8-sig")
        columns = detect_columns(list(raw.columns))
        required = [field for field in ("date", "amount", "direction") if field not in columns]
        if required:
            raise ValueError("Нужны столбцы даты, суммы и направления.")
        created = []
        for row in raw.to_dict("records"):
            date_value = pd.to_datetime(row[columns["date"]], dayfirst=True, errors="raise").date()
            amount = abs(parse_money(row[columns["amount"]]))
            if abs(amount - 1234) < 0.000001:
                continue
            direction_text = str(row[columns["direction"]]).strip().lower()
            if direction_text in ("поступление", "income", "credit"):
                direction = "поступление"
            elif direction_text in ("списание", "расход", "expense", "debit"):
                direction = "списание"
            else:
                raise ValueError(f"Неизвестное направление: {direction_text}")
            record = {
                "date": date_value, "amount": amount, "direction": direction,
                "category": str(row.get(columns.get("category", ""), "Прочие расходы")),
                "event_type": str(row.get(columns.get("event_type", ""), "импортированное событие")),
                "description": str(row.get(columns.get("description", ""), "")),
                "source": file.filename, "status": "Ожидается",
            }
            from app.schemas.api import EventCreate
            created.append(request.app.state.store.create_event(company_id, EventCreate(**record).model_dump()))
        created_ids = {item["id"] for item in created}
        removed = request.app.state.store.cleanup_events(company_id)
        imported = [
            event for event in request.app.state.store.list_events(company_id)
            if event["id"] in created_ids
        ]
        if imported or removed:
            _invalidate_company(request, company_id)
        return {"imported": len(imported), "items": [_json_event(item) for item in imported]}
    except (ValueError, TypeError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as error:
        raise HTTPException(status_code=422, detail=f"Не удалось импортировать события: {error}") from error


@router.patch("/companies/{company_id}/operations/{operation_id}/category")
def change_category(company_id: str, operation_id: str, payload: CategoryPatch, request: Request):
    _, _, frame, store = _context(request, company_id)
    if operation_id not in set(frame["operation_id"].astype(str)):
        raise HTTPException(status_code=404, detail="Операция не найдена.")
    if payload.category not in VALID_CATEGORIES:
        raise HTTPException(status_code=422, detail="Недопустимая категория.")
    store.set_category(company_id, operation_id, payload.category)
    _invalidate_company(request, company_id)
    return {"company_id": company_id, "operation_id": operation_id, "category": payload.category, "saved": True}


@router.patch("/companies/{company_id}/recurring/{recurring_id}")
def update_recurring(company_id: str, recurring_id: str, payload: RecurringPatch, request: Request):
    _, _, frame, store = _context(request, company_id)
    items = company_recurring(categorize_operations(frame, store), store)
    if items.empty or recurring_id not in set(items["recurring_id"]):
        raise HTTPException(status_code=404, detail="Регулярная серия не найдена.")
    store.set_recurring(company_id, recurring_id, payload.confirmed)
    _invalidate_company(request, company_id)
    return {"company_id": company_id, "recurring_id": recurring_id, "confirmed": payload.confirmed}
