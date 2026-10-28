"""Deterministic sample data. Idempotent: does nothing if customers already exist."""
import random
from datetime import datetime, timedelta, timezone

from . import oltp

REGIONS = ["EMEA", "AMER", "APAC"]
CATEGORIES = {
    "Hardware": ["Anvil", "Chisel", "Hammer", "Drill"],
    "Software": ["License", "Plugin", "Support Plan"],
    "Books": ["Database Internals", "SQL Handbook", "Column Stores"],
}


def seed(dsn: str, orders: int = 500) -> bool:
    oltp.ensure_schema(dsn)
    rng = random.Random(42)
    with oltp.connect(dsn) as conn:
        if conn.execute("SELECT count(*) AS n FROM customers").fetchone()["n"] > 0:
            return False
        for i in range(1, 41):
            conn.execute("INSERT INTO customers (name, region) VALUES (%s, %s)", (f"Customer {i}", rng.choice(REGIONS)))
        prices = {}
        for cat, names in CATEGORIES.items():
            for n in names:
                price = rng.randrange(500, 50000, 50)
                row = conn.execute(
                    "INSERT INTO products (name, category, price_cents, stock) VALUES (%s, %s, %s, %s) RETURNING id",
                    (n, cat, price, 100000),
                ).fetchone()
                prices[row["id"]] = price
        now = datetime.now(timezone.utc)
        for _ in range(orders):
            pid = rng.choice(list(prices))
            qty = rng.randint(1, 5)
            conn.execute(
                "INSERT INTO orders (customer_id, product_id, quantity, total_cents, created_at) VALUES (%s, %s, %s, %s, %s)",
                (rng.randint(1, 40), pid, qty, prices[pid] * qty, now - timedelta(days=rng.randint(0, 29), hours=rng.randint(0, 23))),
            )
            conn.execute("UPDATE products SET stock = stock - %s WHERE id = %s", (qty, pid))
    return True


if __name__ == "__main__":
    from .config import load_settings

    print("seeded" if seed(load_settings().pg_dsn) else "already seeded")
