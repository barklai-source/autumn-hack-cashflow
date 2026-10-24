"""Explainable transaction categorization with persistent user corrections."""

from __future__ import annotations

import pandas as pd

from app.core.storage import SQLiteStore
from src.categorization.classifier import TransactionClassifier
from src.categorization.rules import categorize_rule


def categorize_operations(frame: pd.DataFrame, store: SQLiteStore) -> pd.DataFrame:
    """Categorize a single company's records and apply saved overrides."""
    result = frame.drop(columns=["category"], errors="ignore").copy()
    if result.empty:
        for column in ("category", "category_method", "confidence", "needs_review"):
            result[column] = pd.Series(dtype="object")
        return result
    classifications = result.apply(categorize_rule, axis=1, result_type="expand")
    result = pd.concat([result, classifications.rename(columns={
        "method": "category_method", "confidence": "confidence", "needs_review": "needs_review",
    })], axis=1)
    overrides = store.get_category_overrides(str(result["company_id"].iloc[0]))
    mask = result["operation_id"].astype(str).isin(overrides)
    result.loc[mask, "category"] = result.loc[mask, "operation_id"].astype(str).map(overrides)
    result.loc[mask, "category_method"] = "ручная корректировка"
    result.loc[mask, "confidence"] = 1.0
    result.loc[mask, "needs_review"] = False

    manual = result["category_method"].eq("ручная корректировка")
    confident_rules = result["category_method"].eq("правила") & result["confidence"].ge(0.85)
    training = result.loc[(manual | confident_rules) & result["category"].ne("Требует проверки")]
    if len(training) >= 8 and training["category"].nunique() >= 2:
        texts = (
            training["purpose"].fillna("").astype(str) + " "
            + training["counterparty"].fillna("").astype(str) + " "
            + training["inn"].fillna("").astype(str)
        ).tolist()
        sample_weights = [3.0 if method == "ручная корректировка" else 1.0 for method in training["category_method"]]
        classifier = TransactionClassifier()
        try:
            classifier.fit(texts, training["category"].astype(str).tolist(), sample_weights)
        except ValueError:
            classifier = None
        if classifier is not None:
            uncertain = result["needs_review"].fillna(False).astype(bool)
            for index in result.index[uncertain]:
                operation = result.loc[index]
                text = " ".join(
                    str(operation[key]) if key in operation and pd.notna(operation[key]) else ""
                    for key in ("purpose", "counterparty", "inn")
                )
                prediction = classifier.predict(text, minimum_confidence=0.65)
                if prediction["confidence"] >= 0.65:
                    result.loc[index, "category"] = prediction["category"]
                    result.loc[index, "category_method"] = "ML-классификатор"
                    result.loc[index, "confidence"] = prediction["confidence"]
                    result.loc[index, "needs_review"] = False
    return result
