# Test, stress, security and benchmark suite

This is a **test and measurement harness**, not a certification. Nothing here shows production readiness.
The historical measurements formerly documented in this file did not have committed raw output and are removed rather than presented as verified results.

## What exists
| Area | Where | Command |
|---|---|---|
| Functional + security (auth on every route, injection payloads, input bounds, no raw-SQL surface, error leakage, malformed input) | `backend/tests/test_security.py`, `test_flows.py` | `cd backend && pytest` |
| Concurrency correctness (no overselling under 16 threads; concurrent refreshes; reads during refresh+writes) | `backend/tests/test_concurrency.py` | `pytest` |
| Data generator, up to N rows, in-engine and batched (PG `generate_series`, DuckDB `range`) | `backend/bench/datagen.py` | via `bench.run` |
| Analytical engine scale test (DuckDB only) | `bench/run.py olap` | `python -m bench.run olap --orders N --duckdb /data/b.duckdb` |
| PostgreSQL load at scale | `bench/run.py pgload` | `python -m bench.run pgload --dsn <dsn> --orders N` |
| End-to-end PG→DuckDB refresh time | `bench/run.py refresh` | `python -m bench.run refresh --dsn <dsn> --duckdb <path>` |
| Hugging Face stream to PostgreSQL and DuckDB | `bench/hf_10m.py` | See [BENCHMARKS.md](BENCHMARKS.md); requires explicit pinned dataset commit |
| Mixed load / stress ramp over HTTP (writes, reads, reports; p50/p95/p99, error rate, throughput) | `bench/run.py http|stress` | `python -m bench.run stress --url ... --key $KEY --steps <client-counts>` |

Run bench commands from `backend/` with `PYTHONPATH=.`. Results are printed as JSON and appended to `backend/bench/results.jsonl` (git-ignored).

## Measured results

No benchmark results are currently verified in this checkout because no raw run output is committed. Run a benchmark on the target hardware and preserve its raw output before documenting performance figures.

## Security strength: what is and is not covered
Covered by automated tests: authentication required on all routes, injection strings inert on every user-controlled input (REST + GraphQL), integer/size bounds, result-size cap, no SQL-accepting endpoint, no stack traces in refresh errors.
Not covered (no claim): penetration test, fuzzing at scale, dependency/CVE scanning in CI, TLS, rate limiting/brute-force protection, per-user authorisation, GraphQL depth/complexity limits, secrets management, audit logging, container hardening. A single shared API key is the only credential.

## Scale status
- No million-row or larger result is claimed by this document. The optional HF workflow and runner are documented in [BENCHMARKS.md](BENCHMARKS.md); no 10M run has completed in this environment.
- The end-to-end analytics path still uses full snapshot replacement. Incremental sync/CDC is not implemented.

## Freshness
Refresh staleness is exposed by `/api/analytics/status`. Schema-change agility is not measured (no migrations yet).

## Next steps for a real certification effort
Dedicated multi-host load rig; pooled connections and re-run; soak tests; failure injection (kill PG mid-refresh, disk full); fuzzing; SAST/DAST and dependency scanning in CI; TLS + real authn/z; staged scale runs with resource monitoring.
