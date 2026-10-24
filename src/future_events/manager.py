"""Validation and de-duplication of events and recurring forecasts."""

import pandas as pd

from src.data.validation import FutureEventInput
from src.data.loader import detect_columns, parse_money


EVENT_COLUMNS = ["date", "amount", "direction", "category", "event_type", "status", "source", "description", "account"]


def _parse_event_date(value):
    text = str(value).strip()
    year_first = len(text) >= 10 and text[0:4].isdigit() and text[4] in "-./"
    return pd.to_datetime(value, dayfirst=not year_first).date()


def validate_events(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate imported future events and return standardized signed amounts."""
    mapped = detect_columns(list(frame.columns))
    missing = [key for key in ("date", "amount", "direction") if key not in mapped]
    if missing:
        raise ValueError("В файле событий отсутствуют поля: " + ", ".join(missing))
    normalized = []
    for record in frame.to_dict("records"):
        normalized_record = {
            "date": record[mapped["date"]],
            "amount": record[mapped["amount"]],
            "direction": record[mapped["direction"]],
            "category": record.get(mapped.get("category", ""), "Прочее") if mapped.get("category") else "Прочее",
            "event_type": record.get("event_type", "пользовательское событие"),
            "status": record.get(mapped.get("status", ""), "ожидается") if mapped.get("status") else "ожидается",
            "source": record.get(mapped.get("source", ""), "импорт") if mapped.get("source") else "импорт",
            "description": record.get(mapped.get("description", ""), "") if mapped.get("description") else "",
            "account": record.get(mapped.get("account", ""), "Основной счёт") if mapped.get("account") else "Основной счёт",
        }
        event = FutureEventInput(**{
            "date": _parse_event_date(normalized_record["date"]),
            "amount": abs(parse_money(normalized_record["amount"])),
            "direction": str(normalized_record["direction"]).strip().lower(),
            "category": str(normalized_record["category"]),
            "event_type": str(normalized_record["event_type"]),
            "status": str(normalized_record["status"]).lower(),
            "source": str(normalized_record["source"]),
            "description": str(normalized_record["description"]),
            "account": str(normalized_record["account"]),
        })
        item = event.model_dump()
        item["date"] = pd.Timestamp(item["date"])
        item["amount"] *= 1 if event.direction == "поступление" else -1
        normalized.append(item)
    return pd.DataFrame(normalized, columns=EVENT_COLUMNS)


def merge_future_flows(
    start_date: pd.Timestamp,
    horizon_days: int,
    events: pd.DataFrame | None = None,
    recurring: pd.DataFrame | None = None,
    account: str | None = None,
) -> pd.DataFrame:
    """Combine explicit and confirmed recurring events without duplicate flows."""
    dates = pd.date_range(start_date + pd.Timedelta(days=1), periods=horizon_days, freq="D")
    result = pd.DataFrame({
        "date": dates,
        "event_flow": 0.0,
        "event_inflow": 0.0,
        "event_outflow": 0.0,
        "event_count": 0,
    })
    accepted_events = pd.DataFrame(columns=EVENT_COLUMNS) if events is None else events.copy()
    if not accepted_events.empty:
        accepted_events = accepted_events.loc[accepted_events["status"].isin(["ожидается", "подтверждено"])]
        if account:
            accepted_events = accepted_events.loc[accepted_events["account"] == account]
    covered = set()
    for row in accepted_events.to_dict("records"):
        date = pd.Timestamp(row["date"]).normalize()
        if date in set(dates):
            key = (date, round(float(row["amount"]), 2), str(row.get("account", "")))
            covered.add(key)
            mask = result["date"].eq(date)
            result.loc[mask, "event_flow"] += float(row["amount"])
            result.loc[mask, "event_inflow"] += max(float(row["amount"]), 0.0)
            result.loc[mask, "event_outflow"] += max(-float(row["amount"]), 0.0)
            result.loc[mask, "event_count"] += 1
    if recurring is not None and not recurring.empty:
        scheduled = set()
        for row in recurring.to_dict("records"):
            if not bool(row.get("confirmed", False)) or not bool(row.get("accepted", True)):
                continue
            if account and row.get("account") and row.get("account") != account:
                continue
            interval = {"ежедневно": 1, "еженедельно": 7, "ежемесячно": 30, "ежеквартально": 91}[row["frequency"]]
            next_date = pd.Timestamp(row["next_date"]).normalize()
            while next_date <= dates[-1]:
                key = (next_date, round(float(row["amount"]), 2), str(row.get("account", "")))
                if next_date in set(dates) and key not in covered and key not in scheduled:
                    mask = result["date"].eq(next_date)
                    result.loc[mask, "event_flow"] += float(row["amount"])
                    result.loc[mask, "event_inflow"] += max(float(row["amount"]), 0.0)
                    result.loc[mask, "event_outflow"] += max(-float(row["amount"]), 0.0)
                    result.loc[mask, "event_count"] += 1
                    scheduled.add(key)
                next_date += pd.Timedelta(days=interval)
    return result
