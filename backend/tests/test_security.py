import pytest
from fastapi.testclient import TestClient

INJECTIONS = ["1 OR 1=1", "1; DROP TABLE orders;--", "' OR '1'='1", "1 UNION SELECT 1,2,3,4,5,6", "../../etc/passwd", "%00", "A" * 5000]
PROTECTED = [("GET", "/api/products"), ("GET", "/api/orders"), ("POST", "/api/orders"), ("GET", "/api/orders/1"),
             ("POST", "/api/analytics/refresh"), ("GET", "/api/analytics/status"), ("GET", "/api/analytics/reports"),
             ("GET", "/api/analytics/reports/top_customers"), ("POST", "/graphql")]


@pytest.mark.parametrize("method,path", PROTECTED)
@pytest.mark.parametrize("hdr", [{}, {"X-API-Key": ""}, {"X-API-Key": "nope"}, {"Authorization": "******"}])
def test_every_protected_route_rejects_bad_credentials(client, method, path, hdr):
    r = TestClient(client.app).request(method, path, headers=hdr, json={})
    assert r.status_code == 401


@pytest.mark.parametrize("payload", INJECTIONS)
def test_injection_payloads_are_inert(client, payload):
    client.post("/api/analytics/refresh")
    for url in (f"/api/orders/{payload}", f"/api/analytics/reports/{payload}", f"/api/orders?limit={payload}"):
        assert client.get(url).status_code in (404, 405, 422)
    r = client.post("/api/orders", json={"customer_id": payload, "product_id": payload, "quantity": payload})
    assert r.status_code == 422
    g = client.post("/graphql", json={"query": '{ report(name: "%s") { label } }' % payload.replace('"', "")}).json()
    assert g.get("errors")
    assert len(client.get("/api/products").json()) == 10  # tables intact
    assert client.get("/api/analytics/reports/top_customers").status_code == 200


def test_input_bounds(client):
    for body in ({"customer_id": 1, "product_id": 1, "quantity": 1001}, {"customer_id": -1, "product_id": 1, "quantity": 1},
                 {"customer_id": 1, "product_id": 1, "quantity": 1.5}, {"customer_id": 1, "product_id": 1}, {},
                 {"customer_id": 2**70, "product_id": 1, "quantity": 1}):
        assert client.post("/api/orders", json=body).status_code == 422
    assert client.get("/api/products?limit=1000000").status_code == 200
    assert len(client.get("/api/products?limit=1000000").json()) <= 100
    assert client.get("/api/analytics/reports/top_customers?limit=100000").status_code == 422


def test_errors_do_not_leak_internals(client):
    client.app.state.analytics._pg_dsn = "host=127.0.0.1 port=1 connect_timeout=1 dbname=x"
    body = client.post("/api/analytics/refresh").text
    assert "Traceback" not in body and "/home/" not in body


def test_no_raw_sql_surface(client):
    for p in ("/api/sql", "/api/query", "/sql", "/query"):
        assert client.post(p, json={"sql": "select 1"}).status_code in (404, 405)


def test_malformed_json_and_graphql(client):
    assert client.post("/api/orders", content=b"{not json", headers={"Content-Type": "application/json"}).status_code == 422
    assert client.post("/graphql", json={"query": "{ nope }"}).json().get("errors")
