from concurrent.futures import ThreadPoolExecutor

import psycopg


def test_concurrent_orders_never_oversell(client):
    with psycopg.connect(client.settings.pg_dsn) as c:
        c.execute("UPDATE products SET stock = 20 WHERE id = 1")
    with ThreadPoolExecutor(16) as ex:
        codes = list(ex.map(lambda _: client.post("/api/orders", json={"customer_id": 1, "product_id": 1, "quantity": 1}).status_code, range(60)))
    assert codes.count(201) == 20
    assert codes.count(409) == 40
    assert set(codes) <= {201, 409}
    with psycopg.connect(client.settings.pg_dsn) as c:
        assert c.execute("SELECT stock FROM products WHERE id = 1").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM orders WHERE product_id = 1 AND id > 50").fetchone()[0] >= 20


def test_concurrent_refreshes_stay_consistent(client):
    with ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(lambda _: client.post("/api/analytics/refresh").status_code, range(8)))
    assert set(codes) <= {200, 409} and 200 in codes
    s = client.get("/api/analytics/status").json()
    assert s["last_run"]["status"] == "success" and s["last_run"]["rows_orders"] == 50


def test_reads_during_refresh_and_writes(client):
    client.post("/api/analytics/refresh")

    def job(i):
        if i % 3 == 0:
            return client.post("/api/analytics/refresh").status_code
        if i % 3 == 1:
            return client.post("/api/orders", json={"customer_id": 1, "product_id": 2, "quantity": 1}).status_code
        return client.get("/api/analytics/reports/revenue_by_region").status_code

    with ThreadPoolExecutor(12) as ex:
        codes = list(ex.map(job, range(60)))
    assert all(c < 500 for c in codes)
