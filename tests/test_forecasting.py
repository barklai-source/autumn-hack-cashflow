import numpy as np
import pandas as pd

from src.forecasting.evaluation import error_metrics
from src.forecasting.features import feature_row
from src.forecasting.models import forecast_flows
from src.forecasting.models import _fit_ml, baseline_value, forecast_component
from src.forecasting.prediction import apply_cash_flow_scenario, build_forecast
from src.future_events.manager import merge_future_flows, validate_events


def test_forecast_is_daily_and_does_not_read_future_data():
    dates = pd.date_range("2025-01-01", periods=90)
    daily = pd.DataFrame({"date": dates, "inflow": np.where(dates.day_of_week == 1, 100.0, 0.0),
                          "outflow": np.where(dates.day == 1, 50.0, 0.0)})
    forecast = forecast_flows(daily, 30, method="baseline")
    assert len(forecast) == 30
    series = pd.Series(range(100), index=pd.date_range("2025-01-01", periods=100))
    when = pd.Timestamp("2025-03-15")
    before = feature_row(series, when)
    changed = series.copy()
    changed.loc[changed.index >= when] = -9999
    assert feature_row(changed, when) == before


def test_feature_row_adds_calendar_and_robust_history_features_without_future_leakage():
    dates = pd.date_range("2025-01-01", periods=65)
    series = pd.Series(np.arange(65, dtype=float), index=dates)
    when = pd.Timestamp("2025-02-25")

    features = feature_row(series, when)
    changed = series.copy()
    changed.loc[changed.index >= when] = -10000

    assert features["is_weekend"] == 0.0
    assert features["is_month_end"] == 1.0
    assert features["is_tax_day"] == 1.0
    assert features["is_payroll_day"] == 1.0
    assert features["std_28"] == np.std(np.arange(27, 55), ddof=0)
    assert features["median_7"] == 51.0
    assert features["median_28"] == 40.5
    assert features["same_weekday_median"] == 37.5
    assert feature_row(series, pd.Timestamp("2025-02-05"))["is_month_start"] == 1.0
    assert feature_row(series, pd.Timestamp("2025-02-08"))["is_weekend"] == 1.0
    assert feature_row(changed, when) == features


def test_baseline_returns_zero_for_weekday_with_at_least_80_percent_zeroes():
    dates = pd.date_range("2025-01-01", periods=35)
    history = pd.Series(np.where(dates.day_of_week == 0, [100 if index == 5 else 0 for index in range(35)], 10), index=dates, dtype=float)

    assert baseline_value(history, pd.Timestamp("2025-02-10")) == 0.0


def test_ml_fit_clips_outlier_and_uses_absolute_error(monkeypatch):
    captured = {}

    class ModelSpy:
        def __init__(self, **options):
            captured["options"] = options

        def fit(self, features, targets):
            captured["max_target"] = float(targets.max())

    monkeypatch.setattr("src.forecasting.models.HistGradientBoostingRegressor", ModelSpy)
    dates = pd.date_range("2025-01-01", periods=120)
    history = pd.Series(np.full(120, 100.0), index=dates)
    history.iloc[-1] = 100000.0

    _fit_ml(history)

    assert captured["max_target"] < 100000.0
    assert captured["options"]["loss"] == "absolute_error"
    assert captured["options"]["max_iter"] == 80
    assert captured["options"]["early_stopping"] is True


def test_ml_forecast_zeroes_weekends_and_blends_with_baseline(monkeypatch):
    class ModelSpy:
        def predict(self, features):
            return np.array([100.0])

    monkeypatch.setattr("src.forecasting.models._fit_ml", lambda _history: ModelSpy())
    dates = pd.date_range("2025-01-01", periods=35)
    history = pd.Series(np.where(dates.day_of_week >= 5, 0.0, 40.0), index=dates)
    future = pd.date_range("2025-02-05", periods=4)

    forecast = forecast_component(history, future, "ML")

    assert forecast.loc[future[0]] == 85.0
    assert forecast.loc[future[3]] == 0.0


def test_future_event_is_signed_and_not_double_counted_with_confirmed_recurring():
    events = validate_events(pd.DataFrame([{"date": "2025-02-02", "amount": "100,00",
                                             "direction": "списание", "category": "Аренда",
                                             "status": "подтверждено", "account": "A"}]))
    recurring = pd.DataFrame([{"confirmed": True, "accepted": True, "frequency": "ежемесячно", "next_date": pd.Timestamp("2025-02-02"),
                               "amount": -100.0, "account": "A"}])
    flows = merge_future_flows(pd.Timestamp("2025-02-01"), 10, events, recurring, "A")
    assert flows.loc[flows["date"] == pd.Timestamp("2025-02-02"), "event_flow"].iloc[0] == -100
    assert flows.loc[flows["date"] == pd.Timestamp("2025-02-02"), "event_outflow"].iloc[0] == 100
    assert flows.loc[flows["date"] == pd.Timestamp("2025-02-02"), "event_inflow"].iloc[0] == 0
    assert flows.loc[flows["date"] == pd.Timestamp("2025-02-02"), "event_count"].iloc[0] == 1


def test_future_events_support_russian_column_names():
    events = validate_events(pd.DataFrame([{"Дата": "05.02.2025", "Сумма платежа": "2 500",
                                             "Направление": "списание", "Статус": "подтверждено"}]))
    assert events.iloc[0]["amount"] == -2500
    assert events.iloc[0]["status"] == "подтверждено"


def test_recurring_events_from_other_accounts_are_excluded():
    recurring = pd.DataFrame([{"confirmed": True, "accepted": True, "frequency": "ежемесячно",
                               "next_date": pd.Timestamp("2025-02-02"), "amount": -100.0, "account": "B"}])
    flows = merge_future_flows(pd.Timestamp("2025-02-01"), 5, recurring=recurring, account="A")
    assert flows["event_flow"].sum() == 0


def test_build_forecast_accounts_for_balance_and_events():
    ops = pd.DataFrame({"date": pd.to_datetime(["2025-01-01", "2025-01-02"]), "amount": [100, -20],
                        "account": ["A", "A"], "balance": [1100, 1080]})
    ops["direction"] = ["поступление", "списание"]
    ops["counterparty"] = ["x", "y"]
    ops["purpose"] = ["a", "b"]
    ops["inn"] = ["", ""]
    forecast, details = build_forecast(ops, 7)
    assert len(forecast) == 7
    assert details["current_balance"] == 1080
    assert forecast.iloc[0]["date"] == pd.Timestamp("2025-01-03")


def test_scenario_keeps_exact_event_amounts_and_recomputes_daily_balance():
    forecast = pd.DataFrame({
        "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-04"]),
        "baseline_inflow": [110, 100, 100],
        "baseline_outflow": [50, 70, 50],
        "event_inflow": [10, 0, 0],
        "event_outflow": [0, 20, 0],
        "baseline_net_flow": [60, 30, 50],
        "baseline_balance": [1060, 1090, 1140],
    })

    scenario = apply_cash_flow_scenario(
        forecast,
        1000,
        inflow_change_pct=50,
        outflow_change_pct=0,
        daily_net_adjustment=10,
        delay_days=1,
        shock_amount=-25,
        shock_date="2025-01-03",
    )

    assert scenario.loc[0, "inflow"] == 0
    assert scenario.loc[1, "inflow"] == 160
    assert scenario.loc[1, "outflow"] == 95
    assert scenario.loc[1, "net_flow"] == scenario.loc[1, "inflow"] - 95 + 10
    assert scenario.loc[1, "balance"] == 1000 + scenario.loc[0, "net_flow"] + scenario.loc[1, "net_flow"]


def test_forecast_anchor_advances_through_days_without_operations():
    dates = pd.date_range("2025-01-01", periods=35)
    daily = pd.DataFrame({"date": dates, "inflow": np.ones(35), "outflow": np.zeros(35)})
    forecast = forecast_flows(daily, 2, method="baseline", start_date=pd.Timestamp("2025-02-10"))
    assert forecast.iloc[0]["date"] == pd.Timestamp("2025-02-11")


def test_error_metrics_handle_zero_denominator():
    result = error_metrics([0, 0], [1, -1])
    assert result["MAE"] == 1
    assert result["RMSE"] == 1
    assert np.isnan(result["WAPE"])
