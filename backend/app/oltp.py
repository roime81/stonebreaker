"""Transactional (PostgreSQL) path. All SQL is parameterised."""
import psycopg
from psycopg.rows import dict_row

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    region TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    stock INTEGER NOT NULL CHECK (stock >= 0)
);
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    total_cents BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class OrderError(Exception):
    """Business-rule failure (maps to HTTP 4xx)."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def connect(dsn: str, timeout_ms: int = 5000) -> psycopg.Connection:
    return psycopg.connect(dsn, row_factory=dict_row, options=f"-c statement_timeout={int(timeout_ms)}")


def ensure_schema(dsn: str) -> None:
    with connect(dsn) as conn:
        conn.execute(SCHEMA)


def list_products(dsn: str, limit: int) -> list[dict]:
    with connect(dsn) as conn:
        return conn.execute("SELECT id, name, category, price_cents, stock FROM products ORDER BY id LIMIT %s", (limit,)).fetchall()


def list_orders(dsn: str, limit: int) -> list[dict]:
    with connect(dsn) as conn:
        return conn.execute(
            "SELECT id, customer_id, product_id, quantity, total_cents, created_at FROM orders ORDER BY id DESC LIMIT %s",
            (limit,),
        ).fetchall()


def page_orders(dsn: str, after_id: int, limit: int) -> list[dict]:
    """Fetch the next ascending keyset page without scanning skipped rows."""
    with connect(dsn) as conn:
        return conn.execute(
            "SELECT id, customer_id, product_id, quantity, total_cents, created_at "
            "FROM orders WHERE id > %s ORDER BY id LIMIT %s",
            (after_id, limit),
        ).fetchall()


def get_order(dsn: str, order_id: int) -> dict | None:
    with connect(dsn) as conn:
        return conn.execute(
            "SELECT id, customer_id, product_id, quantity, total_cents, created_at FROM orders WHERE id = %s", (order_id,)
        ).fetchone()


def place_order(dsn: str, customer_id: int, product_id: int, quantity: int) -> dict:
    """Atomically check stock, decrement it and insert the order."""
    if quantity <= 0 or quantity > 1000:
        raise OrderError("quantity must be between 1 and 1000")
    if not (0 < customer_id <= 2147483647 and 0 < product_id <= 2147483647):
        raise OrderError("customer_id/product_id out of range")
    with connect(dsn) as conn:  # context manager commits on success, rolls back on error
        if conn.execute("SELECT 1 FROM customers WHERE id = %s", (customer_id,)).fetchone() is None:
            raise OrderError("customer not found", 404)
        product = conn.execute("SELECT price_cents, stock FROM products WHERE id = %s FOR UPDATE", (product_id,)).fetchone()
        if product is None:
            raise OrderError("product not found", 404)
        if product["stock"] < quantity:
            raise OrderError(f"insufficient stock: {product['stock']} available", 409)
        conn.execute("UPDATE products SET stock = stock - %s WHERE id = %s", (quantity, product_id))
        return conn.execute(
            "INSERT INTO orders (customer_id, product_id, quantity, total_cents) VALUES (%s, %s, %s, %s) "
            "RETURNING id, customer_id, product_id, quantity, total_cents, created_at",
            (customer_id, product_id, quantity, product["price_cents"] * quantity),
        ).fetchone()
