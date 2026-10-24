import numpy as np
import pandas as pd

from src.risk.assessment import assess_risk


def test_risk_uses_volatility_bootstrap_when_residuals_are_insufficient():
    forecast = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=3), "balance": [120, 80, 20],
                             "forecast_net": [-40, -40, -60]})
    history = np.array([10, -20, 35, -15, 5, -30, 40], dtype=float)
    result = assess_risk(forecast, reserve=50, historical_net_flows=history)
    assert result["first_breach"] == pd.Timestamp("2025-01-03")
    assert result["max_deficit"] == 30
    assert result["probability"] == result["gap_probability"]
    assert 0 <= result["gap_probability"] <= 1
    assert result["p10"] <= result["p90"]
    assert result["method"] == "Блочный бутстрап (100 симуляций) с учётом волатильности потока"


def test_bootstrap_probability_is_reproducible_with_enough_errors():
    forecast = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=14), "balance": np.linspace(500, 100, 14),
                             "forecast_net": np.full(14, -20.0)})
    errors = np.sin(np.arange(60)) * 10
    first = assess_risk(forecast, reserve=150, residuals=errors, scenarios=200, seed=7)
    second = assess_risk(forecast, reserve=150, residuals=errors, scenarios=200, seed=7)
    assert first["probability"] == second["probability"]
    assert 0 <= first["probability"] <= 1
    assert first["method"] == "Блочный бутстрап (100 симуляций) с учётом волатильности потока"


def test_bootstrap_probability_is_robust_to_residual_offset_and_extreme_outlier():
    forecast = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=14), "balance": np.linspace(500, 100, 14),
                             "forecast_net": np.full(14, -20.0)})
    errors = np.sin(np.arange(60)) * 10
    shifted = errors + 1000
    shifted[0] += 1_000_000

    baseline = assess_risk(forecast, reserve=150, residuals=errors, scenarios=300, seed=11)
    robust = assess_risk(forecast, reserve=150, residuals=shifted, scenarios=300, seed=11)

    assert robust["probability"] == baseline["probability"]


def test_unknown_balance_has_no_success_shaped_risk_numbers():
    forecast = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=2), "balance": [np.nan, np.nan],
                             "forecast_net": [-10, 0]})
    result = assess_risk(forecast, reserve=100)
    assert result["max_deficit"] is None
    assert result["zero_deficit"] is None
    assert result["probability"] is None
    assert result["gap_probability"] is None
    assert result["method"] == "Блочный бутстрап (100 симуляций) с учётом волатильности потока"


def test_risk_fallback_is_reproducible_and_reports_minimum_balance_quantiles():
    forecast = pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=10),
        "balance": np.linspace(1_000, 200, 10),
        "forecast_net": np.full(10, -80.0),
    })
    history = np.array([100, -120, 40, -60, 200, -100, 30, 10], dtype=float)

    first = assess_risk(forecast, reserve=250, historical_net_flows=history, seed=5)
    second = assess_risk(forecast, reserve=250, historical_net_flows=history, seed=5)

    assert first["gap_probability"] == second["gap_probability"]
    assert first["p10"] == second["p10"]
    assert first["p90"] == second["p90"]
    assert first["p10"] <= first["p90"]


def test_warning_recommends_actions_and_names_large_outflows():
    forecast = pd.DataFrame({
        "date": pd.date_range("2026-11-14", periods=3),
        "balance": [300_000, 40_000, -20_000],
        "forecast_net": [-100_000, -260_000, -60_000],
    })
    events = pd.DataFrame([{
        "date": pd.Timestamp("2026-11-15"), "amount": -250_000,
        "status": "ожидается", "description": "Оплата поставки металла",
    }])

    result = assess_risk(forecast, reserve=100_000, events=events)
    warning = result["warning"]

    assert warning["date"] == pd.Timestamp("2026-11-15")
    assert "15.11.2026" in warning["reasons"]
    assert "60 000 ₽" in warning["reasons"]
    assert "Оплата поставки металла — 250 000 ₽" in warning["reasons"]
    assert "перенос оплаты поставщикам на 7–14 дней" in warning["action"]
    assert "запросить предоплату" in warning["action"].lower()
    assert "рассмотреть овердрафт" in warning["action"].lower()
