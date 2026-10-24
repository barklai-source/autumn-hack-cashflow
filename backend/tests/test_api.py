import pandas as pd
from fastapi.testclient import TestClient

import app.main as main_module
from app.api.routes import api as api_module
from app.core.storage import SQLiteStore
from app.main import app
from app.services.categorization import categorize_operations
from app.services.data_loader import Dataset


def _dataset():
    companies = pd.DataFrame([{
        "company_id": "C001", "name": "Компания Один", "inn": "000100", "legal_form": "ООО",
        "industry": "Торговля", "first_operation_date": "2025-01-01", "last_operation_date": "2025-01-02",
    }, {
        "company_id": "C002", "name": "Компания Два", "inn": "000200", "legal_form": "ИП",
        "industry": "Услуги", "first_operation_date": "2025-01-01", "last_operation_date": "2025-01-02",
    }])
    rows = []
    for company_id, balance in (("C001", 1100), ("C002", 900)):
        rows.append({
            "company_id": company_id, "operation_id": f"{company_id}-1",
            "date": pd.Timestamp("2025-01-01"), "operation_date": pd.Timestamp("2025-01-01"),
            "amount": 100, "signed_amount": 100, "direction": "поступление",
            "counterparty_inn": "000001", "counterparty_name": "Покупатель",
            "payment_purpose": "Оплата от клиента", "balance_eod": balance,
            "balance": balance, "counterparty": "Покупатель", "inn": "000001",
            "purpose": "Оплата от клиента", "account": company_id,
        })
    return Dataset(companies, pd.DataFrame(rows), "ready", "loaded", [])


def test_api_company_isolation_pagination_and_saved_categories(tmp_path, monkeypatch):
    store = SQLiteStore(tmp_path / "test.sqlite")
    monkeypatch.setattr(main_module, "load_dataset", lambda _path: _dataset())
    monkeypatch.setattr(main_module, "SQLiteStore", lambda: store)
    app.state.dataset = _dataset()
    app.state.data_directory = tmp_path
    app.state.store = store
    with TestClient(app) as client:
        assert client.get("/api/health").json()["companies"] == 2
        listing = client.get("/api/companies?page=1&page_size=1").json()
        assert listing["total"] == 2
        assert len(listing["items"]) == 1
        rows = client.get("/api/companies/C001/operations?page_size=1").json()
        assert rows["total"] == 1
        assert rows["needs_review_count"] == 0
        assert rows["items"][0]["company_id"] == "C001"
        operation_id = rows["items"][0]["operation_id"]
        changed = client.patch(f"/api/companies/C001/operations/{operation_id}/category", json={"category": "Аренда"})
        assert changed.status_code == 200
        assert client.get("/api/companies/C001/operations").json()["items"][0]["category"] == "Аренда"
        assert client.get("/api/companies/C002/operations").json()["items"][0]["category"] != "Аренда"
        assert client.get("/api/companies/C001/summary").json()["needs_review_count"] == 0


def test_summary_cache_is_reused_and_invalidated_after_category_change(tmp_path, monkeypatch):
    dataset = _dataset()
    store = SQLiteStore(tmp_path / "summary-cache.sqlite")
    monkeypatch.setattr(main_module, "load_dataset", lambda _path: dataset)
    monkeypatch.setattr(main_module, "SQLiteStore", lambda: store)
    original_calculate = api_module.calculate_forecast
    calls = []
    original_overview = api_module._companies_overview_payload
    overview_calls = []

    def counted_calculate(*args, **kwargs):
        calls.append(1)
        return original_calculate(*args, **kwargs)

    def counted_overview(*args, **kwargs):
        overview_calls.append(1)
        return original_overview(*args, **kwargs)

    monkeypatch.setattr(api_module, "calculate_forecast", counted_calculate)
    monkeypatch.setattr(api_module, "_companies_overview_payload", counted_overview)
    app.state.dataset = dataset
    app.state.data_directory = tmp_path
    app.state.store = store

    with TestClient(app) as client:
        first = client.get("/api/companies/C001/summary")
        repeated = client.get("/api/companies/C001/summary")
        assert first.status_code == repeated.status_code == 200
        assert first.json()["last_actual_date"] == "2025-01-01"
        assert len(calls) == 1
        assert client.get("/api/companies/C001/forecast").status_code == 200
        assert client.get("/api/companies/C001/risks").status_code == 200
        assert client.get("/api/companies/C001/model-evaluation").status_code == 200
        assert len(calls) == 1
        assert client.get("/api/companies/overview").status_code == 200
        assert client.get("/api/companies/overview").status_code == 200
        assert len(overview_calls) == 1

        client.patch(
            "/api/companies/C001/operations/C001-1/category",
            json={"category": "Аренда"},
        )
        refreshed = client.get("/api/companies/C001/summary")
        assert len(calls) == 2

        created_event = client.post("/api/companies/C001/events", json={
            "date": "2025-02-01", "amount": 100, "direction": "списание",
            "category": "Аренда", "event_type": "тест",
            "description": "Аренда", "source": "тест", "status": "Ожидается",
        })
        assert created_event.status_code == 201
        refreshed_after_event = client.get("/api/companies/C001/summary")
        assert refreshed_after_event.status_code == 200
        assert len(calls) == 3

        imported_events = client.post(
            "/api/companies/C001/events/import",
            files={"file": (
                "future.csv",
                "дата;сумма;направление\n01.03.2025;200;списание\n".encode("utf-8"),
                "text/csv",
            )},
        )
        assert imported_events.status_code == 200
        assert client.get("/api/companies/C001/summary").status_code == 200
        assert len(calls) == 4
        assert client.get("/api/companies/overview").status_code == 200
        assert len(overview_calls) == 2
        assert app.state.result_cache.company_data_version["C001"] == 3
        assert app.state.result_cache.company_data_version["__all__"] == 3

    assert refreshed.status_code == 200


def test_api_review_count_is_company_wide_and_survives_category_filter(tmp_path, monkeypatch):
    dataset = _dataset()
    dataset.operations.loc[dataset.operations["company_id"] == "C001", "purpose"] = "Оплата"
    dataset.operations.loc[dataset.operations["company_id"] == "C001", "payment_purpose"] = "Оплата"
    monkeypatch.setattr(main_module, "load_dataset", lambda _path: dataset)
    test_store = SQLiteStore(tmp_path / "review-count.sqlite")
    monkeypatch.setattr(main_module, "SQLiteStore", lambda *_args, **_kwargs: test_store)
    app.state.dataset = dataset
    app.state.data_directory = tmp_path
    app.state.store = test_store

    with TestClient(app) as client:
        filtered = client.get("/api/companies/C001/operations", params={"category": "Требует проверки"}).json()
        other_company = client.get("/api/companies/C002/operations").json()
        summary_payload = client.get("/api/companies/C001/summary").json()

    assert filtered["total"] == 1, filtered
    assert filtered["needs_review_count"] == 1
    assert other_company["needs_review_count"] == 0
    assert summary_payload["needs_review_count"] == 1


def test_api_event_create_edit_cancel_are_company_scoped(tmp_path, monkeypatch):
    store = SQLiteStore(tmp_path / "events.sqlite")
    monkeypatch.setattr(main_module, "load_dataset", lambda _path: _dataset())
    monkeypatch.setattr(main_module, "SQLiteStore", lambda: store)
    app.state.dataset = _dataset()
    app.state.data_directory = tmp_path
    app.state.store = store
    payload = {
        "date": "2025-02-01", "amount": 1234, "direction": "списание",
        "category": "Аренда", "event_type": "счёт поставщика",
        "description": "Оплата аренды", "source": "тест", "status": "Ожидается",
    }
    with TestClient(app) as client:
        created = client.post("/api/companies/C001/events", json=payload)
        assert created.status_code == 201
        event_id = created.json()["id"]
        other_company_events = client.get("/api/companies/C002/events").json()["items"]
        assert len(other_company_events) == 6
        assert all(item["company_id"] == "C002" and item["id"] != event_id for item in other_company_events)
        updated = client.patch(f"/api/companies/C001/events/{event_id}", json={"status": "Подтверждено"})
        assert updated.json()["status"] == "Подтверждено"
        cancelled = client.delete(f"/api/companies/C001/events/{event_id}")
        assert cancelled.json()["status"] == "Отменено"


def test_api_imports_event_description_from_csv(tmp_path, monkeypatch):
    store = SQLiteStore(tmp_path / "imported-events.sqlite")
    monkeypatch.setattr(main_module, "load_dataset", lambda _path: _dataset())
    monkeypatch.setattr(main_module, "SQLiteStore", lambda: store)
    app.state.dataset = _dataset()
    app.state.data_directory = tmp_path
    app.state.store = store
    csv_data = "дата;сумма;направление;описание\n01.02.2025;2345;списание;Оплата аренды\n".encode("utf-8")

    with TestClient(app) as client:
        response = client.post(
            "/api/companies/C001/events/import",
            files={"file": ("events.csv", csv_data, "text/csv")},
        )

    assert response.status_code == 200
    imported = response.json()["items"][0]
    assert imported["description"] == "Оплата аренды"
    assert imported["amount"] == 2345


def test_event_csv_skips_test_amount_and_reset_demo_rebuilds_six_events(tmp_path, monkeypatch):
    dataset = _dataset()
    store = SQLiteStore(tmp_path / "reset-demo.sqlite")
    junk = {
        "date": pd.Timestamp("2025-02-01").date(), "amount": 1234,
        "direction": "списание", "category": "Прочие расходы", "event_type": "Аренда",
        "description": "Оплата аренды", "source": "тест", "status": "Ожидается",
    }
    for _ in range(10):
        store.create_event("C001", junk)
    monkeypatch.setattr(main_module, "load_dataset", lambda _path: dataset)
    monkeypatch.setattr(main_module, "SQLiteStore", lambda: store)
    app.state.dataset = dataset
    app.state.data_directory = tmp_path
    app.state.store = store

    with TestClient(app) as client:
        startup_events = store.list_events("C001")
        assert len(startup_events) == 6
        assert len({event["description"] for event in startup_events}) == 6
        assert not any(event["amount"] == 1234 for event in startup_events)

        imported = client.post(
            "/api/companies/C001/events/import",
            files={"file": ("test.csv", "дата;сумма;направление\n01.02.2025;1234;списание\n".encode("utf-8"), "text/csv")},
        )
        assert imported.status_code == 200
        assert imported.json()["imported"] == 0
        assert not any(event["amount"] == 1234 for event in store.list_events("C001"))

        reset = client.post("/api/companies/C001/events/reset-demo")

    assert reset.status_code == 200
    assert app.state.result_cache.company_data_version["C001"] == 1
    items = reset.json()["items"]
    assert len(items) == 6
    assert len({item["description"] for item in items}) == 6
    assert {item["date"] for item in items} == {
        (pd.Timestamp("2025-01-01") + pd.Timedelta(days=days)).date().isoformat()
        for days in (2, 6, 10, 14, 19, 25)
    }


def test_model_evaluation_returns_one_row_per_date_with_method_columns(tmp_path, monkeypatch):
    dataset = _dataset()
    rows = []
    balance = 10000
    for day in pd.date_range("2025-01-01", periods=140):
        signed_amount = 100 if day.day % 2 else -80
        balance += signed_amount
        rows.append({
            "company_id": "C001", "operation_id": day.strftime("C001-%Y%m%d"),
            "date": day, "operation_date": day, "amount": abs(signed_amount),
            "signed_amount": signed_amount,
            "direction": "поступление" if signed_amount > 0 else "списание",
            "payment_purpose": "Оплата от клиента", "balance_eod": balance,
            "balance": balance, "account": "C001", "purpose": "Оплата от клиента",
            "counterparty": "Покупатель", "inn": "000001",
        })
    dataset.operations = pd.DataFrame(rows)
    store = SQLiteStore(tmp_path / "model-evaluation.sqlite")
    monkeypatch.setattr(main_module, "load_dataset", lambda _path: dataset)
    monkeypatch.setattr(main_module, "SQLiteStore", lambda: store)
    app.state.dataset = dataset
    app.state.data_directory = tmp_path
    app.state.store = store

    with TestClient(app) as client:
        response = client.get("/api/companies/C001/model-evaluation")
        forecast = client.get("/api/companies/C001/forecast?horizon=30")
        adjusted_forecast = client.get(
            "/api/companies/C001/forecast?horizon=30&daily_net_adjustment=1000",
        )
        risk = client.get("/api/companies/C001/risks?horizon=30")
        summary = client.get("/api/companies/C001/summary?horizon=30")
        invalid_horizon = client.get("/api/companies/C001/forecast?horizon=31")
        invalid_scenario = client.get(
            "/api/companies/C001/forecast?horizon=30&inflow_change_pct=201",
        )

    assert response.status_code == 200
    assert forecast.status_code == 200
    assert len(forecast.json()["items"]) == 30
    base_payload = forecast.json()
    adjusted_payload = adjusted_forecast.json()
    assert adjusted_forecast.status_code == 200
    assert len(base_payload["items"]) == len(adjusted_payload["items"]) == 30
    assert base_payload["total_net_flow"] == base_payload["baseline_total_net_flow"]
    assert adjusted_payload["total_net_flow"] - adjusted_payload["baseline_total_net_flow"] == 30000
    assert all(item["net_flow"] == item["baseline_net_flow"] for item in base_payload["items"])
    assert all(item["balance"] == item["baseline_balance"] for item in base_payload["items"])
    assert risk.status_code == 200
    assert risk.json()["horizon_days"] == 30
    assert summary.status_code == 200
    assert invalid_horizon.status_code == 422
    assert invalid_scenario.status_code == 422
    payload = response.json()
    assert payload["metrics"]
    assert {row["method"] for row in payload["metrics"]} == {"baseline", "ML"}
    assert {row["horizon_days"] for row in payload["balance_horizons"]} == {7, 30, 90}
    assert payload["backtest"]
    assert {"date", "actual_net", "baseline", "ML"} <= payload["backtest"][0].keys()


def test_api_reports_missing_company_and_rejects_invalid_category(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "load_dataset", lambda _path: _dataset())
    app.state.dataset = _dataset()
    app.state.data_directory = tmp_path
    app.state.store = SQLiteStore(tmp_path / "errors.sqlite")
    with TestClient(app) as client:
        assert client.get("/api/companies/C999/operations").status_code == 404
        assert client.patch("/api/companies/C001/operations/C001-1/category", json={"category": "invalid"}).status_code == 422


def test_login_roles_and_company_data_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "load_dataset", lambda _path: _dataset())
    test_store = SQLiteStore(tmp_path / "auth.sqlite")
    monkeypatch.setattr(main_module, "SQLiteStore", lambda *_args, **_kwargs: test_store)

    with TestClient(app) as client:
        admin_login = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        company_login = client.post("/api/auth/login", json={"username": "c001", "password": "1234"})
        company_password_login = client.post("/api/auth/login", json={"username": "C001", "password": "C001"})
        inn_login = client.post("/api/auth/login", json={"username": "000100", "password": "1234"})
        demo_inn_login = client.post("/api/auth/login", json={"username": "7701001001", "password": "1234"})
        invalid_login = client.post("/api/auth/login", json={"username": "C001", "password": "wrong"})

        admin_headers = {"Authorization": f"Bearer {admin_login.json()['token']}"}
        company_headers = {"Authorization": f"Bearer {company_login.json()['token']}"}

        assert admin_login.status_code == 200
        assert admin_login.json()["role"] == "admin"
        assert company_login.status_code == 200
        assert company_login.json()["role"] == "company"
        assert company_login.json()["company_id"] == "C001"
        assert company_password_login.json()["company_id"] == "C001"
        assert inn_login.json()["company_id"] == "C001"
        assert demo_inn_login.json()["company_id"] == "C001"
        assert demo_inn_login.json()["inn"] == "7701001001"
        assert invalid_login.status_code == 401
        assert client.get("/api/auth/me").status_code == 401
        current_user = client.get("/api/auth/me", headers=company_headers).json()
        assert current_user["company_id"] == "C001"
        assert current_user["inn"] == "000100"
        tampered_headers = {"Authorization": f"Bearer {company_login.json()['token']}x"}
        assert client.get("/api/auth/me", headers=tampered_headers).status_code == 401
        assert len(client.get("/api/companies", headers=admin_headers).json()["items"]) == 2
        company_listing = client.get("/api/companies", headers=company_headers).json()
        assert [item["company_id"] for item in company_listing["items"]] == ["C001"]
        assert company_listing["items"][0]["inn"] == "000100"
        assert [item["company_id"] for item in client.get("/api/companies/overview", headers=company_headers).json()["rows"]] == ["C001"]
        assert client.get("/api/companies/C001/operations", headers=company_headers).status_code == 200
        assert client.get("/api/companies/C002/operations", headers=company_headers).status_code == 403


def test_inn_lookup_registration_and_registered_login(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "load_dataset", lambda _path: _dataset())
    test_store = SQLiteStore(tmp_path / "registered-users.sqlite")
    monkeypatch.setattr(main_module, "SQLiteStore", lambda *_args, **_kwargs: test_store)

    with TestClient(app) as client:
        found = client.get("/api/auth/lookup-inn", params={"inn": "7701002002"})
        unknown = client.get("/api/auth/lookup-inn", params={"inn": "7712345678"})
        registered = client.post("/api/auth/register", json={
            "inn": "7712345678", "password": "test-password", "company_name": "ООО Новая компания",
        })
        login = client.post("/api/auth/login", json={
            "username": "7712345678", "password": "test-password",
        })
        duplicate = client.post("/api/auth/register", json={
            "inn": "7712345678", "password": "another-password",
        })

    assert found.status_code == 200
    assert found.json()["found"] is True
    assert found.json()["company_id"] == "C002"
    assert unknown.status_code == 200 and unknown.json()["found"] is False
    assert registered.status_code == 200
    assert registered.json()["inn"] == "7712345678"
    assert registered.json()["company_id"] == "C001"
    assert login.status_code == 200 and login.json()["company_id"] == "C001"
    assert duplicate.status_code == 409
    stored_user = test_store.get_user("7712345678")
    assert stored_user is not None and stored_user["password"].startswith("pbkdf2_sha256$")
    assert stored_user["password"] != "test-password"


def test_demo_companies_are_dynamic_and_admin_can_reload_dataset(tmp_path, monkeypatch):
    initial_dataset = _dataset()
    refreshed_dataset = _dataset()
    refreshed_dataset.companies = refreshed_dataset.companies.iloc[[1]].copy()
    refreshed_dataset.companies.loc[:, "company_id"] = "ORG-NEW"
    refreshed_dataset.companies.loc[:, "name"] = "Новая организация"
    refreshed_dataset.companies.loc[:, "inn"] = "7700123456"
    refreshed_dataset.operations.loc[:, "company_id"] = "ORG-NEW"
    monkeypatch.setattr(main_module, "load_dataset", lambda _path: initial_dataset)
    store = SQLiteStore(tmp_path / "reload-dataset.sqlite")
    monkeypatch.setattr(main_module, "SQLiteStore", lambda *_args, **_kwargs: store)
    monkeypatch.setattr(api_module, "load_dataset", lambda _path: refreshed_dataset)

    with TestClient(app) as client:
        assert client.post("/api/admin/reload-dataset").status_code == 401
        demo_companies = client.get("/api/auth/demo-companies")
        admin = client.post("/api/auth/login", json={"username": "admin", "password": "admin"}).json()
        reloaded = client.post(
            "/api/admin/reload-dataset",
            headers={"Authorization": f"Bearer {admin['token']}"},
        )

    assert [row["company_id"] for row in demo_companies.json()["items"]] == ["C001", "C002"]
    assert reloaded.status_code == 200
    assert reloaded.json()["total"] == 1
    assert reloaded.json()["companies"][0]["company_id"] == "ORG-NEW"
    assert app.state.dataset.companies.iloc[0]["company_id"] == "ORG-NEW"
    assert app.state.result_cache.company_data_version == {"ORG-NEW": 0}


def test_backend_classifier_uses_manual_overrides_to_resolve_uncertain_operations(tmp_path):
    rows = []
    for index in range(4):
        rows.append({
            "operation_id": f"rent-{index}", "company_id": "C001", "amount": -100,
            "purpose": f"commercial premises office monthly lease {index}", "counterparty": "", "inn": "",
        })
        rows.append({
            "operation_id": f"supply-{index}", "company_id": "C001", "amount": -100,
            "purpose": f"industrial raw materials manufacturing shipment {index}", "counterparty": "", "inn": "",
        })
    rows.append({
        "operation_id": "unknown-1", "company_id": "C001", "amount": -100,
        "purpose": "commercial premises monthly lease", "counterparty": "", "inn": "",
    })
    rows.append({
        "operation_id": "unknown-2", "company_id": "C001", "amount": -100,
        "purpose": "unrelated unrecognized payment", "counterparty": pd.NA, "inn": pd.NA,
    })
    store = SQLiteStore(tmp_path / "classifier.sqlite")
    for index in range(4):
        store.set_category("C001", f"rent-{index}", "Аренда")
        store.set_category("C001", f"supply-{index}", "Закупки и поставщики")

    categorized = categorize_operations(pd.DataFrame(rows), store)
    predicted = categorized.loc[categorized["operation_id"] == "unknown-1"].iloc[0]

    assert predicted["category"] == "Аренда"
    assert predicted["category_method"] == "ML-классификатор"
    assert predicted["confidence"] >= 0.65
    assert not predicted["needs_review"]
    still_uncertain = categorized.loc[categorized["operation_id"] == "unknown-2"].iloc[0]
    assert still_uncertain["category"] == "Требует проверки"
    assert still_uncertain["needs_review"]
