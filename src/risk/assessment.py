"""Deterministic and block-bootstrap cash reserve risk analysis."""

import numpy as np
import pandas as pd


def assess_risk(
    forecast: pd.DataFrame,
    reserve: float = 0.0,
    residuals: np.ndarray | list[float] | None = None,
    scenarios: int = 1000,
    seed: int = 42,
    block_size: int = 7,
    events: pd.DataFrame | None = None,
    historical_net_flows: np.ndarray | pd.Series | list[float] | None = None,
) -> dict[str, object]:
    """Estimate liquidity risk using a 100-path block bootstrap."""
    method = "Блочный бутстрап (100 симуляций) с учётом волатильности потока"
    if forecast.empty or forecast["balance"].isna().all():
        return {"first_breach": None, "max_deficit": None, "zero_deficit": None, "reserve_deficit": None,
                "probability": None, "gap_probability": None, "p10": None, "p90": None,
                "risk_level": "не оценён", "method": method,
                "warning": None, "influencing_events": [], "horizon_days": len(forecast)}
    below = forecast.loc[forecast["balance"] < reserve]
    first = None if below.empty else below.iloc[0]
    deficit = float(max(0, reserve - forecast["balance"].min()))
    zero_deficit = float(max(0, -forecast["balance"].min()))
    influencing_events = []
    if events is not None and first is not None and not events.empty:
        eligible = events.loc[
            events["status"].isin(["ожидается", "подтверждено"]) &
            (pd.to_datetime(events["date"]) >= pd.Timestamp(forecast["date"].min())) &
            (pd.to_datetime(events["date"]) <= pd.Timestamp(first["date"]))
        ]
        influencing_events = [
            {"date": pd.Timestamp(row["date"]), "amount": float(row["amount"]),
             "description": str(row.get("description", "")) or str(row.get("category", "Событие"))}
            for row in eligible.sort_values("date").to_dict("records")
        ]
    errors = np.asarray(residuals if residuals is not None else [], dtype=float)
    errors = errors[np.isfinite(errors)]
    history = np.asarray(historical_net_flows if historical_net_flows is not None else [], dtype=float)
    history = history[np.isfinite(history)]
    if len(errors) >= 30:
        centered_errors = errors - np.median(errors)
        lower, upper = np.quantile(centered_errors, [0.05, 0.95])
        bootstrap_pool = np.clip(centered_errors, lower, upper)
    else:
        source = history
        if len(source) < 2:
            source = forecast["forecast_net"].to_numpy(dtype=float)
        sigma = float(np.std(source, ddof=1)) if len(source) > 1 else 0.0
        centered = source - float(np.mean(source)) if len(source) else np.zeros(1, dtype=float)
        source_sigma = float(np.std(centered, ddof=1)) if len(centered) > 1 else 0.0
        if source_sigma > 0:
            bootstrap_pool = centered * (sigma / source_sigma)
        else:
            bootstrap_pool = np.zeros(max(1, len(centered)), dtype=float)
    bootstrap_iterations = 100
    pool_size = max(block_size, len(bootstrap_pool))
    if len(bootstrap_pool) < pool_size:
        bootstrap_pool = np.resize(bootstrap_pool, pool_size)
    rng = np.random.default_rng(seed)
    net = forecast["forecast_net"].to_numpy(dtype=float)
    base = float(forecast["balance"].iloc[0] - forecast["forecast_net"].iloc[0])
    n = len(net)
    effective_block_size = min(max(1, block_size), pool_size)
    blocks_needed = int(np.ceil(n / effective_block_size))
    starts = rng.integers(
        0, pool_size - effective_block_size + 1,
        size=(bootstrap_iterations, blocks_needed),
    )
    offsets = np.arange(effective_block_size)
    samples = bootstrap_pool[starts[:, :, None] + offsets].reshape(bootstrap_iterations, -1)[:, :n]
    balances = base + np.cumsum(net[None, :] + samples, axis=1)
    minimum_balances = balances.min(axis=1)
    simulated_breaches = np.any(balances < reserve, axis=1)
    probability = float(simulated_breaches.mean())
    p10, p90 = (float(value) for value in np.quantile(minimum_balances, [0.1, 0.9]))
    level = "высокий" if (probability is not None and probability >= 0.5) or (probability is None and first is not None and deficit > 0) else (
        "средний" if (probability is not None and probability >= 0.15) or first is not None else "низкий"
    )
    warning = None
    warning_row = first
    estimated_reserve_shortfall = None
    estimated_zero_shortfall = None
    if warning_row is None and simulated_breaches.any():
        first_indices = np.argmax(balances[simulated_breaches] < reserve, axis=1)
        most_common_index = int(np.bincount(first_indices, minlength=n).argmax())
        warning_row = forecast.iloc[most_common_index]
        breached_minimums = minimum_balances[simulated_breaches]
        estimated_reserve_shortfall = float(np.maximum(0, reserve - breached_minimums).mean())
        estimated_zero_shortfall = float(np.maximum(0, -breached_minimums).mean())
    if warning_row is not None:
        breach_date = pd.Timestamp(warning_row["date"])
        breach_balance = float(warning_row["balance"])
        reserve_shortfall = estimated_reserve_shortfall
        if reserve_shortfall is None:
            reserve_shortfall = float(max(0, reserve - breach_balance))
        zero_shortfall = estimated_zero_shortfall
        if zero_shortfall is None:
            zero_shortfall = float(max(0, -breach_balance))
        recommended_amount = reserve_shortfall or zero_shortfall
        format_money = lambda amount: f"{amount:,.0f}".replace(",", " ")
        major_outflows = [
            event for event in influencing_events
            if event["amount"] < 0 and abs(event["amount"]) >= max(100_000, reserve_shortfall * 0.1)
        ][:3]
        event_details = "; ".join(
            f"{event['description']} — {format_money(abs(event['amount']))} ₽"
            for event in major_outflows
        )
        if first is None:
            reasons = (
                f"Блочный бутстрап выявил риск кассового разрыва около {breach_date:%d.%m.%Y}: "
                f"средний дефицит до нуля {format_money(zero_shortfall)} ₽, "
                f"до резерва — {format_money(reserve_shortfall)} ₽."
            )
        else:
            reasons = (
                f"Кассовый разрыв ожидается {breach_date:%d.%m.%Y}: дефицит до нуля "
                f"{format_money(zero_shortfall)} ₽, до резерва — {format_money(reserve_shortfall)} ₽."
            )
        if event_details:
            reasons += f" На период до разрыва приходятся крупные списания: {event_details}."
        warning = {
            "date": breach_date,
            "deficit": reserve_shortfall,
            "probability": probability,
            "gap_probability": probability,
            "p10": p10,
            "p90": p90,
            "reasons": reasons,
            "action": (
                f"Для устранения кассового разрыва на сумму {format_money(recommended_amount)} ₽ "
                f"к {breach_date:%d.%m.%Y} рекомендуется: 1) Согласовать перенос оплаты поставщикам "
                "на 7–14 дней; 2) Ускорить взыскание дебиторской задолженности и запросить предоплату "
                "по договорам; 3) Рассмотреть овердрафт Банка Центр-инвест "
                f"на сумму дефицита — около {format_money(recommended_amount)} ₽."
            ),
        }
    return {
        "first_breach": None if first is None else pd.Timestamp(first["date"]),
        "max_deficit": deficit,
        "zero_deficit": zero_deficit,
        "reserve_deficit": deficit,
        "influencing_events": influencing_events,
        "probability": probability,
        "gap_probability": probability,
        "p10": p10,
        "p90": p90,
        "risk_level": level,
        "method": method,
        "warning": warning,
        "reserve": reserve,
        "horizon_days": len(forecast),
    }
