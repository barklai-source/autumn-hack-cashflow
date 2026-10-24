"""Baseline and ML daily flow models."""

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from config.settings import MINIMUM_HISTORY_DAYS_FOR_ML, RANDOM_SEED
from src.forecasting.features import _feature_row, supervised_features


def baseline_value(history: pd.Series, date: pd.Timestamp) -> float:
    """Use same-weekday median when available, otherwise trailing 28-day median."""
    weekday = history.loc[history.index.day_of_week == date.day_of_week]
    if len(weekday) and float(weekday.eq(0).mean()) >= 0.8:
        return 0.0
    recent = history.tail(28)
    if len(weekday) >= 4:
        return float(weekday.median())
    return float(recent.median()) if len(recent) else 0.0


def _fit_ml(history: pd.Series) -> HistGradientBoostingRegressor | None:
    if len(history) < MINIMUM_HISTORY_DAYS_FOR_ML:
        return None
    positive = history.loc[history > 0]
    if not positive.empty:
        upper = float(positive.quantile(0.95))
        history = history.clip(upper=upper)
    x, y = supervised_features(history)
    if len(x) < 60:
        return None
    model = HistGradientBoostingRegressor(
        loss="absolute_error", max_iter=80, learning_rate=0.06, max_leaf_nodes=15,
        min_samples_leaf=10, l2_regularization=1.5, early_stopping=True,
        n_iter_no_change=10, random_state=RANDOM_SEED,
    )
    model.fit(x.to_numpy(dtype=float), y.to_numpy(dtype=float))
    return model


def _baseline_value(values: np.ndarray, weekdays: np.ndarray, date: pd.Timestamp) -> float:
    weekday_values = values[weekdays == date.day_of_week]
    if len(weekday_values) and float(np.count_nonzero(weekday_values == 0) / len(weekday_values)) >= 0.8:
        return 0.0
    recent = values[-28:]
    if len(weekday_values) >= 4:
        return float(np.median(weekday_values) if np.isfinite(weekday_values).all() else np.nanmedian(weekday_values))
    return float(np.median(recent) if np.isfinite(recent).all() else np.nanmedian(recent)) if len(recent) else 0.0


def forecast_component(history: pd.Series, future_dates: pd.DatetimeIndex, method: str) -> pd.Series:
    """Forecast one nonnegative flow component recursively."""
    series = history.astype(float).copy().sort_index()
    history_dates = pd.DatetimeIndex(series.index)
    initial_values = series.to_numpy(dtype=float)
    weekend_values = initial_values[history_dates.day_of_week >= 5]
    weekend_is_zero = bool(
        len(weekend_values) and float(np.count_nonzero(weekend_values == 0) / len(weekend_values)) > 0.85
    )
    model = _fit_ml(series) if method == "ML" else None
    chosen = "ML" if model is not None else "baseline"
    dates = history_dates.append(pd.DatetimeIndex(future_dates))
    weekdays = dates.day_of_week.to_numpy()
    values = np.empty(len(dates), dtype=float)
    values[:len(initial_values)] = initial_values
    predictions = np.empty(len(future_dates), dtype=float)
    for offset, date in enumerate(future_dates):
        position = len(initial_values) + offset
        prior_values = values[:position]
        prior_weekdays = weekdays[:position]
        if weekend_is_zero and date.day_of_week >= 5:
            value = 0.0
        elif chosen == "ML":
            features = np.asarray(list(_feature_row(prior_values, prior_weekdays, date).values()), dtype=float).reshape(1, -1)
            ml_prediction = float(model.predict(features)[0])
            value = 0.75 * ml_prediction + 0.25 * _baseline_value(prior_values, prior_weekdays, date)
        else:
            value = _baseline_value(prior_values, prior_weekdays, date)
        value = max(0.0, value)
        predictions[offset] = value
        values[position] = value
    return pd.Series(predictions, index=future_dates, dtype=float)


def forecast_flows(daily: pd.DataFrame, horizon_days: int, method: str = "auto", start_date: pd.Timestamp | None = None) -> pd.DataFrame:
    """Forecast inflows and outflows independently and report selected method."""
    if daily.empty:
        raise ValueError("Для прогноза нужна хотя бы одна историческая операция.")
    indexed = daily.set_index("date").sort_index().asfreq("D", fill_value=0)
    date0 = pd.Timestamp(start_date or indexed.index.max())
    if date0 < indexed.index.max():
        raise ValueError("Дата начала прогноза не может предшествовать последним историческим данным.")
    if date0 > indexed.index.max():
        full_index = pd.date_range(indexed.index.min(), date0, freq="D")
        indexed = indexed.reindex(full_index, fill_value=0.0)
        indexed.index.name = "date"
    future_dates = pd.date_range(date0 + pd.Timedelta(days=1), periods=horizon_days)
    requested = method
    use_ml = method in {"auto", "ML"} and len(indexed) >= MINIMUM_HISTORY_DAYS_FOR_ML
    selected = "ML" if use_ml else "baseline"
    inflow = forecast_component(indexed["inflow"], future_dates, selected)
    outflow = forecast_component(indexed["outflow"], future_dates, selected)
    if requested == "ML" and selected == "baseline":
        selected = "baseline (недостаточно истории)"
    result = pd.DataFrame({"date": future_dates, "inflow": inflow.values, "outflow": outflow.values})
    result["net_flow"] = result["inflow"] - result["outflow"]
    result.attrs["method"] = selected
    return result
