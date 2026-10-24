import pandas as pd
from io import StringIO

from src.data import loader
from src.data.loader import daily_balances, detect_columns, normalize_statement, read_statement


def test_read_csv_detects_semicolon_and_decimal_comma():
    frame = read_statement(StringIO("Дата;Сумма;Направление\n01.03.2025;1.234,50;Поступление\n"), "statement.csv")
    assert frame.iloc[0]["Сумма"] == "1.234,50"
    result = normalize_statement(frame)
    assert result.operations.iloc[0]["amount"] == 1234.5


def test_read_statement_file_is_cached(tmp_path, monkeypatch):
    path = tmp_path / "statement.csv"
    path.write_text("Дата;Сумма\n01.03.2025;100\n", encoding="utf-8-sig")
    original_read_csv = pd.read_csv
    calls = []

    def counted_read_csv(*args, **kwargs):
        calls.append(args[0])
        return original_read_csv(*args, **kwargs)

    monkeypatch.setattr(loader.pd, "read_csv", counted_read_csv)

    read_statement(str(path), "statement.csv")
    read_statement(str(path), "statement.csv")

    assert len(calls) == 1


def test_russian_csv_columns_and_direction_signs():
    raw = pd.DataFrame({
        "Дата операции": ["01.02.2025", "01.02.2025"],
        "Сумма": ["1 250,50", "-300,00"],
        "Направление": ["Поступление", "Списание"],
        "Остаток на конец дня": ["10 950,50", "10 950,50"],
    })
    result = normalize_statement(raw)
    assert result.operations["amount"].tolist() == [1250.5, -300.0]
    daily, warnings = daily_balances(result.operations)
    assert daily.loc[0, "opening_balance"] == 10000
    assert warnings == []


def test_column_mapping_and_rejected_rows():
    raw = pd.DataFrame({"Booked": ["2025-01-02", "bad"], "Value": ["20.00", "x"]})
    assert detect_columns(["Дата платежа", "Сумма"]) == {"date": "Дата платежа", "amount": "Сумма"}
    result = normalize_statement(raw, {"date": "Booked", "amount": "Value"})
    assert len(result.operations) == 1
    assert len(result.rejected) == 1


def test_duplicate_rows_are_reported_not_double_counted():
    raw = pd.DataFrame({"Дата": ["2025-01-02"] * 2, "Сумма": ["100", "100"], "Назначение": ["Оплата", "Оплата"]})
    result = normalize_statement(raw)
    assert len(result.operations) == 1
    assert result.duplicate_count == 1
    assert result.rejected.iloc[0]["reason"] == "дубликат операции"


def test_empty_statement_is_valid_empty_result_and_missing_schema_is_reported():
    empty = normalize_statement(pd.DataFrame(columns=["Дата", "Сумма"]))
    assert empty.operations.empty
    assert empty.warnings
    try:
        normalize_statement(pd.DataFrame({"Контрагент": ["Поставщик"]}))
    except ValueError as error:
        assert "обязательные поля" in str(error)
    else:
        raise AssertionError("Missing required columns must be reported.")
