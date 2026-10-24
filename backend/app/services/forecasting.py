"""Forecast services that reuse the audited forecasting/business modules."""

import numpy as np
import pandas as pd

from app.core.storage import SQLiteStore
from app.services.categorization import categorize_operations
from app.services.recurring import company_recurring
from src.forecasting.prediction import build_forecast
from src.risk.assessment import assess_risk


def _event_frame(events: list[dict]) -> pd.DataFrame:
    if not events:
        return pd.DataFrame(columns=["date", "amount", "direction", "category", "status", "source", "description", "account"])
    result = pd.DataFrame(events).rename(columns={"event_date": "date"})
    result["date"] = pd.to_datetime(result["date"])
    result["amount"] = result.apply(lambda row: row["amount"] if row["direction"] == "поступление" else -row["amount"], axis=1)
    result["status"] = result["status"].map({
        "Ожидается": "ожидается", "Подтверждено": "подтверждено",
        "Исполнено": "исполнено", "Отменено": "отменено",
    })
    result["account"] = result["company_id"].astype(str)
    return result


def calculate_forecast(
    operations: pd.DataFrame,
    company: dict,
    store: SQLiteStore,
    horizon: int = 90,
    reserve: float = 0,
    scenarios: int = 1000,
    start_date: pd.Timestamp | None = None,
    daily_flows: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict, dict]:
    """Calculate forecast, historical validation and deterministic/scenario risk."""
    company_id = str(company["company_id"])
    categorized = categorize_operations(operations, store)
    events = _event_frame(store.list_events(company_id, include_cancelled=False))
    recurring = company_recurring(categorized, store)
    forecast, details = build_forecast(
        categorized, horizon_days=horizon, events=events, recurring=recurring, account=company_id,
        start_date=start_date or pd.Timestamp(categorized["date"].max()),
        daily_flows=daily_flows,
    )
    observed_days = set(pd.to_datetime(categorized["date"]).dt.normalize())
    calendar_days = pd.date_range(categorized["date"].min(), categorized["date"].max(), freq="D")
    history_has_gaps = len(observed_days) < len(calendar_days)
    forecast["uncertain"] = history_has_gaps
    forecast["uncertainty_reason"] = (
        "В выписке нет строк для всех календарных дней истории."
        if history_has_gaps else ""
    )
    selected_name = str(details["selected_method"]).split(" ")[0]
    backtest = details["backtest"]
    residuals = np.array([], dtype=float)
    if not backtest.empty:
        chosen = backtest.loc[backtest["method"] == selected_name]
        residuals = (chosen["actual_net"] - chosen["predicted_net"]).to_numpy(dtype=float)
    risk = assess_risk(
        forecast, reserve=reserve, residuals=residuals, scenarios=scenarios,
        events=events.loc[events["account"].eq(company_id)] if not events.empty else events,
        historical_net_flows=categorized.groupby("date")["signed_amount"].sum().to_numpy(dtype=float),
    )
    return forecast, details, risk


def category_summary(operations: pd.DataFrame, store: SQLiteStore, start=None, end=None) -> dict:
    """Summarize categorized inflows/outflows over an optional date range."""
    categorized = categorize_operations(operations, store)
    if start:
        categorized = categorized.loc[categorized["date"] >= pd.Timestamp(start)]
    if end:
        categorized = categorized.loc[categorized["date"] <= pd.Timestamp(end)]
    output = {}
    for direction, mask in (("поступление", categorized["signed_amount"] > 0), ("списание", categorized["signed_amount"] < 0)):
        part = categorized.loc[mask].copy()
        if part.empty:
            output[direction] = []
            continue
        part["value"] = part["signed_amount"].abs()
        rows = part.groupby("category", as_index=False).agg(amount=("value", "sum"), operations=("operation_id", "count"))
        total = float(rows["amount"].sum())
        rows["share"] = rows["amount"] / total if total else 0.0
        output[direction] = rows.sort_values("amount", ascending=False).to_dict("records")
    return output


def evaluation_payload(details: dict) -> dict:
    """Return metrics and bounded historical prediction rows for charting."""
    metrics = details["metrics"]
    predictions = details["backtest"]
    horizons = details["balance_horizons"]
    if predictions.empty:
        backtest = []
    else:
        backtest_frame = predictions.pivot_table(index="date", columns="method", values="predicted_net", aggfunc="mean").reset_index()
        actuals = predictions.groupby("date", as_index=False)["actual_net"].mean()
        backtest_frame = actuals.merge(backtest_frame, on="date", how="left").tail(500)
        backtest = backtest_frame.replace({np.nan: None}).to_dict("records")
    return {
        "selected_method": details["selected_method"],
        "forecast_method": details["forecast_method"],
        "metrics": metrics.replace({np.nan: None}).to_dict("records") if not metrics.empty else [],
        "balance_horizons": horizons.replace({np.nan: None}).to_dict("records") if not horizons.empty else [],
        "backtest": backtest,
    }
