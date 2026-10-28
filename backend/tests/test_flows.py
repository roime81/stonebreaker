import psycopg

from fastapi.testclient import TestClient


def order(client, **kw):
    body = {"customer_id": 1, "product_id": 1, "quantity": 2, **kw}
    return client.post("/api/orders", json=body)


def revenue(client):
    return sum(r["revenue_cents"] for r in client.get("/api/analytics/reports/revenue_by_category").json())


def test_auth_required(client):
    anon = TestClient(client.app)
    assert anon.get("/api/products").status_code == 401
    assert anon.get("/api/products", headers={"X-API-Key": "wrong"}).status_code == 401
    assert anon.post("/graphql", json={"query": "{ products { id } }"}).status_code == 401
    assert anon.get("/health").status_code == 200


def test_transaction_write_read_and_stock(client):
    before = {p["id"]: p for p in client.get("/api/products").json()}[1]["stock"]
    r = order(client)
    assert r.status_code == 201
    o = r.json()
    assert client.get(f"/api/orders/{o['id']}").json()["quantity"] == 2
    after = {p["id"]: p for p in client.get("/api/products").json()}[1]["stock"]
    assert after == before - 2


def test_transaction_errors_leave_state_unchanged(client):
    with psycopg.connect(client.settings.pg_dsn) as c:
        c.execute("UPDATE products SET stock = 5 WHERE id = 1")
    stock = 5
    assert order(client, quantity=stock + 1).status_code == 409
    assert order(client, quantity=0).status_code == 422
    assert order(client, product_id=9999).status_code == 404
    assert order(client, customer_id=9999).status_code == 404
    assert {p["id"]: p for p in client.get("/api/products").json()}[1]["stock"] == stock
    assert client.get("/api/orders/999999").status_code == 404


def test_refresh_makes_new_data_visible_and_is_idempotent(client):
    s = client.post("/api/analytics/refresh").json()
    assert s["last_run"]["status"] == "success" and s["last_run"]["rows_orders"] == 50
    base = revenue(client)
    pg_total = _pg_total(client)
    assert base == pg_total
    # freshness: new order invisible until refresh
    price = {p["id"]: p for p in client.get("/api/products").json()}[1]["price_cents"]
    order(client, quantity=3)
    assert revenue(client) == base
    client.post("/api/analytics/refresh")
    assert revenue(client) == base + 3 * price
    # repeated refresh does not duplicate
    for _ in range(3):
        s = client.post("/api/analytics/refresh").json()
    assert s["last_run"]["rows_orders"] == 51
    assert revenue(client) == base + 3 * price == _pg_total(client)


def _pg_total(client):
    with psycopg.connect(client.settings.pg_dsn) as c:
        return int(c.execute("SELECT sum(total_cents) FROM orders").fetchone()[0])


def test_report_validation(client):
    client.post("/api/analytics/refresh")
    assert client.get("/api/analytics/reports/nope").status_code == 404
    assert client.get("/api/analytics/reports/top_customers?limit=101").status_code == 422
    assert client.get("/api/analytics/reports/top_customers?limit=0").status_code == 422
    assert len(client.get("/api/analytics/reports/top_customers?limit=3").json()) == 3
    assert client.get("/api/analytics/reports/x;DROP TABLE orders").status_code == 404


def test_refresh_failure_is_reported_and_keeps_old_snapshot(client):
    client.post("/api/analytics/refresh")
    base = revenue(client)
    ana = client.app.state.analytics
    ana._pg_dsn = "host=127.0.0.1 port=1 connect_timeout=2 dbname=x"
    s = client.post("/api/analytics/refresh").json()
    assert s["last_run"]["status"] == "failed" and s["last_run"]["error"]
    assert revenue(client) == base
    assert client.get("/api/analytics/status").json()["last_success_at"]


def test_graphql_flow(client):
    q = 'mutation { placeOrder(customerId: 1, productId: 2, quantity: 1) { id totalCents } }'
    assert "errors" not in client.post("/graphql", json={"query": q}).json()
    r = client.post("/graphql", json={"query": "mutation { refreshAnalytics { status error } }"}).json()
    assert r["data"]["refreshAnalytics"]["status"] == "success"
    r = client.post("/graphql", json={"query": '{ report(name: "revenue_by_region", limit: 5) { label revenueCents } }'}).json()
    assert r["data"]["report"]
    r = client.post("/graphql", json={"query": '{ report(name: "x") { label } }'}).json()
    assert r["errors"]
