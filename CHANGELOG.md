# Changelog

## 0.9.0-beta.1

- Expanded the static console with health/status views, keyset-paged orders, report charts, and transformation proposal review.
- Added bounded sample profiling, an offline transformation provider, an optional HTTPS JSON provider, and validation for the `trim`, `rename`, and `cast` proposal operations.
- Added keyset pagination for orders, request IDs, basic security headers, `/healthz`, `/readyz`, and a basic Prometheus text endpoint.
- Added a streaming Hugging Face benchmark runner and a manually triggered GitHub Actions workflow.
- Added beta-readiness, benchmark, backup/restore, and upgrade documentation.
- This release does not provide production-grade per-user authentication, durable ingestion jobs, migrations, incremental sync, or a completed 10-million-row measurement. See the readiness checklist.
