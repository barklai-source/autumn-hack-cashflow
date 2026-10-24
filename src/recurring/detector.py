"""Conservative detector of recurring flows."""

import numpy as np
import pandas as pd


PERIODS = {"ежедневно": 1, "еженедельно": 7, "ежемесячно": 30, "ежеквартально": 91}


def detect_recurring(operations: pd.DataFrame, minimum_observations: int = 3) -> pd.DataFrame:
    """Group likely recurring operations by account, counterparty and purpose."""
    columns = ["series_id", "account", "counterparty", "purpose", "direction", "category", "frequency", "amount", "next_date", "observations", "confidence", "confirmed", "accepted"]
    if operations.empty:
        return pd.DataFrame(columns=columns)
    frame = operations.copy()
    if "category" not in frame:
        frame["category"] = "Не указана"
    frame["series_id"] = (
        frame["account"].fillna("").astype(str) + "|" +
        frame["counterparty"].fillna("").astype(str).str.lower() + "|" +
        frame["inn"].fillna("").astype(str) + "|" +
        frame["purpose"].fillna("").astype(str).str.lower().str[:28] + "|" +
        frame["category"].astype(str) + "|" + np.where(frame["amount"] >= 0, "in", "out")
    )
    rows = []
    for series_id, group in frame.groupby("series_id"):
        group = group.sort_values("date")
        if len(group) < minimum_observations:
            continue
        intervals = group["date"].diff().dropna().dt.days.to_numpy()
        median_interval = float(np.median(intervals))
        frequency = min(PERIODS, key=lambda label: abs(PERIODS[label] - median_interval))
        target = PERIODS[frequency]
        interval_error = float(np.median(np.abs(intervals - target)) / max(target, 1))
        amounts = group["amount"].abs()
        amount_cv = float(amounts.std(ddof=0) / max(amounts.mean(), 1))
        if interval_error > 0.24 or amount_cv > 0.35:
            continue
        confidence = float(np.clip(0.55 + 0.12 * (len(group) - 3) - interval_error * 0.7 - amount_cv * 0.25, 0.5, 0.98))
        last = group.iloc[-1]
        rows.append({
            "series_id": series_id,
            "account": last.get("account", ""),
            "counterparty": last.get("counterparty", ""),
            "purpose": last.get("purpose", ""),
            "direction": "поступление" if last["amount"] > 0 else "списание",
            "category": last["category"],
            "frequency": frequency,
            "amount": float(group["amount"].median()),
            "next_date": pd.Timestamp(last["date"]) + pd.Timedelta(days=target),
            "observations": int(len(group)),
            "confidence": confidence,
            "confirmed": confidence >= 0.75,
            "accepted": True,
        })
    return pd.DataFrame(rows, columns=columns)
