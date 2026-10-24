"""Build a complete balance forecast from history and explicit future events."""

import pandas as pd
import numpy as np

from src.forecasting.evaluation import evaluate_balance_horizons, walk_forward_evaluation
from src.forecasting.models import forecast_flows


def build_forecast(
    operations: pd.DataFrame,
    horizon_days: int = 90,
    starting_balance: float | None = None,
    events: pd.DataFrame | None = None,
    recurring: pd.DataFrame | None = None,
    account: str | None = None,
    method: str = "auto",
    start_date: pd.Timestamp | None = None,
    daily_flows: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Produce dated projections and preserve known events as a separate layer."""
    from src.data.preprocessing import aggregate_daily
    from src.future_events.manager import merge_future_flows

    history_ops = operations if account is None else operations.loc[operations["account"] == account]
    daily = daily_flows.copy(deep=True) if daily_flows is not None else aggregate_daily(history_ops)
    if daily.empty:
        raise ValueError("Нет операций для выбранного счёта.")
    forecast_start = pd.Timestamp(start_date or daily["date"].max()).normalize()
    backtest, metrics = walk_forward_evaluation(daily, horizon=7, max_origins=1)
    selected_method = "baseline"
    if not metrics.empty and {"ML", "baseline"}.issubset(set(metrics["method"])):
        score = metrics.set_index("method")["MAE"]
        selected_method = "ML" if score["ML"] < score["baseline"] else "baseline"
    forecast_method = selected_method if method == "auto" else method
    forecast = forecast_flows(daily, horizon_days, method=forecast_method, start_date=forecast_start)
    used_method = forecast.attrs.get("method", forecast_method)
    last_date = forecast_start
    event_flows = merge_future_flows(last_date, horizon_days, events, recurring, account)
    forecast = forecast.merge(event_flows, on="date", how="left")
    forecast["event_flow"] = forecast["event_flow"].fillna(0.0)
    forecast["event_inflow"] = forecast["event_inflow"].fillna(0.0)
    forecast["event_outflow"] = forecast["event_outflow"].fillna(0.0)
    forecast["event_count"] = forecast["event_count"].fillna(0).astype(int)
    forecast["baseline_inflow"] = forecast["inflow"] + forecast["event_inflow"]
    forecast["baseline_outflow"] = forecast["outflow"] + forecast["event_outflow"]
    forecast["baseline_net_flow"] = forecast["baseline_inflow"] - forecast["baseline_outflow"]
    forecast["baseline_balance"] = np.nan
    forecast["inflow"] = forecast["baseline_inflow"]
    forecast["outflow"] = forecast["baseline_outflow"]
    forecast["net_flow"] = forecast["baseline_net_flow"]
    forecast["forecast_net"] = forecast["baseline_net_flow"]

    balance_series = history_ops.loc[history_ops["balance"].notna()].sort_values("date")
    closing = balance_series.groupby("date")["balance"].last()
    if not closing.empty:
        current_balance = float(closing.iloc[-1])
        balance_source = "остаток из выписки"
    elif starting_balance is not None:
        current_balance = float(starting_balance)
        balance_source = "введён пользователем"
    else:
        current_balance = None
        balance_source = "неизвестен"
    if current_balance is not None:
        forecast["baseline_balance"] = current_balance + forecast["baseline_net_flow"].cumsum()
        forecast["balance"] = forecast["baseline_balance"]
        validation_errors = pd.Series(dtype=float)
        if not backtest.empty:
            validation_errors = (
                backtest.loc[backtest["method"] == selected_method, "actual_net"] -
                backtest.loc[backtest["method"] == selected_method, "predicted_net"]
            )
        if len(validation_errors) >= 14:
            errors = validation_errors.to_numpy(dtype=float)
            median_error = float(np.median(errors))
            spread = float(1.4826 * np.median(np.abs(errors - median_error)))
            expansion = 1.96 * spread * (forecast.index.to_series().add(1).pow(0.5).to_numpy())
            forecast["lower"] = forecast["balance"] - expansion
            forecast["upper"] = forecast["balance"] + expansion
        else:
            forecast["lower"] = float("nan")
            forecast["upper"] = float("nan")
    else:
        forecast["balance"] = float("nan")
        forecast["lower"] = float("nan")
        forecast["upper"] = float("nan")

    return forecast, {
        "daily": daily,
        "current_balance": current_balance,
        "balance_source": balance_source,
        "metrics": metrics,
        "balance_horizons": evaluate_balance_horizons(daily, seven_day_metrics=metrics),
        "backtest": backtest,
        "selected_method": selected_method,
        "forecast_method": used_method,
    }


def apply_cash_flow_scenario(
    forecast: pd.DataFrame,
    current_balance: float | None,
    *,
    inflow_change_pct: float = 0.0,
    outflow_change_pct: float = 0.0,
    daily_net_adjustment: float = 0.0,
    delay_days: int = 0,
    shock_amount: float = 0.0,
    shock_date: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Apply adjustable assumptions while preserving baseline and exact event amounts."""
    result = forecast.copy(deep=True)
    baseline_inflow = result["baseline_inflow"].to_numpy(dtype=float)
    baseline_outflow = result["baseline_outflow"].to_numpy(dtype=float)
    event_inflow = result["event_inflow"].to_numpy(dtype=float)
    event_outflow = result["event_outflow"].to_numpy(dtype=float)
    model_inflow = np.maximum(0.0, baseline_inflow - event_inflow)
    model_outflow = np.maximum(0.0, baseline_outflow - event_outflow)

    adjusted_model_inflow = model_inflow * (1 + inflow_change_pct / 100)
    adjusted_model_outflow = model_outflow * (1 + outflow_change_pct / 100)
    inflow = event_inflow.copy()
    outflow = event_outflow.copy()
    if delay_days:
        inflow = np.pad(inflow, (delay_days, 0))[:len(inflow)]
        adjusted_model_inflow = np.pad(adjusted_model_inflow, (delay_days, 0))[:len(adjusted_model_inflow)]
    inflow += adjusted_model_inflow
    outflow += adjusted_model_outflow
    net_flow = inflow - outflow + daily_net_adjustment

    if shock_amount and shock_date:
        shock_day = pd.Timestamp(shock_date).normalize()
        matches = pd.to_datetime(result["date"]).dt.normalize().eq(shock_day)
        if matches.any():
            shock_index = int(np.flatnonzero(matches.to_numpy())[0])
            if shock_amount > 0:
                inflow[shock_index] += shock_amount
            else:
                outflow[shock_index] += abs(shock_amount)
            net_flow[shock_index] += shock_amount

    result["inflow"] = inflow
    result["outflow"] = outflow
    result["net_flow"] = net_flow
    result["forecast_net"] = net_flow
    if current_balance is not None:
        result["balance"] = current_balance + np.cumsum(net_flow)
    else:
        result["balance"] = np.nan
    return result
