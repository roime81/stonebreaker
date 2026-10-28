# Stonebreaker (MVP)

A small, runnable vertical slice of an OLTP + OLAP platform: **PostgreSQL** is the transactional source of truth,
**DuckDB** serves analytics over a **snapshot** copied from PostgreSQL, behind a FastAPI REST + GraphQL API and a minimal web console.

This is a development MVP, **not production-ready** and not a database engine.

## Technology choices
- Backend: Python 3.12, FastAPI, psycopg 3, DuckDB, Strawberry GraphQL (small, one language, easy to test).
- Console: a single static HTML/JS page served by the backend (no build step; output is rendered via `textContent`).
- Docker Compose: `postgres:16` + `backend`.
- **Assumption:** "graphsql" in the request was interpreted as **GraphQL**. A `/graphql` endpoint exposes products, `placeOrder`, `refreshAnalytics`, `syncStatus` and `report`. If you meant SQL/PGQ or graph traversal, that is future work.

## Run
```bash
cp .env.example .env        # then change the secrets
docker compose up --build   # console + API on http://127.0.0.1:8000
```
On start the backend creates the schema and seeds deterministic sample data (40 customers, 10 products, 500 orders) if the DB is empty.

## Demo steps
1. Open http://127.0.0.1:8000, paste `STONEBREAKER_API_KEY` from `.env`, click **Use key**.
2. Click **Refresh now** (loads the snapshot into DuckDB; status shows row counts / success / error).
3. Run report `revenue_by_category`; note the numbers.
4. Place an order (customer 1, product 1, quantity 3). Re-run the report: unchanged (snapshot is stale by design).
5. Refresh again, re-run the report: revenue grew by the order total. Refresh repeatedly: no duplication.
6. Errors: ordering more than the stock (or a non-existent product) returns 409/404; stop `postgres` and refresh to see a failed status with the error.

API (all except `/health` need header `X-API-Key`): `GET/POST /api/orders`, `GET /api/orders/{id}`, `GET /api/products`,
`POST /api/analytics/refresh`, `GET /api/analytics/status`, `GET /api/analytics/reports`, `GET /api/analytics/reports/{name}?limit=`,
`POST /graphql`, OpenAPI docs at `/docs`.

Example:
```bash
curl -H "X-API-Key: $KEY" -X POST -H 'Content-Type: application/json' \
  -d '{"customer_id":1,"product_id":1,"quantity":2}' http://127.0.0.1:8000/api/orders
curl -H "X-API-Key: $KEY" -X POST -H 'Content-Type: application/json' \
  -d '{"query":"{ report(name:\"revenue_by_region\", limit:5){label revenueCents} }"}' http://127.0.0.1:8000/graphql
```

## Tests
```bash
cd backend && pip install -r requirements.txt && pytest
```
Tests use a real PostgreSQL: set `STONEBREAKER_TEST_PG_DSN` (a superuser DSN, e.g. `host=localhost user=postgres`) or, if PostgreSQL binaries are in `/usr/lib/postgresql/*/bin`, a throwaway cluster is started automatically (not as root). They cover: transactions and rollback on errors, auth, refresh, freshness, no duplication on repeated refresh, refresh failure reporting that preserves the previous snapshot, report validation, and GraphQL.

Run without Docker: `cd backend && STONEBREAKER_API_KEY=... STONEBREAKER_PG_DSN=... uvicorn app.server:app`.

## Architecture
```
console / clients --HTTP--> FastAPI --psycopg (parameterised SQL)--> PostgreSQL (truth)
                              |  \--refresh: REPEATABLE READ snapshot copy--> DuckDB file --> fixed reports
                              \-- /graphql (Strawberry), same service layer
```
- Writes: `place_order` runs in one PostgreSQL transaction (row lock on product, stock check, decrement, insert).
- Sync: a full snapshot refresh. Tables are read from PostgreSQL in one `REPEATABLE READ READ ONLY` transaction (consistent point in time across tables), then DuckDB tables are emptied and refilled inside one DuckDB transaction. It is all-or-nothing and idempotent (primary keys, replace not append). Only one refresh runs at a time (concurrent call: 409). Every run is recorded in `sync_runs`.

## Security (development assumptions)
- No endpoint accepts SQL. Analytics are a fixed catalogue of reports with bounded `limit` (max 100); all values are bound parameters.
- A single shared API key (`X-API-Key`, constant-time compare) is required and has no default; the app refuses to start without one. This is **not** real user auth/authorisation. The console keeps the key in `sessionStorage`.
- Compose binds only to `127.0.0.1`; PostgreSQL is not exposed. No TLS. Don't expose this to a network as-is.
- PostgreSQL statement timeout (5 s) on API queries; GraphQL has no depth/complexity limiting yet.

## Consistency and limitations
- Analytics are **eventually consistent snapshots**, as fresh as the last successful refresh (manual trigger; no scheduler). Not real-time, no CDC/WAL.
- Refresh copies whole tables into memory: fine for the sample, not for large data.
- DuckDB is single-process, accessed through one guarded connection.
- Not implemented: MySQL protocol/dialect compatibility, graph traversal, AI acceleration, automatic query routing, CDC, user management, migrations, observability, production hardening.

## Next milestones
1. Incremental sync (watermarks) then logical-replication CDC; scheduled refresh.
2. Per-user auth/roles; GraphQL depth limits.
3. Schema migrations; configurable schemas.
4. Query router experiments; benchmarks.
5. Later/optional: MySQL-compatible front end, vector/graph features.
