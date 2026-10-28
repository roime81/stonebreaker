# Stonebreaker (0.9.0-beta.1 candidate)

A beta-candidate vertical slice of an OLTP + OLAP platform: **PostgreSQL** is the transactional source of truth,
**DuckDB** serves analytics over a **snapshot** copied from PostgreSQL, behind a FastAPI REST + GraphQL API and a responsive static console.

The beta candidate is **not yet production-ready**. See [production readiness](docs/PRODUCTION_READINESS.md) for verified scope and gaps. It is not a database engine.

## Technology choices
- Backend: Python 3.12, FastAPI, psycopg 3, DuckDB, Strawberry GraphQL (small, one language, easy to test).
- Console: a responsive static HTML/JS page served by the backend (no framework or build step; output is rendered via DOM `textContent`).
- Docker Compose: `postgres:16` + `backend`.
- **Assumption:** "graphsql" in the request was interpreted as **GraphQL**. A `/graphql` endpoint exposes products, `placeOrder`, `refreshAnalytics`, `syncStatus` and `report`. If you meant SQL/PGQ or graph traversal, that is future work.

## Run
```bash
cp .env.example .env        # then change the secrets
docker compose up --build   # console + API on http://127.0.0.1:8000
```
On start the backend creates the schema and seeds deterministic sample data (40 customers, 10 products, 500 orders) if the DB is empty.

## Demo steps
1. Open http://127.0.0.1:8000, paste `STONEBREAKER_API_KEY` from `.env`, click **Connect**. This remains a service-account key, not per-user login.
2. Click **Refresh now** (loads the snapshot into DuckDB; status shows row counts / success / error).
3. Run report `revenue_by_category`; note the numbers.
4. Place an order (customer 1, product 1, quantity 3). Re-run the report: unchanged (snapshot is stale by design).
5. Refresh again, re-run the report: revenue grew by the order total. Refresh repeatedly: no duplication.
6. Errors: ordering more than the stock (or a non-existent product) returns 409/404; stop `postgres` and refresh to see a failed status with the error.
7. Page through orders by keyset cursor, and review/validate a rule-based transformation proposal from a small JSON sample.

API (protected routes need header `X-API-Key`; `/health`, `/healthz`, `/readyz`, and `/metrics` are public): `GET/POST /api/orders`, `GET /api/orders/{id}`, `GET /api/products`,
`POST /api/analytics/refresh`, `GET /api/analytics/status`, `GET /api/analytics/reports`, `GET /api/analytics/reports/{name}?limit=`,
`GET /api/orders/page?after_id=&limit=`, `POST /api/ingestion/proposals`, `POST /api/ingestion/proposals/approve`,
`POST /graphql`, OpenAPI docs at `/docs`. `/healthz`, `/readyz`, and `/metrics` are operational endpoints.

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

## Testing and benchmarks
See [docs/TESTING_AND_BENCHMARKS.md](docs/TESTING_AND_BENCHMARKS.md) for security, concurrency, stress and scale tests, plus [docs/BENCHMARKS.md](docs/BENCHMARKS.md) for the unrun Hugging Face benchmark.

## Architecture
```
console / clients --HTTP--> FastAPI --psycopg (parameterised SQL)--> PostgreSQL (truth)
                              |  \--refresh: REPEATABLE READ snapshot copy--> DuckDB file --> fixed reports
                              \-- /graphql (Strawberry), same service layer
```
- Writes: `place_order` runs in one PostgreSQL transaction (row lock on product, stock check, decrement, insert).
- Sync: a full snapshot refresh. Tables are read from PostgreSQL in one `REPEATABLE READ READ ONLY` transaction (consistent point in time across tables), streamed to temporary CSV files with `COPY`, then DuckDB tables are emptied and refilled inside one DuckDB transaction. It is all-or-nothing and idempotent (primary keys, replace not append). Only one refresh runs at a time (concurrent call: 409). Every run is recorded in `sync_runs`.

## Security (beta-candidate limitations)
- No endpoint accepts SQL. Analytics are a fixed catalogue of reports with bounded `limit` (max 100); all values are bound parameters.
- A single shared API key (`X-API-Key`, constant-time compare) is required and has no default; the app refuses to start without one. It is a service-account mechanism; per-user authentication and role-based authorisation are not implemented. The console keeps the key in `sessionStorage`.
- Compose binds only to `127.0.0.1`; PostgreSQL is not exposed. No TLS. Don't expose this to a network as-is.
- PostgreSQL statement timeout (5 s) on API queries; GraphQL has no depth/complexity limiting yet.
- Request IDs, basic security headers, `/readyz`, and a basic Prometheus text endpoint are present; CORS policy, rate limiting, structured logging, and tracing are not.
- AI provider calls receive profile metadata only, not sampled cell values. Treat column names and all imported content as untrusted; proposals are validated allowlisted operations, not executable SQL. Proposal versioning/audit persistence and a durable approval workflow are still missing.

## Consistency and limitations
- Analytics are **eventually consistent snapshots**, as fresh as the last successful refresh (manual trigger; no scheduler). Not real-time, no CDC/WAL.
- Refresh copies whole tables (streamed through temp files on disk, not memory); cost grows with total data size. See [benchmark status](docs/BENCHMARKS.md); no newly recorded benchmark result is claimed here.
- DuckDB is single-process, accessed through one guarded connection.
- Not implemented: MySQL protocol/dialect compatibility, graph traversal, automatic query routing, CDC, background ingestion jobs, per-user authentication, migrations, and complete production hardening.

## Release notes and operations
- [CHANGELOG](CHANGELOG.md)
- [Production readiness checklist](docs/PRODUCTION_READINESS.md)
- [HF scale benchmark and reproducible command](docs/BENCHMARKS.md)
- [Backup and restore runbook](docs/BACKUP_RESTORE.md)
- [Upgrade notes from MVP](docs/UPGRADE.md)
- [Security policy](SECURITY.md)
