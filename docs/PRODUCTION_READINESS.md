# 0.9 beta readiness checklist

This checklist is evidence-based. **Done** means the stated behavior is implemented and has direct evidence; **partial** means some behavior exists but is incomplete or unverified; **not done** means there is no verified implementation. The release remains a prerelease and must not be treated as production-ready until the blocking gaps below are closed and tested in the intended environment.

## Web client

| Criterion | Status | Evidence |
|---|---|---|
| Responsive web console, loading/error feedback, keyboard-visible focus | partial | `backend/app/static/index.html`; no automated accessibility audit |
| OLTP/OLAP health and refresh state | partial | UI calls `/healthz`, `/readyz`, `/api/analytics/status`; backend in `backend/app/main.py` |
| Data browser with server-side keyset pagination | partial | `GET /api/orders/page`, `backend/app/oltp.py::page_orders`; not virtualized |
| Fixed analytical reports with chart rendering | partial | Named report catalogue in `backend/app/olap.py`; basic SVG-free bars in static console; no chart tests |
| Login/session and real per-user roles | not done | API-key dependency remains shared; `backend/app/main.py::require_key` |
| Ingestion job wizard, durable job history/progress, error and audit views | not done | No persistent job or audit model |
| Transformation proposal review | partial | Proposal and validation endpoints plus UI; not persisted, versioned, or attached to an ingestion job |
| No arbitrary SQL from the UI | done | Static UI calls named API endpoints only; fixed report SQL in `backend/app/olap.py`; `backend/tests/test_security.py::test_no_raw_sql_surface` |
| Frontend component tests and ingest-review-query end-to-end test | not done | No frontend test runner or browser E2E suite exists |

## Ingestion and transformation

| Criterion | Status | Evidence |
|---|---|---|
| CSV, JSON array, JSONL/NDJSON streaming readers | partial | `backend/app/ingestion.py::iter_rows`; reader tests in `backend/tests/test_ingestion.py` |
| Parquet reader | partial | DuckDB-backed reader in `backend/app/ingestion.py`; no Parquet fixture test |
| Hugging Face streaming at a pinned revision | partial | `bench/hf_10m.py` requires an immutable 40-character revision; network was unavailable to verify a live run |
| Resumable background jobs, idempotency, progress, retry, and row-count persistence | not done | Benchmark batches are idempotent by deterministic row IDs but there is no application job/checkpoint service |
| Type/null/cardinality/range/outlier/PII-name profiling | partial | `profile_rows`; profile uses a bounded sample and a heuristic PII-name check |
| Pluggable deterministic and mock providers | done | `RuleBasedProvider`, `MockProvider`, and provider test in `backend/tests/test_ingestion.py` |
| Optional remote provider configured by environment | partial | `HttpProposalProvider` in `backend/app/ingestion.py`; requires HTTPS; no live provider contract test |
| Restricted plan validation; no execution of free-form SQL/code | done | `validate_plan` and `apply_plan`; adversarial operation cases in `backend/tests/test_ingestion.py` |
| Prompt-injection/content minimization | partial | Remote provider receives the profile, not sample rows; profiles still contain column names and aggregate statistics, and adversarial HTTP-payload tests are not yet present |
| User approval, plan versioning, audit trail | partial | UI requires a review/approval call; approval is not durable or associated with a user/job |
| Per-job quality report, quarantine, and schema-drift detection | not done | No persistent ingestion job or quarantine schema |

## Large-data path and analytics

| Criterion | Status | Evidence |
|---|---|---|
| PostgreSQL bulk load and DuckDB-native ingestion in bounded batches | partial | `bench/hf_10m.py` uses PostgreSQL `COPY` and DuckDB batches; end-to-end scale not run |
| Idempotent benchmark re-run and count/checksum verification | partial | Deterministic row IDs, upsert, reconciled counts and sample hashes in `bench/hf_10m.py`; not executed here |
| Incremental refresh/watermark/CDC | not done | `backend/app/olap.py::Analytics.refresh` remains full snapshot |
| Refresh does not block readers | not done | Refresh holds the DuckDB connection lock while replacing the snapshot |
| PostgreSQL indexes/partitioning and connection pooling | not done | `backend/app/oltp.py::SCHEMA` has primary keys only; `connect` opens a connection per call |
| Query timeout and result limits | partial | PostgreSQL timeout in `backend/app/oltp.py::connect`; report bounds in `backend/app/olap.py`; no global API body/result budget |
| Keyset pagination | partial | Orders have `after_id` keyset API; products and other large tables have no paginated browser/API |
| Columnar/partitioned Parquet layout and before/after EXPLAIN evidence | not done | No maintained Parquet layout or recorded query-plan comparison |
| 10-million-row Hugging Face result with hardware and raw output committed | not done | No full run could be performed; no raw result is claimed. See `docs/BENCHMARKS.md` |

## Operations, security, and release process

| Criterion | Status | Evidence |
|---|---|---|
| Environment config and required API-key validation | partial | `backend/app/config.py::load_settings`; configuration remains small and not comprehensively validated |
| Versioned database migrations and tested upgrade | not done | Schema DDL remains inline in `backend/app/oltp.py`; see `docs/UPGRADE.md` |
| `/healthz` and database-aware `/readyz` | done | Routes in `backend/app/main.py`; no separate integration test yet |
| Structured JSON logging, request IDs, metrics, OpenTelemetry hooks | partial | Request ID response header, basic request counter at `/metrics`; no structured logging or OTel |
| Rate limiting, explicit CORS, security headers | partial | Basic security headers are emitted; no rate limiter or configurable CORS policy |
| TLS guidance and graceful shutdown | partial | Local-only deployment guidance in README; analytics connection closes in FastAPI lifespan; no TLS deployment or shutdown integration test |
| Backup/restore runbook | partial | `docs/BACKUP_RESTORE.md`; restore exercise not recorded |
| Non-root container and prod-like compose | partial | `backend/Dockerfile` uses a non-root user; base image and service versions are not digest-pinned; compose is development-only |
| Kubernetes/Helm deployment | not done | No Kubernetes manifests or chart |
| Automated lint/type/frontend/E2E/container/dependency-scan CI | not done | `.github/workflows/hf-10m.yml` is manual benchmark-only; no general CI workflow |
| Version/changelog/security/upgrade notes | partial | `CHANGELOG.md`, `SECURITY.md`, and `docs/UPGRADE.md` exist; 0.9 API/versioning compatibility has not been independently reviewed |
| MySQL compatibility, full CDC, automatic cost-based routing | not done | No implementation or test evidence; no compatibility claim is made |

## Beta exit blockers

Before calling this build production-usable, implement and validate user authentication/RBAC, durable ingestion jobs and audit/approval persistence, database migrations, the missing operational controls, backup/restore and upgrade drills, and deployment hardening. Add automated frontend/E2E and CI coverage, then run and record the full benchmark on documented hardware. The checklist should be updated only with direct evidence from those runs.
