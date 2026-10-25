import sqlite3

import pandas as pd

from app.services import data_loader
from app.services.data_loader import load_dataset, validate_daily_balances
from app.core.storage import SQLiteStore


def test_loads_utf8_bom_semicolon_inns_and_signed_operations(tmp_path):
    (tmp_path / "companies.csv").write_text(
        "\ufeffcompany_id;name;inn;legal_form;industry\nC001;Тест;000123456789;ООО;Торговля\n",
        encoding="utf-8",
    )
    operations_dir = tmp_path / "statements"
    operations_dir.mkdir()
    (operations_dir / "C001.csv").write_text(
        "\ufeffoperation_id;operation_date;amount;direction;counterparty_inn;counterparty_name;payment_purpose;balance_eod\n"
        "O1;2025-01-02;1000;Поступление;0000012345;Клиент;Оплата;5500\n"
        "O2;2025-01-02;500;Списание;0000098765;Поставщик;Закупка;5500\n",
        encoding="utf-8",
    )
    dataset = load_dataset(tmp_path)
    assert dataset.status == "ready"
    assert dataset.companies.iloc[0]["inn"] == "000123456789"
    assert dataset.operations.iloc[0]["counterparty_inn"] == "0000012345"
    assert sorted(dataset.operations["signed_amount"].tolist()) == [-500, 1000]
    balances = validate_daily_balances(dataset.operations)
    assert balances.iloc[0]["opening_balance"] == 5000
    assert balances.iloc[0]["operations"] == 2
    assert dataset.daily_flows["C001"]["net_flow"].tolist() == [500]


def test_missing_company_inns_receive_deterministic_ten_digit_values(tmp_path):
    (tmp_path / "companies.csv").write_text(
        "company_id;name;inn\nC001;Первый;\nC002;Второй;\nC150;Последний;\n",
        encoding="utf-8-sig",
    )
    statements = tmp_path / "statements"
    statements.mkdir()
    (statements / "C001.csv").write_text(
        "operation_id;operation_date;amount;direction;balance_eod\n"
        "O1;2025-01-01;10;Поступление;10\n",
        encoding="utf-8-sig",
    )

    inns = load_dataset(tmp_path).companies.set_index("company_id")["inn"]

    assert inns.to_dict() == {
        "C001": "7701001001",
        "C002": "7701002002",
        "C150": "7701000150",
    }


def test_statement_loader_accepts_arbitrary_company_ids(tmp_path):
    (tmp_path / "companies.csv").write_text(
        "company_id;name\nORG-ALPHA;Альфа\n", encoding="utf-8-sig",
    )
    statements = tmp_path / "statements"
    statements.mkdir()
    (statements / "ORG-ALPHA.csv").write_text(
        "operation_id;operation_date;amount;direction;balance_eod\n"
        "O1;2024-03-15;100;Поступление;100\n",
        encoding="utf-8-sig",
    )

    dataset = load_dataset(tmp_path)

    assert dataset.companies.iloc[0]["company_id"] == "ORG-ALPHA"
    assert len(dataset.companies.iloc[0]["inn"]) == 10
    assert dataset.operations.iloc[0]["company_id"] == "ORG-ALPHA"
    assert dataset.operations.iloc[0]["date"] == pd.Timestamp("2024-03-15")


def test_csv_files_are_parsed_once_until_their_metadata_changes(tmp_path, monkeypatch):
    (tmp_path / "companies.csv").write_text(
        "company_id;name\nC001;Test\n", encoding="utf-8-sig",
    )
    statements = tmp_path / "statements"
    statements.mkdir()
    statement_path = statements / "C001.csv"
    statement_path.write_text(
        "operation_id;operation_date;amount;direction;balance_eod\n"
        "O1;2025-01-01;10;Поступление;20\n",
        encoding="utf-8-sig",
    )
    original_read_csv = pd.read_csv
    calls = []
    daily_calls = []
    original_daily_flows = data_loader._daily_flows

    def counted_read_csv(path, *args, **kwargs):
        calls.append(str(path))
        return original_read_csv(path, *args, **kwargs)

    def counted_daily_flows(operations):
        daily_calls.append(1)
        return original_daily_flows(operations)

    monkeypatch.setattr(data_loader.pd, "read_csv", counted_read_csv)
    monkeypatch.setattr(data_loader, "_daily_flows", counted_daily_flows)

    load_dataset(tmp_path)
    load_dataset(tmp_path)

    assert len(calls) == 2
    assert len(daily_calls) == 1


def test_combined_source_takes_precedence_over_duplicate_individual_files(tmp_path):
    (tmp_path / "companies.csv").write_text("company_id;name\nC001;Test\n", encoding="utf-8-sig")
    (tmp_path / "all_operations.csv").write_text(
        "company_id;operation_id;operation_date;amount;direction;counterparty_inn;counterparty_name;payment_purpose;balance_eod\n"
        "C001;O1;2025-01-01;10;Поступление;001;Buyer;Sale;20\n",
        encoding="utf-8-sig",
    )
    statements = tmp_path / "statements"
    statements.mkdir()
    (statements / "C001.csv").write_text(
        "operation_id;operation_date;amount;direction;counterparty_inn;counterparty_name;payment_purpose;balance_eod\n"
        "O1;2025-01-01;10;Поступление;001;Buyer;Sale;20\n",
        encoding="utf-8-sig",
    )
    dataset = load_dataset(tmp_path)
    assert len(dataset.operations) == 1
    assert dataset.operations.iloc[0]["company_id"] == "C001"


def test_missing_dataset_returns_a_diagnostic_instead_of_crashing(tmp_path):
    result = load_dataset(tmp_path)
    assert result.status == "missing"
    assert "companies.csv" in result.message
    assert result.operations.empty


def test_csv_loader_accepts_supported_encodings_delimiters_and_missing_optional_values(tmp_path):
    cases = (
        ("utf-8", ","),
        ("utf-8-sig", ";"),
        ("cp1251", "\t"),
    )
    for index, (encoding, delimiter) in enumerate(cases):
        directory = tmp_path / str(index)
        directory.mkdir()
        company_csv = (
            f" company_id {delimiter} name {delimiter} inn\n"
            f"C{index + 1:03d}{delimiter}Тестовая компания{delimiter}\n"
        )
        operations_csv = (
            f" company_id {delimiter} operation_date {delimiter} amount {delimiter} direction "
            f"{delimiter} balance_eod {delimiter} counterparty_inn {delimiter} payment_purpose\n"
            f"C{index + 1:03d}{delimiter}2025-03-01{delimiter}1500{delimiter}Поступление"
            f"{delimiter}2500{delimiter}{delimiter}\n"
        )
        (directory / "companies.csv").write_text(company_csv, encoding=encoding)
        (directory / "all_operations.csv").write_text(operations_csv, encoding=encoding)

        dataset = load_dataset(directory)

        assert dataset.status == "ready"
        assert len(dataset.operations) == 1
        assert dataset.operations.iloc[0]["counterparty_inn"] == ""
        assert dataset.operations.iloc[0]["payment_purpose"] == ""
        assert dataset.operations.iloc[0]["operation_id"]
        assert len(dataset.companies.iloc[0]["inn"]) == 10


def test_daily_balance_validation_does_not_report_gaps_as_zero_flow_days():
    rows = pd.DataFrame({
        "company_id": ["A", "A"], "date": pd.to_datetime(["2025-01-01", "2025-01-04"]),
        "signed_amount": [100, -20], "balance_eod": [1100, 1080], "operation_id": ["1", "2"],
    })
    result = validate_daily_balances(rows)
    assert len(result) == 2
    assert result["date"].tolist() == list(pd.to_datetime(["2025-01-01", "2025-01-04"]))
    assert result["balance_consistent"].all()


def test_store_indexes_events_and_manual_categories_by_company_and_date(tmp_path):
    store = SQLiteStore(tmp_path / "indexes.sqlite")

    with store.connection() as connection:
        event_indexes = {row["name"] for row in connection.execute("PRAGMA index_list(future_events)")}
        category_indexes = {row["name"] for row in connection.execute("PRAGMA index_list(category_overrides)")}

    assert "idx_events_company_date" in event_indexes
    assert "idx_category_overrides_company_updated_at" in category_indexes


def test_store_migrates_legacy_users_and_event_owner_scope(tmp_path):
    database = tmp_path / "legacy.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE users (
                inn TEXT PRIMARY KEY,
                company_id TEXT NOT NULL,
                company_name TEXT NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin', 'company'))
            );
            INSERT INTO users VALUES ('7701001001', 'C001', 'Компания', 'legacy-hash', 'company');
            CREATE TABLE future_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id TEXT NOT NULL,
                event_date TEXT NOT NULL,
                amount REAL NOT NULL,
                direction TEXT NOT NULL,
                category TEXT NOT NULL,
                event_type TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'ручной ввод',
                status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)

    store = SQLiteStore(database)
    legacy_user = store.get_user("7701001001")

    assert legacy_user is not None and legacy_user["role"] == "company"
    store.create_user({
        "inn": "7712345678", "company_id": "C001", "company_name": "Новая",
        "password": "hashed", "role": "owner",
    })
    with store.connection() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(future_events)")}

    assert store.get_user("7712345678")["role"] == "owner"
    assert {"owner_inn", "counterparty_inn", "counterparty_name"} <= columns


def test_event_cleanup_removes_test_amounts_and_same_company_duplicates(tmp_path):
    store = SQLiteStore(tmp_path / "event-cleanup.sqlite")
    event = {
        "date": pd.Timestamp("2025-02-01").date(), "amount": 1000,
        "direction": "списание", "category": "Аренда", "event_type": "Счёт",
        "description": "Аренда помещения", "source": "тест", "status": "Ожидается",
    }
    store.create_event("C001", event)
    store.create_event("C001", event)
    store.create_event("C002", event)
    store.create_event("C001", {**event, "amount": 1234})

    deleted = store.cleanup_events()

    assert deleted == 2
    assert len(store.list_events("C001")) == 1
    assert len(store.list_events("C002")) == 1


def test_demo_events_are_six_unique_entries_after_last_actual_date(tmp_path):
    store = SQLiteStore(tmp_path / "demo-events.sqlite")
    last_actual = pd.Timestamp("2025-12-31").date()

    events = store.reset_demo_events("C001", last_actual)

    assert len(events) == 6
    assert len({event["description"] for event in events}) == 6
    assert [pd.Timestamp(event["event_date"]).date() - last_actual for event in events] == [
        pd.Timedelta(days=days) for days in (2, 6, 10, 14, 19, 25)
    ]
