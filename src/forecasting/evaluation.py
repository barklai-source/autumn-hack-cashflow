"""Walk-forward evaluation of daily cash-flow methods."""

import numpy as np
import pandas as pd

from config.settings import MINIMUM_HISTORY_DAYS_FOR_ML
from src.forecasting.models import forecast_flows


def error_metrics(actual: np.ndarray | pd.Series, predicted: np.ndarray | pd.Series) -> dict[str, float]:
    """Compute MAE, RMSE, and zero-safe WAPE."""
    y = np.asarray(actual, dtype=float)
    p = np.asarray(predicted, dtype=float)
    if len(y) == 0:
        return {"MAE": float("nan"), "RMSE": float("nan"), "WAPE": float("nan")}
    errors = y - p
    denominator = float(np.abs(y).sum())
    return {
        "MAE": float(np.mean(np.abs(errors))),
        "RMSE": float(np.sqrt(np.mean(errors**2))),
        "WAPE": float(np.abs(errors).sum() / denominator) if denominator > 0 else float("nan"),
    }


def _summarize_predictions(predictions: pd.DataFrame) -> pd.DataFrame:
    metrics = []
    for (method, _), group in predictions.groupby(["method", predictions["date"].dt.year]):
        row = {"method": method, **error_metrics(group["actual_net"], group["predicted_net"])}
        balance_metrics = error_metrics(group["actual_balance_delta"], group["predicted_balance_delta"])
        row.update({f"balance_{key}": value for key, value in balance_metrics.items()})
        metrics.append(row)
    return pd.DataFrame(metrics).groupby("method", as_index=False).mean(numeric_only=True)


def walk_forward_evaluation(daily: pd.DataFrame, horizon: int = 7, max_origins: int = 5) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Evaluate baseline and ML with chronological expanding-window cutoffs."""
    if len(daily) < horizon + 45:
        return pd.DataFrame(), pd.DataFrame()
    data = daily.set_index("date").sort_index().asfreq("D", fill_value=0)
    first_origin = MINIMUM_HISTORY_DAYS_FOR_ML if len(data) >= MINIMUM_HISTORY_DAYS_FOR_ML + horizon else 35
    available_origins = len(data) - horizon - first_origin
    if available_origins < 0:
        first_origin = 35
        available_origins = len(data) - horizon - first_origin
    origin_count = min(max_origins, max(1, available_origins // 14 + 1))
    origins = (
        np.array([len(data) - horizon])
        if origin_count == 1
        else np.linspace(first_origin, len(data) - horizon, num=origin_count, dtype=int)
    )
    records = []
    for origin in sorted(set(origins)):
        history = data.iloc[:origin]
        actual = data.iloc[origin:origin + horizon]
        methods = ("baseline", "ML") if len(history) >= MINIMUM_HISTORY_DAYS_FOR_ML else ("baseline",)
        for method in methods:
            try:
                predicted = forecast_flows(history.reset_index(), horizon, method=method)
                predicted = predicted.set_index("date").reindex(actual.index)
                actual_balance_delta = actual["net_flow"].cumsum()
                predicted_balance_delta = predicted["net_flow"].cumsum()
                for date in actual.index:
                    records.append({"date": date, "origin": history.index[-1], "method": method,
                                    "actual_net": actual.loc[date, "net_flow"],
                                    "predicted_net": predicted.loc[date, "net_flow"],
                                    "actual_balance_delta": actual_balance_delta.loc[date],
                                    "predicted_balance_delta": predicted_balance_delta.loc[date]})
            except (ValueError, KeyError):
                continue
    predictions = pd.DataFrame(records)
    if predictions.empty:
        return predictions, pd.DataFrame()
    return predictions, _summarize_predictions(predictions)


def evaluate_balance_horizons(
    daily: pd.DataFrame,
    seven_day_metrics: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Report available chronological 7/30/90-day net flow error summaries."""
    rows = []
    if seven_day_metrics is not None and not seven_day_metrics.empty:
        rows.extend(
            {"horizon_days": 7, "method": row["method"],
             "MAE": row["balance_MAE"], "RMSE": row["balance_RMSE"],
             "WAPE": row["balance_WAPE"]}
            for row in seven_day_metrics.to_dict("records")
        )

    long_predictions, long_metrics = walk_forward_evaluation(daily, horizon=90, max_origins=1)
    if not long_predictions.empty:
        thirty_day_predictions = long_predictions.groupby(["method", "origin"], sort=False).head(30)
        metrics_by_horizon = {
            30: _summarize_predictions(thirty_day_predictions),
            90: long_metrics,
        }
    else:
        _, thirty_day_metrics = walk_forward_evaluation(daily, horizon=30, max_origins=1)
        metrics_by_horizon = {30: thirty_day_metrics}

    for horizon, metrics in metrics_by_horizon.items():
        if not metrics.empty:
            rows.extend(
                {"horizon_days": horizon, "method": row["method"],
                 "MAE": row["balance_MAE"], "RMSE": row["balance_RMSE"],
                 "WAPE": row["balance_WAPE"]}
                for row in metrics.to_dict("records")
            )
    return pd.DataFrame(rows)
