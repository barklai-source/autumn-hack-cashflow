"""Leakage-safe time-series features."""

import numpy as np
import pandas as pd


def _feature_row(values: np.ndarray, weekdays: np.ndarray, date: pd.Timestamp) -> dict[str, float]:
    recent = values[-28:]
    recent_7 = values[-7:]
    finite_recent = np.isfinite(recent).all()
    finite_recent_7 = np.isfinite(recent_7).all()
    weekday_values = values[weekdays == date.weekday()][-4:]
    finite_weekday = np.isfinite(weekday_values).all()
    row: dict[str, float] = {
        "weekday": float(date.weekday()),
        "day": float(date.day),
        "month": float(date.month),
        "weekofyear": float(date.isocalendar().week),
        "is_weekend": 1.0 if date.weekday() >= 5 else 0.0,
        "is_month_start": 1.0 if date.day <= 5 else 0.0,
        "is_month_end": 1.0 if date.day >= 25 else 0.0,
        "is_tax_day": 1.0 if 25 <= date.day <= 28 else 0.0,
        "is_payroll_day": 1.0 if date.day in (5, 6, 7, 10, 20, 21, 22, 25) else 0.0,
    }
    for lag in (1, 7, 14, 28):
        row[f"lag_{lag}"] = float(values[-lag]) if len(values) >= lag else 0.0
    row["mean_7"] = float(np.mean(recent_7) if finite_recent_7 else np.nanmean(recent_7)) if len(recent_7) else 0.0
    row["mean_28"] = float(np.mean(recent) if finite_recent else np.nanmean(recent)) if len(recent) else 0.0
    row["median_7"] = float(np.median(recent_7) if finite_recent_7 else np.nanmedian(recent_7)) if len(recent_7) else 0.0
    row["median_28"] = float(np.median(recent) if finite_recent else np.nanmedian(recent)) if len(recent) else 0.0
    valid_recent_count = len(recent) if finite_recent else np.count_nonzero(~np.isnan(recent))
    row["std_28"] = (
        float(np.std(recent, ddof=0) if finite_recent else np.nanstd(recent, ddof=0))
        if valid_recent_count >= 2 else 0.0
    )
    row["same_weekday_median"] = (
        float(np.median(weekday_values) if finite_weekday else np.nanmedian(weekday_values))
        if len(weekday_values) else 0.0
    )
    return row


def feature_row(history: pd.Series, date: pd.Timestamp) -> dict[str, float]:
    """Create calendar and lag features using observations strictly before date."""
    index = pd.DatetimeIndex(history.index)
    values = history.to_numpy(dtype=float, na_value=np.nan)
    weekdays = index.day_of_week.to_numpy()
    cutoff = index.searchsorted(date, side="left") if index.is_monotonic_increasing else None
    if cutoff is None:
        past = index < date
        return _feature_row(values[past], weekdays[past], date)
    return _feature_row(values[:cutoff], weekdays[:cutoff], date)


def supervised_features(series: pd.Series) -> tuple[pd.DataFrame, pd.Series]:
    """Build rows from historical data where each row only sees earlier values."""
    dates = pd.DatetimeIndex(series.index)
    values = series.to_numpy(dtype=float, na_value=np.nan)
    weekdays = dates.day_of_week.to_numpy()
    rows = []
    for position, date in enumerate(dates[28:], start=28):
        rows.append(_feature_row(values[:position], weekdays[:position], date))
    return pd.DataFrame(rows, index=series.index[28:]), series.iloc[28:].astype(float)
