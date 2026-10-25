"""SQLite persistence for company-specific user changes and future events."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from app.core.config import DATABASE_PATH

DEMO_EVENTS = (
    {
        "offset": 2,
        "amount": 480000,
        "direction": "поступление",
        "category": "Выручка и поступления от клиентов",
        "event_type": "Оплата по договору",
        "description": "Оплата от покупателя по договору поставки №48",
        "status": "Подтверждено",
    },
    {
        "offset": 6,
        "amount": 145000,
        "direction": "списание",
        "category": "Аренда",
        "event_type": "Аренда",
        "description": "Аренда офисного и складского помещения",
        "status": "Ожидается",
    },
    {
        "offset": 10,
        "amount": 320000,
        "direction": "списание",
        "category": "Фонд оплаты труда",
        "event_type": "Зарплата",
        "description": "Выплата аванса и заработной платы сотрудникам",
        "status": "Подтверждено",
    },
    {
        "offset": 14,
        "amount": 215000,
        "direction": "списание",
        "category": "Налоги и обязательные платежи",
        "event_type": "Налоговый платёж",
        "description": "Единый налоговый платёж (ЕНП / НДС)",
        "status": "Ожидается",
    },
    {
        "offset": 19,
        "amount": 190000,
        "direction": "списание",
        "category": "Закупки и поставщики",
        "event_type": "Закупка материалов",
        "description": "Закупка партии сырья и материалов по УПД",
        "status": "Ожидается",
    },
    {
        "offset": 25,
        "amount": 275000,
        "direction": "поступление",
        "category": "Выручка и поступления от клиентов",
        "event_type": "Поступление по эквайрингу",
        "description": "Поступление выручки по эквайрингу и СБП",
        "status": "Подтверждено",
    },
)


class SQLiteStore:
    def __init__(self, path: Path = DATABASE_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS category_overrides (
                    company_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (company_id, operation_id)
                );
                CREATE TABLE IF NOT EXISTS recurring_overrides (
                    company_id TEXT NOT NULL,
                    recurring_id TEXT NOT NULL,
                    confirmed INTEGER NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (company_id, recurring_id)
                );
                CREATE TABLE IF NOT EXISTS users (
                    inn TEXT PRIMARY KEY,
                    company_id TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    password TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('admin', 'owner', 'company'))
                );
                CREATE TABLE IF NOT EXISTS future_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_id TEXT NOT NULL,
                    owner_inn TEXT NOT NULL DEFAULT '',
                    event_date TEXT NOT NULL,
                    amount REAL NOT NULL CHECK (amount > 0),
                    direction TEXT NOT NULL CHECK (direction IN ('поступление', 'списание')),
                    category TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    counterparty_inn TEXT NOT NULL DEFAULT '',
                    counterparty_name TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'ручной ввод',
                    status TEXT NOT NULL CHECK (status IN ('Ожидается', 'Подтверждено', 'Исполнено', 'Отменено')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_events_company_date ON future_events(company_id, event_date);
                CREATE INDEX IF NOT EXISTS idx_category_overrides_company_updated_at
                    ON category_overrides(company_id, updated_at);
            """)
            user_table = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'",
            ).fetchone()
            if user_table and "'owner'" not in str(user_table["sql"]):
                connection.executescript("""
                    ALTER TABLE users RENAME TO users_legacy;
                    CREATE TABLE users (
                        inn TEXT PRIMARY KEY,
                        company_id TEXT NOT NULL,
                        company_name TEXT NOT NULL,
                        password TEXT NOT NULL,
                        role TEXT NOT NULL CHECK (role IN ('admin', 'owner', 'company'))
                    );
                    INSERT INTO users(inn, company_id, company_name, password, role)
                    SELECT inn, company_id, company_name, password, role FROM users_legacy;
                    DROP TABLE users_legacy;
                """)
            event_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(future_events)").fetchall()
            }
            for column in ("owner_inn", "counterparty_inn", "counterparty_name"):
                if column not in event_columns:
                    connection.execute(
                        f"ALTER TABLE future_events ADD COLUMN {column} TEXT NOT NULL DEFAULT ''",
                    )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_company_owner_date "
                "ON future_events(company_id, owner_inn, event_date)",
            )

    def get_user(self, inn: str) -> dict | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT inn, company_id, company_name, password, role FROM users WHERE inn = ?",
                (inn,),
            ).fetchone()
        return None if row is None else dict(row)

    def create_user(self, user: dict[str, str]) -> None:
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO users(inn, company_id, company_name, password, role)
                   VALUES (?, ?, ?, ?, ?)""",
                (user["inn"], user["company_id"], user["company_name"], user["password"], user["role"]),
            )

    def cleanup_events(self, company_id: str | None = None, owner_inn: str | None = None) -> int:
        scope_parts = []
        parameters: tuple = ()
        if company_id is not None:
            scope_parts.append("company_id = ?")
            parameters += (company_id,)
        if owner_inn is not None:
            scope_parts.append("owner_inn = ?")
            parameters += (owner_inn,)
        scope = " WHERE " + " AND ".join(scope_parts) if scope_parts else ""
        with self.connection() as connection:
            cursor = connection.execute(
                f"DELETE FROM future_events{scope}{' AND' if scope else ' WHERE'} "
                "ABS(ABS(amount) - 1234.0) < 0.000001",
                parameters,
            )
            deleted = cursor.rowcount
            duplicate_scope = " AND ".join(scope_parts)
            cursor = connection.execute(
                f"""DELETE FROM future_events
                    WHERE {duplicate_scope + " AND " if duplicate_scope else ""}id NOT IN (
                        SELECT MIN(id) FROM future_events
                        WHERE {duplicate_scope + " AND " if duplicate_scope else ""}1 = 1
                        GROUP BY company_id, owner_inn, event_date, amount, category, description
                    )""",
                parameters + parameters,
            )
            return deleted + cursor.rowcount

    def reset_demo_events(
        self,
        company_id: str,
        last_actual_date: date,
        owner_inn: str | None = None,
    ) -> list[dict]:
        event_dates = [last_actual_date + timedelta(days=int(item["offset"])) for item in DEMO_EVENTS]
        with self.connection() as connection:
            if owner_inn is None:
                connection.execute("DELETE FROM future_events WHERE company_id = ?", (company_id,))
            else:
                connection.execute(
                    "DELETE FROM future_events WHERE company_id = ? AND owner_inn = ?",
                    (company_id, owner_inn),
                )
            connection.executemany(
                """INSERT INTO future_events(company_id, owner_inn, event_date, amount, direction, category, event_type,
                   description, counterparty_inn, counterparty_name, source, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        company_id,
                        owner_inn or "",
                        event_date.isoformat(),
                        item["amount"],
                        item["direction"],
                        item["category"],
                        item["event_type"],
                        item["description"],
                        "",
                        "",
                        "демо-набор",
                        item["status"],
                    )
                    for item, event_date in zip(DEMO_EVENTS, event_dates, strict=True)
                ],
            )
        return self.list_events(company_id, owner_inn=owner_inn)

    def ensure_diverse_events(self, company_id: str, last_actual_date: date) -> list[dict]:
        self.cleanup_events(company_id, owner_inn="")
        active_events = self.list_events(company_id, include_cancelled=False, owner_inn="")
        categories = {event["category"] for event in active_events}
        descriptions = {event["description"] for event in active_events}
        if len(categories) < 3 or len(descriptions) < 3:
            return self.reset_demo_events(company_id, last_actual_date, owner_inn="")
        return active_events

    def ensure_tax_calendar_events(
        self,
        company_id: str,
        last_actual_date: date,
        tax_history: dict[str, float],
        *,
        is_individual_entrepreneur: bool = False,
    ) -> int:
        if not tax_history:
            return 0
        end_date = last_actual_date + timedelta(days=90)
        schedules: list[tuple[str, date]] = []
        year = last_actual_date.year
        while year <= end_date.year:
            for month in range(1, 13):
                due_date = date(year, month, 28)
                if last_actual_date < due_date <= end_date and "ЕНП" in tax_history:
                    schedules.append(("ЕНП", due_date))
                if last_actual_date < due_date <= end_date and "НДС" in tax_history:
                    schedules.append(("НДС", due_date))
            annual_due_month = 4 if is_individual_entrepreneur else 3
            annual_due = date(year, annual_due_month, 28)
            if last_actual_date < annual_due <= end_date and "УСН" in tax_history:
                schedules.append(("УСН", annual_due))
            for month in (4, 7, 10):
                advance_due = date(year, month, 28)
                if last_actual_date < advance_due <= end_date and "УСН" in tax_history:
                    schedules.append(("УСН", advance_due))
            year += 1

        created = 0
        with self.connection() as connection:
            for tax_name, due_date in schedules:
                description = f"{tax_name} — сумма оценена по истории платежей"
                existing = connection.execute(
                    """SELECT 1 FROM future_events
                       WHERE company_id = ? AND event_date = ? AND source = ?
                         AND description = ? LIMIT 1""",
                    (company_id, due_date.isoformat(), "Налоговый календарь ФНС", description),
                ).fetchone()
                if existing:
                    continue
                connection.execute(
                    """INSERT INTO future_events(company_id, event_date, amount, direction, category,
                       event_type, description, source, status)
                       VALUES (?, ?, ?, 'списание', 'Налоги и обязательные платежи',
                               'Налоговый платёж', ?, 'Налоговый календарь ФНС', 'Ожидается')""",
                    (company_id, due_date.isoformat(), tax_history[tax_name], description),
                )
                created += 1
        return created

    def get_category_overrides(self, company_id: str) -> dict[str, str]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT operation_id, category FROM category_overrides WHERE company_id = ?",
                (company_id,),
            ).fetchall()
        return {str(row["operation_id"]): str(row["category"]) for row in rows}

    def set_category(self, company_id: str, operation_id: str, category: str) -> None:
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO category_overrides(company_id, operation_id, category)
                   VALUES (?, ?, ?)
                   ON CONFLICT(company_id, operation_id)
                   DO UPDATE SET category=excluded.category, updated_at=CURRENT_TIMESTAMP""",
                (company_id, operation_id, category),
            )

    def recurring_confirmation(self, company_id: str) -> dict[str, bool]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT recurring_id, confirmed FROM recurring_overrides WHERE company_id = ?",
                (company_id,),
            ).fetchall()
        return {str(row["recurring_id"]): bool(row["confirmed"]) for row in rows}

    def set_recurring(self, company_id: str, recurring_id: str, confirmed: bool) -> None:
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO recurring_overrides(company_id, recurring_id, confirmed)
                   VALUES (?, ?, ?)
                   ON CONFLICT(company_id, recurring_id)
                   DO UPDATE SET confirmed=excluded.confirmed, updated_at=CURRENT_TIMESTAMP""",
                (company_id, recurring_id, int(confirmed)),
            )

    def list_events(
        self,
        company_id: str,
        include_cancelled: bool = True,
        owner_inn: str | None = None,
    ) -> list[dict]:
        query = "SELECT * FROM future_events WHERE company_id = ?"
        parameters: tuple = (company_id,)
        if owner_inn is not None:
            query += " AND (owner_inn = '' OR owner_inn = ?)"
            parameters = (company_id, owner_inn)
        if not include_cancelled:
            query += " AND status != 'Отменено'"
        query += " ORDER BY event_date, id"
        with self.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def create_event(self, company_id: str, event: dict, owner_inn: str | None = None) -> dict:
        with self.connection() as connection:
            cursor = connection.execute(
                """INSERT INTO future_events(company_id, owner_inn, event_date, amount, direction, category, event_type,
                   description, counterparty_inn, counterparty_name, source, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    company_id, owner_inn or "", event["date"].isoformat(), event["amount"], event["direction"],
                    event["category"], event["event_type"], event["description"],
                    event.get("counterparty_inn") or "", event.get("counterparty_name") or "",
                    event["source"], event["status"],
                ),
            )
            event_id = cursor.lastrowid
        return next(item for item in self.list_events(company_id, owner_inn=owner_inn) if item["id"] == event_id)

    def update_event(
        self,
        company_id: str,
        event_id: int,
        changes: dict,
        owner_inn: str | None = None,
    ) -> dict | None:
        visible_events = self.list_events(company_id, owner_inn=owner_inn)
        existing = next(
            (
                item for item in visible_events
                if item["id"] == event_id and (owner_inn is None or item["owner_inn"] == owner_inn)
            ),
            None,
        )
        if existing is None:
            return None
        fields = {
            "date": "event_date", "amount": "amount", "direction": "direction", "category": "category",
            "event_type": "event_type", "description": "description", "source": "source", "status": "status",
            "counterparty_inn": "counterparty_inn", "counterparty_name": "counterparty_name",
        }
        for key, value in changes.items():
            if value is not None and key in fields:
                existing[fields[key]] = value.isoformat() if key == "date" else value
        with self.connection() as connection:
            update_sql = """UPDATE future_events SET event_date=?, amount=?, direction=?, category=?, event_type=?,
                   description=?, counterparty_inn=?, counterparty_name=?, source=?, status=?
                   WHERE id=? AND company_id=?"""
            parameters = (
                existing["event_date"], existing["amount"], existing["direction"], existing["category"],
                existing["event_type"], existing["description"], existing["counterparty_inn"],
                existing["counterparty_name"], existing["source"], existing["status"], event_id, company_id,
            )
            if owner_inn is not None:
                update_sql += " AND owner_inn = ?"
                parameters += (owner_inn,)
            connection.execute(update_sql, parameters)
        return next(
            item for item in self.list_events(company_id, owner_inn=owner_inn) if item["id"] == event_id
        )

    def cancel_event(self, company_id: str, event_id: int, owner_inn: str | None = None) -> dict | None:
        return self.update_event(company_id, event_id, {"status": "Отменено"}, owner_inn=owner_inn)
