"""Company-isolated recurring flow detection."""

import hashlib

import pandas as pd

from app.core.storage import SQLiteStore
from src.recurring.detector import detect_recurring


def company_recurring(operations: pd.DataFrame, store: SQLiteStore) -> pd.DataFrame:
    """Return repeat series with stable IDs and saved user confirmations."""
    if operations.empty:
        return pd.DataFrame()
    result = detect_recurring(operations)
    if result.empty:
        return result
    company_id = str(operations["company_id"].iloc[0])
    result["recurring_id"] = result["series_id"].map(
        lambda value: hashlib.sha256(f"{company_id}|{value}".encode("utf-8")).hexdigest()[:20]
    )
    confirmations = store.recurring_confirmation(company_id)
    result["confirmed"] = result.apply(
        lambda row: confirmations.get(
            row["recurring_id"],
            float(row["confidence"]) >= 0.75,
        ),
        axis=1,
    ).astype(bool)
    return result
