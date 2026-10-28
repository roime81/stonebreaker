"""Scalable synthetic data generation (server-side generate_series / DuckDB range()).

Targets: PostgreSQL `orders` (OLTP source) and a standalone DuckDB file (OLAP engine scale test).
Rows are produced inside the database engines, in batches, so client memory stays flat.
"""
import time

from app import oltp

BATCH = 5_000_000


def load_postgres(dsn: str, orders: int, customers: int = 10_000, products: int = 1_000) -> dict:
    """Replace data in PG with `orders` rows (deterministic via hashing of the id, no RNG state)."""
    oltp.ensure_schema(dsn)
    t0 = time.perf_counter()
    with oltp.connect(dsn, timeout_ms=0) as c:
        c.execute("TRUNCATE orders, products, customers RESTART IDENTITY CASCADE")
        c.execute("INSERT INTO customers (name, region) SELECT 'Customer '||g, (ARRAY['EMEA','AMER','APAC'])[1+g%%3] "
                  "FROM generate_series(1, %s) g", (customers,))
        c.execute("INSERT INTO products (name, category, price_cents, stock) SELECT 'Product '||g, "
                  "(ARRAY['Hardware','Software','Books'])[1+g%%3], 500+(g*37)%%50000, 2000000000 "
                  "FROM generate_series(1, %s) g", (products,))
    for start in range(1, orders + 1, BATCH):
        end = min(start + BATCH - 1, orders)
        with oltp.connect(dsn, timeout_ms=0) as c:
            c.execute(
                "INSERT INTO orders (customer_id, product_id, quantity, total_cents, created_at) "
                "SELECT 1+(g*7919)%%%s, 1+(g*104729)%%%s, 1+g%%5, (1+g%%5)*(500+((1+(g*104729)%%%s)*37)%%50000), "
                "now() - ((g%%365) || ' days')::interval FROM generate_series(%s::bigint, %s::bigint) g",
                (customers, products, products, start, end),
            )
    with oltp.connect(dsn, timeout_ms=0) as c:
        c.execute("SELECT setval(pg_get_serial_sequence('orders','id'), (SELECT max(id) FROM orders))")
        c.execute("ANALYZE")
    return {"orders": orders, "load_seconds": round(time.perf_counter() - t0, 2)}


def load_duckdb(path: str, orders: int, customers: int = 10_000, products: int = 1_000) -> dict:
    """Populate a standalone DuckDB with the same shape, for analytical scale tests (up to 1e9 rows)."""
    import duckdb

    t0 = time.perf_counter()
    con = duckdb.connect(path)
    con.execute("DROP TABLE IF EXISTS orders; DROP TABLE IF EXISTS products; DROP TABLE IF EXISTS customers")
    con.execute("CREATE TABLE customers AS SELECT g AS id, 'Customer '||g AS name, ['EMEA','AMER','APAC'][1+g%3] AS region FROM range(1, ?+1) t(g)", [customers])
    con.execute("CREATE TABLE products AS SELECT g AS id, 'Product '||g AS name, ['Hardware','Software','Books'][1+g%3] AS category, "
                "500+(g*37)%50000 AS price_cents, 2000000000 AS stock FROM range(1, ?+1) t(g)", [products])
    con.execute("CREATE TABLE orders (id BIGINT, customer_id INTEGER, product_id INTEGER, quantity INTEGER, total_cents BIGINT, created_at TIMESTAMP)")
    for start in range(1, orders + 1, BATCH):
        end = min(start + BATCH - 1, orders)
        con.execute(
            "INSERT INTO orders SELECT g, 1+(g*7919)%?, 1+(g*104729)%?, 1+g%5, (1+g%5)*(500+((1+(g*104729)%?)*37)%50000), "
            "TIMESTAMP '2026-01-01' - to_days(CAST(g%365 AS INTEGER)) FROM range(?, ?+1) t(g)",
            [customers, products, products, start, end],
        )
    con.close()
    return {"orders": orders, "load_seconds": round(time.perf_counter() - t0, 2)}
