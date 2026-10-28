"""Analytical (DuckDB) path: snapshot refresh from PostgreSQL plus a fixed catalogue of reports.

There is deliberately no endpoint that accepts SQL; clients choose a named report and
bounded parameters.
"""
import os
import tempfile
import threading
from datetime import datetime, timezone

import duckdb

from . import oltp

_TABLES = {
    "customers": ("id", "name", "region"),
    "products": ("id", "name", "category", "price_cents", "stock"),
    "orders": ("id", "customer_id", "product_id", "quantity", "total_cents", "created_at"),
}

_DDL = """
CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY, name VARCHAR, region VARCHAR);
CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, name VARCHAR, category VARCHAR, price_cents INTEGER, stock INTEGER);
CREATE TABLE IF NOT EXISTS orders (id BIGINT PRIMARY KEY, customer_id INTEGER, product_id INTEGER,
    quantity INTEGER, total_cents BIGINT, created_at TIMESTAMP);
CREATE SEQUENCE IF NOT EXISTS sync_run_seq;
CREATE TABLE IF NOT EXISTS sync_runs (run_id BIGINT, started_at TIMESTAMP, finished_at TIMESTAMP, status VARCHAR,
    error VARCHAR, rows_customers BIGINT, rows_products BIGINT, rows_orders BIGINT);
"""

_CSV_TYPES = {
    "customers": "{'id':'INTEGER','name':'VARCHAR','region':'VARCHAR'}",
    "products": "{'id':'INTEGER','name':'VARCHAR','category':'VARCHAR','price_cents':'INTEGER','stock':'INTEGER'}",
    "orders": "{'id':'BIGINT','customer_id':'INTEGER','product_id':'INTEGER','quantity':'INTEGER','total_cents':'BIGINT','created_at':'TIMESTAMP'}",
}

REPORTS = {
    "revenue_by_category": (
        "SELECT p.category AS category, sum(o.total_cents) AS revenue_cents, sum(o.quantity) AS units "
        "FROM orders o JOIN products p ON p.id = o.product_id GROUP BY p.category ORDER BY revenue_cents DESC LIMIT ?",
        0,
    ),
    "revenue_by_region": (
        "SELECT c.region AS region, sum(o.total_cents) AS revenue_cents, count(*) AS orders "
        "FROM orders o JOIN customers c ON c.id = o.customer_id GROUP BY c.region ORDER BY revenue_cents DESC LIMIT ?",
        0,
    ),
    "top_customers": (
        "SELECT c.id AS customer_id, c.name AS name, sum(o.total_cents) AS revenue_cents, count(*) AS orders "
        "FROM orders o JOIN customers c ON c.id = o.customer_id GROUP BY c.id, c.name "
        "ORDER BY revenue_cents DESC, c.id LIMIT ?",
        0,
    ),
    "daily_revenue": (
        "SELECT CAST(created_at AS DATE)::VARCHAR AS day, sum(total_cents) AS revenue_cents, count(*) AS orders "
        "FROM orders GROUP BY 1 ORDER BY 1 DESC LIMIT ?",
        0,
    ),
}


class RefreshInProgress(Exception):
    pass


class UnknownReport(Exception):
    pass


class Analytics:
    def __init__(self, duckdb_path: str, pg_dsn: str, max_rows: int = 100):
        self._con = duckdb.connect(duckdb_path)
        self._con.execute(_DDL)
        self._db_lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._pg_dsn = pg_dsn
        self.max_rows = max_rows

    def close(self) -> None:
        self._con.close()

    def _query(self, sql: str, params: list | None = None) -> list[dict]:
        with self._db_lock:
            cur = self._con.cursor()
            try:
                cur.execute(sql, params or [])
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
            finally:
                cur.close()

    def refresh(self) -> dict:
        """Full snapshot refresh. Reads PG in one REPEATABLE READ snapshot, then replaces
        the DuckDB copy inside a single DuckDB transaction (all-or-nothing, never duplicates)."""
        if not self._refresh_lock.acquire(blocking=False):
            raise RefreshInProgress("a refresh is already running")
        started = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            counts: dict[str, int] = {}
            try:
                with tempfile.TemporaryDirectory(prefix="sb_refresh_") as tmp:
                    files: dict[str, str] = {}
                    with oltp.connect(self._pg_dsn, timeout_ms=0) as pg:
                        pg.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                        for table, cols in _TABLES.items():
                            sel = ", ".join(f"{c} AT TIME ZONE 'UTC'" if c == "created_at" else c for c in cols)
                            path = os.path.join(tmp, f"{table}.csv")
                            with open(path, "wb") as f, pg.cursor().copy(
                                f"COPY (SELECT {sel} FROM {table} ORDER BY id) TO STDOUT WITH (FORMAT csv)"  # fixed identifiers
                            ) as cp:
                                for chunk in cp:
                                    f.write(chunk)
                            files[table] = path
                    with self._db_lock:
                        con = self._con.cursor()
                        try:
                            con.execute("BEGIN")
                            try:
                                for table in ("orders", "products", "customers"):
                                    con.execute(f"DELETE FROM {table}")
                                for table in ("customers", "products", "orders"):
                                    con.execute(f"INSERT INTO {table} SELECT * FROM read_csv(?, header=false, columns={_CSV_TYPES[table]})", [files[table]])
                                    counts[table] = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                                self._record(con, started, "success", None, counts)
                                con.execute("COMMIT")
                            except Exception:
                                con.execute("ROLLBACK")
                                raise
                        finally:
                            con.close()
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"[:500]
                with self._db_lock:
                    con = self._con.cursor()
                    try:
                        self._record(con, started, "failed", msg, {})
                    finally:
                        con.close()
                return self.status()
            return self.status()
        finally:
            self._refresh_lock.release()

    @staticmethod
    def _record(con, started, status, error, counts):
        con.execute(
            "INSERT INTO sync_runs VALUES (nextval('sync_run_seq'), ?, ?, ?, ?, ?, ?, ?)",
            [started, datetime.now(timezone.utc).replace(tzinfo=None), status, error,
             counts.get("customers"), counts.get("products"), counts.get("orders")],
        )

    def status(self) -> dict:
        rows = self._query("SELECT * FROM sync_runs ORDER BY run_id DESC LIMIT 1")
        last_ok = self._query("SELECT finished_at FROM sync_runs WHERE status = 'success' ORDER BY run_id DESC LIMIT 1")
        last = rows[0] if rows else None
        if last:
            for k in ("started_at", "finished_at"):
                last[k] = last[k].isoformat() + "Z"
        return {
            "last_run": last,
            "last_success_at": last_ok[0]["finished_at"].isoformat() + "Z" if last_ok else None,
            "mode": "snapshot (full refresh, not real-time)",
        }

    def report(self, name: str, limit: int | None = None) -> list[dict]:
        if name not in REPORTS:
            raise UnknownReport(name)
        n = self.max_rows if limit is None else limit
        if not 1 <= n <= self.max_rows:
            raise ValueError(f"limit must be between 1 and {self.max_rows}")
        return self._query(REPORTS[name][0], [n])

