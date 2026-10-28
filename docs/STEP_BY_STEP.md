# Step-by-step development workflow

This guide describes the checked-in MVP only. It is for local development and is not a production deployment procedure. See the [README](../README.md) for project status and architecture, the [project log](LOGFILE.md) for dated results, and [Testing and benchmarks](TESTING_AND_BENCHMARKS.md) for test coverage and reported measurements.

## 1. Prepare the local environment

Install Docker and its Compose plugin. From the repository root, copy the example environment file and replace both example values with private development values:

```bash
cp .env.example .env
```

`.env` is ignored by Git. `POSTGRES_PASSWORD` is used by the Compose PostgreSQL service, and `STONEBREAKER_API_KEY` must be at least eight characters. The application has no default API key. Do not commit `.env` or paste credentials into shared logs or issues.

## 2. Start the services

```bash
docker compose up --build
```

Compose starts PostgreSQL 16 and then the backend after PostgreSQL passes its health check. The backend runs as a non-root container user. Its DuckDB file is stored in the `duckdata` named volume; PostgreSQL data is in `pgdata`. The API is bound to `127.0.0.1:8000`, and PostgreSQL is not published to a host port.

The backend creates the schema on startup. `STONEBREAKER_SEED` defaults to `true`; if the database has no customers, startup seeds 40 customers, 10 products, and 500 orders. Existing data is not reseeded. This is not a schema migration system.

In another terminal, confirm the service is responding:

```bash
curl -i http://127.0.0.1:8000/health
```

The health endpoint does not require the API key. Open <http://127.0.0.1:8000> for the static console. The page itself is also unauthenticated; enter the `STONEBREAKER_API_KEY` value from your private `.env` file and select **Use key** to call protected APIs. The key is kept in browser `sessionStorage`.

### Run the backend without Docker

For a local Python run, use Python 3.12 and a reachable PostgreSQL database. From the repository root:

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
mkdir -p data
```

In that private shell, set `STONEBREAKER_API_KEY` to a private value of at least eight characters, `STONEBREAKER_PG_DSN` to the DSN of your local development database, and optionally `STONEBREAKER_DUCKDB_PATH` (default `./data/analytics.duckdb`). `STONEBREAKER_SEED` defaults to `true`; leave it enabled for a fresh database so startup creates the schema and sample data. To start:

```bash
uvicorn app.server:app --host 127.0.0.1 --port 8000
```

The application binds locally, and Uvicorn logs to the terminal. Do not copy real credentials into shared command history or documentation.

## 3. Place a transactional order

In the console, use customer `1`, product `1`, and a quantity from 1 to 1000, then choose **Place order**. The API validates the input; PostgreSQL checks that the customer and product exist, locks the product row, checks stock, decrements stock, and inserts the order in one transaction. Invalid input returns 422, missing customer/product returns 404, and insufficient stock returns 409. A failed operation does not leave a partial stock decrement.

To use the API from a terminal, read the key without echoing it and issue a request:

```bash
read -rsp 'Stonebreaker API key: ' KEY; printf '\n'
curl -i -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"customer_id":1,"product_id":1,"quantity":2}' \
  http://127.0.0.1:8000/api/orders
unset KEY
```

The OpenAPI page at <http://127.0.0.1:8000/docs> is unauthenticated and is useful for inspecting the API. Do not expose it or this development service to an untrusted network.

## 4. Refresh and query analytics

Analytics are not live views of PostgreSQL. In the console:

1. Select **Refresh now** to copy a consistent full snapshot of customers, products, and orders into DuckDB.
2. Select **Status** to see the last run, its result and row counts, and the last successful refresh time.
3. Run `revenue_by_category` and note the result.
4. Place another order and run the report again. It remains unchanged until a successful refresh.
5. Refresh, then rerun the report. The new order is now included.
6. Refresh again. The snapshot is replaced, not appended, so rows are not duplicated.

There are four fixed reports: `revenue_by_category`, `revenue_by_region`, `top_customers`, and `daily_revenue`; report limits are bounded to 100. A refresh copies PostgreSQL tables using a read-only `REPEATABLE READ` transaction and temporary CSV files, then replaces DuckDB tables in one transaction. Only one refresh can run at a time; a simultaneous request returns 409. No endpoint accepts arbitrary SQL.

Example report request:

```bash
read -rsp 'Stonebreaker API key: ' KEY; printf '\n'
curl -H "X-API-Key: $KEY" \
  'http://127.0.0.1:8000/api/analytics/reports/revenue_by_region?limit=5'
unset KEY
```

REST and GraphQL routes require `X-API-Key`. GraphQL is available at `POST /graphql`; the console and `/docs` are not protected by that key. `/health` is also unauthenticated.

## 5. Run the backend tests

Tests use a real PostgreSQL server. From the repository root:

```bash
cd backend
python -m pip install -r requirements.txt
pytest
```

The test fixture uses `STONEBREAKER_TEST_PG_DSN` if set. Otherwise it attempts to start a throwaway local PostgreSQL cluster using binaries under `/usr/lib/postgresql/*/bin`. It skips if those binaries are unavailable or the test process runs as root. The configured DSN must allow creating and dropping per-test databases. **Do not point tests at production or any database with valuable data.** If the fixture skips or cannot connect, provide a disposable local PostgreSQL admin DSN in `STONEBREAKER_TEST_PG_DSN`, then rerun `pytest`.

The tests cover transactional flows and rollback, authentication, report bounds, snapshot refresh/freshness/idempotence, error handling, GraphQL, input bounds, and concurrency. The test command does not run the scale benchmarks.

## 6. Run a benchmark only on disposable data

The commands below are measurement tools, not certification or a production readiness check. Run them from `backend/` with `PYTHONPATH=.`. Results are printed as JSON and appended to `backend/bench/results.jsonl`.

### DuckDB-only analytical benchmark

```bash
PYTHONPATH=. python -m bench.run olap --orders 1000000 \
  --duckdb /tmp/stonebreaker_olap_bench.duckdb
```

This generates synthetic data in the specified DuckDB file. The generator drops and recreates its `orders`, `products`, and `customers` tables. **Use a new, disposable file; an existing file at that path will lose those tables.**

### PostgreSQL data load

```bash
PYTHONPATH=. python -m bench.run pgload --dsn "$BENCH_DSN" --orders 1000000
```

`pgload` is destructive: it truncates `orders`, `products`, and `customers`, restarts identities, and writes synthetic rows in the PostgreSQL database selected by `BENCH_DSN`. **Never use a production or valuable database.** Create a dedicated disposable benchmark database and verify the DSN points to it before running this command.

### End-to-end snapshot refresh

```bash
PYTHONPATH=. python -m bench.run refresh --dsn "$BENCH_DSN" \
  --duckdb /tmp/stonebreaker_refresh_bench.duckdb
```

This reads the selected PostgreSQL database and writes/replaces tables in the DuckDB file. It is not read-only for DuckDB: choose a dedicated disposable path. Use generated benchmark data or a disposable database, not production data.

### HTTP mixed load and stress ramp

Start the local development service with a dedicated test database, then from `backend/` run:

```bash
read -rsp 'Stonebreaker API key: ' KEY; printf '\n'
export STONEBREAKER_API_KEY="$KEY"
unset KEY
PYTHONPATH=. python -m bench.run http --url http://127.0.0.1:8000 \
  --clients 16 --seconds 20
PYTHONPATH=. python -m bench.run stress --url http://127.0.0.1:8000 \
  --steps 4,16,64,128 --seconds 10
unset STONEBREAKER_API_KEY
```

The runner reads its default key from `STONEBREAKER_API_KEY`, avoiding a key on the process command line. The mixed workload includes order writes as well as reads and reports (20% writes by default); it changes the service's order data and stock. Use an isolated development database. The commands can impose substantial load; monitor the local machine and stop if needed.

For reported measurements, limitations, and the difference between the DuckDB-only run and PostgreSQL-to-DuckDB snapshot refresh, see [Testing and benchmarks](TESTING_AND_BENCHMARKS.md). The 1-billion DuckDB target is not a completed run, and the 10-million Hugging Face end-to-end test has not been verified.

## 7. View service logs and troubleshoot

View live Compose output:

```bash
docker compose logs --follow backend
docker compose logs --follow postgres
```

For a recent snapshot instead of a live stream, use `docker compose logs --tail=100 backend`. Locally run Uvicorn output appears in the terminal that launched it. These are actual service logs; [LOGFILE.md](LOGFILE.md) is a curated project record, not a runtime log. Review and redact output before sharing it because it may contain private configuration or data.

Common issues:

- **Compose rejects missing environment values:** ensure `.env` exists and both `POSTGRES_PASSWORD` and `STONEBREAKER_API_KEY` are set.
- **Backend exits because the key is missing or too short:** set `STONEBREAKER_API_KEY` to a private value of at least eight characters.
- **Backend cannot connect at startup:** check `docker compose ps` and PostgreSQL health/logs; the Compose backend waits for the database health check.
- **401 from a protected API:** provide the same `X-API-Key` value configured for the backend. The health endpoint, console page, and `/docs` do not require it.
- **No seed data appears:** seeding is enabled by default but does nothing if the database already contains customers. Compose named volumes persist when containers stop.
- **Analytics look stale:** refresh is manual. Check `/api/analytics/status` or the console's status and inspect backend logs for a failed refresh.
- **Test fixture skips or fails to start PostgreSQL:** configure `STONEBREAKER_TEST_PG_DSN` with a disposable admin DSN; tests do not run an automatic PostgreSQL cluster as root.
- **Port 8000 is occupied:** stop the other local service or change the host-side mapping in `docker-compose.yml` for your development environment.

## 8. Stop and reset safely

Stop containers while retaining local data:

```bash
docker compose down
```

Compose keeps `pgdata` and `duckdata` unless asked to remove volumes. **Destructive reset warning:** `docker compose down -v` deletes these named volumes, including all PostgreSQL and DuckDB data. Only run it when you deliberately intend to erase the local development dataset.

## 9. Development-only deployment boundary

The Compose file binds only to localhost and is provided for development. Do not deploy this configuration to production or expose it by changing the port binding. The MVP lacks TLS, real user authentication/authorization, rate limiting, managed secrets, GraphQL query limits, migrations, incremental/CDC sync, and production hardening. The requested 0.9/AI-ingestion and Hugging Face work is not verified as merged into this checkout; consult the [README status](../README.md) and [dated project log](LOGFILE.md).
