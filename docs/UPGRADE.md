# Upgrade notes from the MVP

This beta-candidate branch preserves the existing REST paths and GraphQL schema and adds endpoints; it does not include a database migration framework. It is not safe to treat future schema changes as automatically upgradeable.

## Current rollout

1. Back up PostgreSQL using [the backup/restore runbook](BACKUP_RESTORE.md).
2. Preserve `.env` values outside source control and verify `STONEBREAKER_API_KEY` is present.
3. Build and start the application using the existing Compose configuration.
4. Check `/healthz`, `/readyz`, and the protected API before routing traffic.
5. If DuckDB compatibility or refresh state is uncertain, use a fresh DuckDB file and run a full refresh from PostgreSQL.

The existing PostgreSQL tables are created with idempotent inline DDL. There is no migration version table, rollback mechanism, or automated schema-upgrade test yet. Do not apply this build to a production database without a separately tested backup, staging rehearsal, and rollback plan.

## Compatibility notes

- Existing service API-key authentication and routes remain. The console continues to use the service key; this is not end-user authentication.
- New endpoints include keyset order pagination and transformation proposal/validation.
- Snapshot refresh remains full replacement; it is not incremental CDC.
