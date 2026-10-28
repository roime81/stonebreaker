# Backup and restore runbook

This runbook describes a manual PostgreSQL backup and a derived DuckDB rebuild for the current single-node Compose setup. It is not a tested point-in-time recovery plan.

## Backup

1. Stop or quiesce application writes if a consistent application-level snapshot is required.
2. Set `DATABASE_URL` from the protected deployment secret store; do not put credentials in shell history or commit them.
3. Back up PostgreSQL in custom format:

   ```bash
   pg_dump --format=custom --no-owner --file=stonebreaker.dump "$DATABASE_URL"
   ```

4. Store the dump in encrypted, access-controlled storage. Record its creation time and checksum.
5. DuckDB holds a refreshable snapshot. Preserve its file if desired, but PostgreSQL remains the source of truth.

## Restore

1. Create an empty PostgreSQL database and restore the dump:

   ```bash
   createdb stonebreaker_restore
   pg_restore --no-owner --dbname=stonebreaker_restore stonebreaker.dump
   ```

2. Point Stonebreaker at the restored database and a fresh DuckDB path.
3. Start the application and verify `/healthz` and `/readyz`.
4. Authenticate with the service API key and call `POST /api/analytics/refresh` to rebuild the derived analytics snapshot.
5. Verify representative API reads and named analytical reports before directing traffic to the restored instance.

Test this procedure against an isolated copy before relying on it. No restore drill or recovery-time/recovery-point objective has been measured.
