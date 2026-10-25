"""Transparent retrospective metrics for forecast and categorization quality."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.data_loader import validate_daily_balances
from src.categorization.rules import categorize_rule
from src.forecasting.models import forecast_flows


def _regression_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float | None]:
    if len(actual) == 0:
        return {name: None for name in ("MAE", "MSE", "RMSE", "MAPE", "R2")}
    errors = actual - predicted
    nonzero = np.abs(actual) > 1e-9
    total_variance = float(np.sum((actual - np.mean(actual)) ** 2))
    return {
        "MAE": float(np.mean(np.abs(errors))),
        "MSE": float(np.mean(errors**2)),
        "RMSE": float(np.sqrt(np.mean(errors**2))),
        "MAPE": float(np.mean(np.abs(errors[nonzero] / actual[nonzero])) * 100) if nonzero.any() else None,
        "R2": float(1 - np.sum(errors**2) / total_variance) if len(actual) > 1 and total_variance > 0 else None,
    }


def _holt_winters(history: np.ndarray, horizon: int, season_length: int = 7) -> np.ndarray:
    """Additive Holt-Winters projection with fixed, conservative smoothing factors."""
    if len(history) < season_length * 2:
        return np.full(horizon, float(np.mean(history[-min(7, len(history)):])) if len(history) else 0.0)
    alpha, beta, gamma = 0.3, 0.1, 0.2
    level = float(np.mean(history[:season_length]))
    trend = float((np.mean(history[season_length:2 * season_length]) - level) / season_length)
    seasonal = (history[:season_length] - level).astype(float)
    for index in range(season_length, len(history)):
        previous_level = level
        season_index = index % season_length
        level = alpha * (history[index] - seasonal[season_index]) + (1 - alpha) * (level + trend)
        trend = beta * (level - previous_level) + (1 - beta) * trend
        seasonal[season_index] = gamma * (history[index] - level) + (1 - gamma) * seasonal[season_index]
    return np.asarray([
        level + (step + 1) * trend + seasonal[(len(history) + step) % season_length]
        for step in range(horizon)
    ], dtype=float)


def _classification_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float | int | None]:
    true_positive = int(np.sum(actual & predicted))
    false_positive = int(np.sum(~actual & predicted))
    false_negative = int(np.sum(actual & ~predicted))
    true_negative = int(np.sum(~actual & ~predicted))
    count = len(actual)
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "TP": true_positive,
        "FP": false_positive,
        "FN": false_negative,
        "TN": true_negative,
        "Accuracy": (true_positive + true_negative) / count if count else None,
        "Precision": precision,
        "Recall": recall,
        "F1": f1,
        "percentages": {
            "TP": true_positive / count * 100 if count else 0.0,
            "FP": false_positive / count * 100 if count else 0.0,
            "FN": false_negative / count * 100 if count else 0.0,
            "TN": true_negative / count * 100 if count else 0.0,
        },
        "sample_count": count,
    }


def _roc_auc(actual: np.ndarray, risk_score: np.ndarray) -> float | None:
    positives = risk_score[actual]
    negatives = risk_score[~actual]
    if not len(positives) or not len(negatives):
        return None
    comparisons = positives[:, None] - negatives[None, :]
    return float((np.sum(comparisons > 0) + 0.5 * np.sum(comparisons == 0)) / comparisons.size)


def _category_confusion(operations: pd.DataFrame, categorized: pd.DataFrame) -> dict:
    reference = operations.apply(categorize_rule, axis=1, result_type="expand")["category"].astype(str)
    predicted = categorized["category"].astype(str)
    labels = sorted(set(reference) | set(predicted))
    matrix = pd.crosstab(
        pd.Categorical(reference, categories=labels),
        pd.Categorical(predicted, categories=labels),
        dropna=False,
    )
    total = int(matrix.to_numpy().sum())
    accuracy = float(np.trace(matrix.to_numpy()) / total) if total else None
    return {
        "labels": labels,
        "matrix": matrix.to_numpy(dtype=int).tolist(),
        "accuracy": accuracy,
        "sample_count": total,
        "reference_note": "Сверка с правилами категоризации (weak labels), не с ручной экспертной разметкой.",
    }


def build_quality_metrics(operations: pd.DataFrame, categorized: pd.DataFrame) -> dict:
    if operations.empty:
        return {
            "train_test": {"train_days": 0, "test_days": 0, "split_date": None},
            "comparison": [],
            "cash_gap_confusion": {
                **_classification_metrics(np.array([], dtype=bool), np.array([], dtype=bool)),
                "roc_auc": None,
            },
            "category_confusion": _category_confusion(operations, categorized),
            "diagnostics": {"missing_calendar_days": 0, "balance_inconsistencies": 0, "anomalies": 0},
        }

    daily = operations.groupby("date", as_index=False).agg(
        inflow=("signed_amount", lambda values: float(values[values > 0].sum())),
        outflow=("signed_amount", lambda values: float(-values[values < 0].sum())),
    ).sort_values("date")
    daily = daily.set_index("date").asfreq("D", fill_value=0)
    total_days = len(daily)
    test_days = min(90, max(7, int(round(total_days * 0.2))))
    train_days = max(0, total_days - test_days)
    train = daily.iloc[:train_days]
    test = daily.iloc[train_days:]
    comparison = []
    gap_confusion = {
        **_classification_metrics(np.array([], dtype=bool), np.array([], dtype=bool)),
        "roc_auc": None,
    }
    if not train.empty and not test.empty:
        actual_net = (test["inflow"] - test["outflow"]).to_numpy(dtype=float)
        moving_average = np.full(len(test), float((train["inflow"] - train["outflow"]).tail(7).mean()))
        seasonal_history = (train["inflow"] - train["outflow"]).to_numpy(dtype=float)
        holt_winters = _holt_winters(seasonal_history, len(test))
        projected_frame = forecast_flows(train.reset_index(), len(test), method="ML")
        hybrid = projected_frame["net_flow"].to_numpy(dtype=float)
        if projected_frame.attrs.get("method", "baseline").startswith("baseline"):
            hybrid_label = "Гибридный ансамбль проекта (fallback baseline)"
        else:
            hybrid_label = "Гибридный ансамбль проекта"
        methods = [
            ("Baseline Moving Average", moving_average),
            ("Seasonal Holt-Winters", holt_winters),
            (hybrid_label, hybrid),
        ]
        actual_balance_delta = np.cumsum(actual_net)
        balance_values = operations.loc[operations["balance_eod"].notna()].sort_values("date")
        origin_balance_rows = balance_values.loc[balance_values["date"] < test.index[0]]
        starting_balance = float(origin_balance_rows.iloc[-1]["balance_eod"]) if not origin_balance_rows.empty else None
        for method, predicted_net in methods:
            predicted_balance_delta = np.cumsum(predicted_net)
            regression = _regression_metrics(actual_balance_delta, predicted_balance_delta)
            absolute_actual = actual_balance_delta + starting_balance if starting_balance is not None else actual_balance_delta
            absolute_predicted = predicted_balance_delta + starting_balance if starting_balance is not None else predicted_balance_delta
            actual_gap = absolute_actual < 0
            predicted_gap = absolute_predicted < 0
            classification = _classification_metrics(actual_gap, predicted_gap)
            comparison.append({
                "method": method,
                **regression,
                "Accuracy": classification["Accuracy"],
                "Precision": classification["Precision"],
                "Recall": classification["Recall"],
                "F1": classification["F1"],
                "ROC_AUC": _roc_auc(actual_gap, -absolute_predicted),
            })
            if method == hybrid_label:
                gap_confusion = {**classification, "roc_auc": _roc_auc(actual_gap, -absolute_predicted)}

    balance_checks = validate_daily_balances(operations)
    span = max(0, (operations["date"].max() - operations["date"].min()).days + 1)
    abs_amounts = operations["signed_amount"].abs().dropna()
    anomaly_threshold = float(abs_amounts.quantile(0.99) * 10) if not abs_amounts.empty else 0.0
    diagnostics = {
        "missing_calendar_days": max(0, span - int(operations["date"].nunique())),
        "balance_inconsistencies": int((~balance_checks["balance_consistent"]).sum()) if not balance_checks.empty else 0,
        "anomalies": int((abs_amounts > anomaly_threshold).sum()) if anomaly_threshold else 0,
        "anomaly_rule": "Сумма выше 10×P99 истории компании.",
    }
    return {
        "train_test": {
            "train_days": train_days,
            "test_days": len(test),
            "split_date": test.index[0].date().isoformat() if not test.empty else None,
        },
        "comparison": comparison,
        "cash_gap_confusion": gap_confusion,
        "category_confusion": _category_confusion(operations, categorized),
        "diagnostics": diagnostics,
    }
