# Stonebreaker

Stonebreaker is an **MVP / development prototype** for a small hybrid OLTP + OLAP service. The checked-in application is version `0.1.0`, not the requested 0.9 beta, and is **not production-ready**.

The current implementation provides:
- PostgreSQL as the transactional source of truth for customers, products, and orders.
- Atomic order placement with stock checking and decrement.
- A manually refreshed, full DuckDB snapshot for a fixed set of analytical reports.
- A FastAPI REST API, a provisional GraphQL API, and a small static browser console.
- API-key protection for application routes other than `/health`.

The web console is a development UI, not a production client product. AI-driven ingestion/transformation and a 10-million-row Hugging Face validation are **not verified in this checkout**. A separate [draft 0.9 proposal](https://github.com/roime81/stonebreaker/pull/3) is open and unmerged; its proposed code is not part of this source tree.

## Architecture

```text
Browser / API client
       │ HTTP (REST or GraphQL)
       ▼
FastAPI ── parameterized transactions ──► PostgreSQL (source of truth)
   │
   └── manual REPEATABLE READ full snapshot ──► DuckDB ──► fixed reports
```

Order placement checks customer and product existence, locks the product row, checks stock, decrements stock, and inserts the order in one PostgreSQL transaction. Analytics are eventually consistent: a manual refresh copies all three tables from one read-only PostgreSQL snapshot into DuckDB in a transaction. Refreshes replace rather than append data, so repeating one does not duplicate rows. Refresh status and row counts are recorded in DuckDB.

## Development quickstart

Requirements: Docker with the Compose plugin. All run and deployment guidance in this repository is for **local development only**.

```bash
cp .env.example .env
# Edit .env and replace both example values with private development values.
docker compose up --build
```

Compose binds the API to `127.0.0.1:8000`; PostgreSQL is not published to the host. On first startup, the backend creates the schema and seeds 40 customers, 10 products, and 500 orders if the database is empty. Open <http://127.0.0.1:8000> for the console, enter `STONEBREAKER_API_KEY` from `.env`, then use **Use key**.

The console demonstrates placing an order, refreshing the analytics snapshot, checking sync status, and running a report. A newly placed order will not affect reports until the next successful refresh. More detailed setup, API examples, tests, troubleshooting, and benchmark safety notes are in [Step by step](docs/STEP_BY_STEP.md).

## API and reports

REST API routes and `/graphql` require `X-API-Key`. `GET /health`, the static console at `/`, and OpenAPI documentation at `/docs` do not require the key.

- `GET /api/products`, `GET /api/orders`, `GET /api/orders/{order_id}`
- `POST /api/orders` with `customer_id`, `product_id`, and `quantity`
- `POST /api/analytics/refresh`, `GET /api/analytics/status`
- `GET /api/analytics/reports`, `GET /api/analytics/reports/{name}?limit=`
- `POST /graphql`

The fixed reports are `revenue_by_category`, `revenue_by_region`, `top_customers`, and `daily_revenue`; result limits are capped at 100. There is no client-supplied SQL endpoint.

Example (set `KEY` in your shell without putting the actual key in a shared command or document):

```bash
curl -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"customer_id":1,"product_id":1,"quantity":2}' \
  http://127.0.0.1:8000/api/orders
curl -H "X-API-Key: $KEY" \
  'http://127.0.0.1:8000/api/analytics/reports/revenue_by_region?limit=5'
```

## Tests and scale evidence

Backend tests are run from `backend/` with `pytest`. They need a PostgreSQL admin DSN in `STONEBREAKER_TEST_PG_DSN` or local PostgreSQL binaries available for a temporary test cluster. The fixture creates and drops a separate database per test, so **never point it at production or a database containing valuable data**.

The [test and benchmark guide](docs/TESTING_AND_BENCHMARKS.md) documents the existing commands and reported measurements. Its reported 20M-order DuckDB-only analytical run and 2M-order PostgreSQL-to-DuckDB snapshot refresh are different tests. Neither demonstrates a 10M Hugging Face end-to-end run. The [dated project log](docs/LOGFILE.md) records the verified project/task/test evidence and its limits.

## Security and production limitations

This is not suitable for exposure to an untrusted network: there is no TLS, user identity or role-based authorization, rate limiting, secret management, or production hardening. The API uses one shared API key; the browser console stores it in `sessionStorage`. The console page and OpenAPI docs themselves are unauthenticated. GraphQL query depth/complexity is not limited. Compose is explicitly development-only and binds locally; changing that binding does not make the service production-ready.

Not implemented in this checkout: AI-assisted ingestion/transformation, automated or incremental ingestion, CDC, scheduled refreshes, migrations, production authentication, or the requested Hugging Face large-data validation. Read the benchmark guide for scale limits and warnings before running any load command.

## Related documentation

- [Step-by-step local workflow](docs/STEP_BY_STEP.md)
- [Curated project and test log](docs/LOGFILE.md)
- [Testing, security, and benchmark details](docs/TESTING_AND_BENCHMARKS.md)
