# Test, stress, security and benchmark suite

This is a **test and measurement harness**, not a certification. Nothing here shows "carrier grade" or production readiness,
and the 1-billion-row target has **not** been run (see "Scale status").

## What exists
| Area | Where | Command |
|---|---|---|
| Functional + security (auth on every route, injection payloads, input bounds, no raw-SQL surface, error leakage, malformed input) | `backend/tests/test_security.py`, `test_flows.py` | `cd backend && pytest` |
| Concurrency correctness (no overselling under 16 threads; concurrent refreshes; reads during refresh+writes) | `backend/tests/test_concurrency.py` | `pytest` |
| Data generator, up to N rows, in-engine and batched (PG `generate_series`, DuckDB `range`) | `backend/bench/datagen.py` | via `bench.run` |
| Analytical engine scale test (DuckDB only) | `bench/run.py olap` | `python -m bench.run olap --orders 1000000000 --duckdb /data/b.duckdb` |
| PostgreSQL load at scale | `bench/run.py pgload` | `python -m bench.run pgload --dsn <dsn> --orders N` |
| End-to-end PG→DuckDB refresh time | `bench/run.py refresh` | `python -m bench.run refresh --dsn <dsn> --duckdb <path>` |
| Mixed load / stress ramp over HTTP (writes, reads, reports; p50/p95/p99, error rate, throughput) | `bench/run.py http|stress` | `python -m bench.run stress --url ... --key $KEY --steps 4,16,64,128` |

Run bench commands from `backend/` with `PYTHONPATH=.`. Results are printed as JSON and appended to `backend/bench/results.jsonl` (git-ignored).

## Measured results (sandbox: 4 vCPU, 15 GB RAM, one machine running PG, DuckDB, API and load generator together)
Indicative only; not comparable to real hardware.

- **DuckDB analytical reports, 20M orders** (256 MB file, load 4.9 s): `revenue_by_category` 67 ms, `revenue_by_region` 63 ms, `top_customers` 151 ms, `daily_revenue` 300 ms (best of 3).
- **PG load**: 2M orders in 19.7 s (~100k rows/s) with in-database generation.
- **Snapshot refresh, 2M orders**: 3.0 s end to end (streamed `COPY` to temp CSV, then DuckDB load). An earlier row-by-row implementation took minutes at this size and was replaced because of this benchmark.
- **HTTP mixed load** (20% order writes, 50% order reads, 30% reports, 2M-order dataset, 0 errors at every step):

| clients | rps | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|
| 4 | 155 | 16.5 | 75.7 | 105.5 |
| 16 | 150 | 19.7 | 374 | 443 |
| 64 | 154 | 187 | 995 | 1049 |

Finding: throughput plateaus at ~150 rps and latency grows linearly with clients, i.e. saturation, not failure. Likely causes (not profiled): a new PostgreSQL connection per request (no pool), synchronous handlers in a limited threadpool, a single DuckDB lock, and the load generator sharing the 4 CPUs. Connection pooling is the first optimisation to try.

## Security strength: what is and is not covered
Covered by automated tests: authentication required on all routes, injection strings inert on every user-controlled input (REST + GraphQL), integer/size bounds, result-size cap, no SQL-accepting endpoint, no stack traces in refresh errors.
Not covered (no claim): penetration test, fuzzing at scale, dependency/CVE scanning in CI, TLS, rate limiting/brute-force protection, per-user authorisation, GraphQL depth/complexity limits, secrets management, audit logging, container hardening. A single shared API key is the only credential.

## Scale status ("up to 1 billion")
- Generator and DuckDB scale test accept `--orders 1000000000` but this was **not executed** here (expect roughly 15+ GB of DuckDB file and a long load on this machine; the 20M run is the largest verified). Extrapolating is not a measurement.
- The end-to-end path is bounded by the snapshot design: a full refresh rewrites every table, so 1B rows would take a long time and need ~2x temp disk. Incremental sync/CDC is the next milestone and required before that scale is meaningful for the full platform.
- PG at 1B rows needs a dedicated server with suitable storage; indexes/partitioning have not been designed.

## "Agility"
Interpreted as time-to-fresh-analytics: refresh duration (above) and staleness = time since last successful refresh (exposed by `/api/analytics/status`). Schema-change agility is not measured (no migrations yet).

## Next steps for a real certification effort
Dedicated multi-host load rig; pooled connections and re-run; soak tests (hours); failure injection (kill PG mid-refresh, disk full); fuzzing; SAST/DAST and dependency scanning in CI; TLS + real authn/z; 100M→1B staged runs with resource monitoring.
