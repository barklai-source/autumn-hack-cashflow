"""Deterministic demo scoring that simulates open-register counterparty checks."""

from __future__ import annotations

import hashlib
import re

import pandas as pd

RELIABLE = "Надежный (ФНС ок)"
DELAY_RISK = "Риск задержки (долги ФНС / иски)"
HIGH_RISK = "Высокий риск (признаки банкротства)"


def score_counterparty(inn: object, history: pd.DataFrame | None = None) -> dict | None:
    if inn is None or pd.isna(inn):
        return None
    digits = re.sub(r"\D", "", str(inn))
    if len(digits) not in (10, 12):
        return None

    history_count = 0 if history is None else len(history)
    register_indicator = int(hashlib.sha256(digits.encode("ascii")).hexdigest()[:8], 16) % 100
    history_adjustment = 12 if history_count == 1 else 5 if history_count <= 3 else 0
    score = min(100, register_indicator + history_adjustment)
    if score >= 80:
        status = HIGH_RISK
        delay_probability = 0.68
        advice = "Проверьте контрагента и предусмотрите резерв или авансовый платёж."
    elif score >= 55:
        status = DELAY_RISK
        delay_probability = 0.34
        advice = "Уточните дату оплаты и контролируйте дебиторскую задолженность."
    else:
        status = RELIABLE
        delay_probability = 0.08
        advice = "Признаков повышенного риска в демо-проверке не выявлено."
    return {
        "status": status,
        "score": score,
        "delay_probability": delay_probability,
        "advice": advice,
        "source": "Имитация проверки открытых реестров",
    }


def company_counterparty_scores(operations: pd.DataFrame) -> dict[str, dict]:
    if operations.empty or "counterparty_inn" not in operations:
        return {}
    result: dict[str, dict] = {}
    for inn, history in operations.groupby("counterparty_inn", dropna=True, sort=False):
        score = score_counterparty(inn, history)
        if score is not None:
            result[re.sub(r"\D", "", str(inn))] = score
    return result


def incoming_delay_probability(operations: pd.DataFrame) -> float | None:
    if operations.empty or "counterparty_inn" not in operations:
        return None
    incoming = operations.loc[operations["signed_amount"] > 0].copy()
    if incoming.empty:
        return None
    incoming["inn_key"] = incoming["counterparty_inn"].fillna("").astype(str).str.replace(r"\D", "", regex=True)
    scores = company_counterparty_scores(operations)
    incoming["probability"] = incoming["inn_key"].map(
        lambda key: scores.get(key, {}).get("delay_probability", 0.08),
    )
    weights = incoming["signed_amount"].abs()
    if float(weights.sum()) <= 0:
        return None
    return float((incoming["probability"] * weights).sum() / weights.sum())
