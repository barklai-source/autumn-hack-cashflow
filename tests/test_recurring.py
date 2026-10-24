import pandas as pd

from src.recurring.detector import detect_recurring


def test_detects_monthly_recurring_series_from_three_observations():
    frame = pd.DataFrame({
        "date": pd.to_datetime(["2025-01-01", "2025-01-31", "2025-03-02"]),
        "amount": [-1000.0, -1010.0, -990.0],
        "counterparty": ["Landlord"] * 3,
        "inn": ["123"] * 3,
        "purpose": ["Rent"] * 3,
        "category": ["Аренда"] * 3,
        "account": ["A"] * 3,
    })
    result = detect_recurring(frame)
    assert len(result) == 1
    assert result.iloc[0]["frequency"] == "ежемесячно"
    assert result.iloc[0]["observations"] == 3


def test_two_observations_are_not_enough():
    frame = pd.DataFrame({"date": pd.to_datetime(["2025-01-01", "2025-02-01"]), "amount": [-10, -10],
                          "counterparty": ["X", "X"], "inn": ["", ""], "purpose": ["x", "x"], "account": ["a", "a"]})
    assert detect_recurring(frame).empty


def test_reliable_recurring_series_are_auto_confirmed():
    frame = pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=5, freq="30D"),
        "amount": [-1000.0] * 5,
        "counterparty": ["Landlord"] * 5,
        "inn": ["123"] * 5,
        "purpose": ["Rent"] * 5,
        "category": ["Аренда"] * 5,
        "account": ["A"] * 5,
    })

    result = detect_recurring(frame)

    assert len(result) == 1
    assert result.iloc[0]["confidence"] >= 0.75
    assert result.iloc[0]["confirmed"]
