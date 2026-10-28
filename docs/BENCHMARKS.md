# Hugging Face scale benchmark

## Dataset record

| Field | Record |
|---|---|
| Dataset | `HuggingFaceFW/fineweb` |
| Dataset card | https://huggingface.co/datasets/HuggingFaceFW/fineweb |
| License | ODC-BY 1.0, as stated by the public dataset card; verify applicable terms before redistribution |
| Revision / commit hash | **Not resolved in this sandbox.** The runner requires `--revision` with a 40-character immutable commit and records it in the raw result. |
| Total source row count | **Not verified here.** The benchmark requests the first 10,000,000 streamed rows; it does not claim that this is the repository's exact total row count. |
| Downloaded size | **Not measured.** Streaming avoids downloading the complete dataset; the bytes transferred are not currently recorded. |
| Achieved benchmark scale | **No run completed in this environment.** Do not interpret the requested target as a measured result. |

The sandbox could not resolve `huggingface.co`, and its PostgreSQL/Python test dependencies were not preinstalled. Therefore no dataset commit, source metadata, performance numbers, or 10-million-row output is fabricated or included.

## Reproducible command

Use an isolated PostgreSQL instance and enough disk for the table and database/WAL files. Install the existing backend requirements and the optional pinned Hugging Face reader:

```bash
pip install -r backend/requirements.txt datasets==3.3.2
export STONEBREAKER_PG_DSN='host=127.0.0.1 dbname=stonebreaker user=stonebreaker'
python bench/hf_10m.py \
  --revision <40-character-Hugging-Face-commit> \
  --rows 10000000 \
  --approve-offline-plan
```

The command streams `HuggingFaceFW/fineweb`, profiles only a bounded sample, generates and validates a deterministic offline proposal, and requires explicit approval before loading. It loads bounded batches through PostgreSQL `COPY` and DuckDB, upserts deterministic row IDs, reconciles source/load/reject counts, and verifies sample checksums. Re-running the same dataset revision and row count does not duplicate IDs.

The script writes raw JSON to `bench/results/` and prints the output path. Record/commit that raw result before adding any measured number to docs; retain the hardware, dataset revision, source/load/reject counts, and code revision. The manual GitHub Actions workflow is also available under **Actions → Hugging Face 10M benchmark** and preserves raw results as a workflow artifact.

## Metrics and limitations

The runner records achieved source rows, ingestion duration and throughput, process peak RSS, a small-sample DuckDB report p50/p95, hardware metadata, revision, and checksum/count validation. It does **not** yet measure full snapshot-refresh duration, OLTP read/write latency under ingestion, or API p50/p95/p99 under concurrent traffic; those fields are explicitly `null`, not estimates. The five report samples are a smoke measurement, not a statistically meaningful latency distribution.

No run results are presently checked into `bench/results/`. No benchmark measurements are claimed for this release. The runner is a benchmark path, not a resumable production ingestion service.
