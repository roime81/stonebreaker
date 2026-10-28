#!/usr/bin/env python3
"""Reproducible, bounded-memory Hugging Face -> PostgreSQL + DuckDB benchmark.

Run from the repository root after installing backend requirements and `datasets`:
  python bench/hf_10m.py --revision <40-character-HF-commit> --dsn "$STONEBREAKER_PG_DSN" --approve-offline-plan
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import platform
import re
import resource
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import duckdb
import psycopg

from app.ingestion import RuleBasedProvider, apply_plan, profile_rows, validate_plan

DATASET = "HuggingFaceFW/fineweb"
BATCH_SIZE = 10_000


def repository_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True, help="Pinned 40-character Hugging Face dataset commit")
    parser.add_argument("--rows", type=int, default=10_000_000)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--dsn", default=os.environ.get("STONEBREAKER_PG_DSN"))
    parser.add_argument("--duckdb", default="./data/hf_10m.duckdb")
    parser.add_argument("--approve-offline-plan", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", args.revision):
        parser.error("--revision must be an immutable 40-character commit hash")
    if not args.dsn:
        parser.error("--dsn or STONEBREAKER_PG_DSN is required")
    if args.rows < 1 or args.batch_size < 1 or args.batch_size > 100_000:
        parser.error("rows and batch size must be positive; batch size cannot exceed 100000")
    if not args.approve_offline_plan:
        parser.error("inspect the deterministic proposal, then pass --approve-offline-plan to load data")

    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise SystemExit("Install the optional Hugging Face reader: pip install datasets==3.3.2") from exc

    source = iter(load_dataset(DATASET, split="train", revision=args.revision, streaming=True))
    sample = list(itertools.islice(source, 100))
    if not sample:
        raise SystemExit("the pinned dataset split is empty")
    profile = profile_rows(sample)
    proposal = validate_plan((column["name"] for column in profile["columns"]), RuleBasedProvider().propose(profile))
    print(json.dumps({"proposal_provider": "offline", "profile": profile, "approved_plan": proposal}, default=str))
    records = itertools.chain(sample, source)

    dsn = args.dsn
    duck_path = Path(args.duckdb)
    duck_path.parent.mkdir(parents=True, exist_ok=True)
    table = "stonebreaker_hf_10m"
    started = time.perf_counter()
    source_count = rejects = 0
    expected_samples: dict[int, tuple[str, str]] = {}
    with psycopg.connect(dsn) as pg, duckdb.connect(str(duck_path)) as duck:
        pg.execute(
            f"CREATE TABLE IF NOT EXISTS {table} (id BIGINT PRIMARY KEY, text TEXT NOT NULL, "
            "token_count INTEGER, language TEXT, sha256 TEXT NOT NULL)"
        )
        pg.execute(
            f"CREATE TEMP TABLE sb_batch_hf (id BIGINT PRIMARY KEY, text TEXT NOT NULL, "
            "token_count INTEGER, language TEXT, sha256 TEXT NOT NULL) ON COMMIT PRESERVE ROWS"
        )
        duck.execute(
            f"CREATE TABLE IF NOT EXISTS {table} (id BIGINT PRIMARY KEY, text VARCHAR NOT NULL, "
            "token_count INTEGER, language VARCHAR, sha256 VARCHAR NOT NULL)"
        )
        batch: list[tuple[int, str, int | None, str | None, str]] = []

        def flush() -> None:
            if not batch:
                return
            pg.execute("TRUNCATE sb_batch_hf")
            with pg.cursor().copy(
                "COPY sb_batch_hf (id, text, token_count, language, sha256) FROM STDIN"
            ) as copy:
                for row in batch:
                    copy.write_row(row)
            pg.execute(
                f"INSERT INTO {table} SELECT * FROM sb_batch_hf "
                "ON CONFLICT (id) DO UPDATE SET text=EXCLUDED.text, token_count=EXCLUDED.token_count, "
                "language=EXCLUDED.language, sha256=EXCLUDED.sha256"
            )
            pg.commit()
            duck.executemany(
                f"INSERT OR REPLACE INTO {table} VALUES (?, ?, ?, ?, ?)",
                batch,
            )
            batch.clear()

        for raw in records:
            if source_count >= args.rows:
                break
            row_id = source_count
            source_count += 1
            try:
                transformed = apply_plan(raw, proposal)
                text = transformed.get("text")
                if not isinstance(text, str):
                    raise ValueError("text field is missing or not a string")
                token_count = transformed.get("token_count")
                token_count = int(token_count) if token_count is not None else None
                language = transformed.get("language")
                language = str(language)[:128] if language is not None else None
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                batch.append((row_id, text, token_count, language, digest))
                if row_id in (0, args.rows - 1):
                    expected_samples[row_id] = (text, digest)
            except (TypeError, ValueError, UnicodeError):
                rejects += 1
                pg.execute(f"DELETE FROM {table} WHERE id=%s", (row_id,))
                pg.commit()
                duck.execute(f"DELETE FROM {table} WHERE id=?", [row_id])
            if len(batch) >= args.batch_size:
                flush()
        flush()
        if source_count != args.rows:
            raise RuntimeError(f"source ended at {source_count} rows; requested {args.rows}")
        pg_count = pg.execute(f"SELECT count(*) FROM {table} WHERE id < %s", (source_count,)).fetchone()[0]
        duck_count = duck.execute(f"SELECT count(*) FROM {table} WHERE id < ?", [source_count]).fetchone()[0]
        if source_count != pg_count + rejects or source_count != duck_count + rejects:
            raise RuntimeError("source/load/reject counts do not reconcile")
        for row_id, expected in expected_samples.items():
            pg_sample = pg.execute(f"SELECT text, sha256 FROM {table} WHERE id=%s", (row_id,)).fetchone()
            duck_sample = duck.execute(f"SELECT text, sha256 FROM {table} WHERE id=?", [row_id]).fetchone()
            if pg_sample != expected or duck_sample != expected:
                raise RuntimeError(f"sample checksum mismatch at row {row_id}")
        query_times = []
        for _ in range(5):
            before = time.perf_counter()
            duck.execute(f"SELECT language, count(*), avg(token_count) FROM {table} GROUP BY language").fetchall()
            query_times.append((time.perf_counter() - before) * 1000)

    elapsed = time.perf_counter() - started
    query_times.sort()
    result = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": DATASET,
        "license": "ODC-BY 1.0 (dataset card; verify applicable terms before use)",
        "dataset_revision": args.revision,
        "dataset_total_rows": None,
        "dataset_size_bytes": None,
        "requested_rows": args.rows,
        "source_rows": source_count,
        "loaded_postgres_rows": pg_count,
        "loaded_duckdb_rows": duck_count,
        "rejects": rejects,
        "count_reconciles": source_count == pg_count + rejects == duck_count + rejects,
        "sample_checksums_verified": list(expected_samples),
        "ingestion_seconds": round(elapsed, 3),
        "ingestion_rows_per_second": round(source_count / elapsed, 2),
        "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1024 if sys.platform != "darwin" else 1),
        "duckdb_report_latency_ms": {"p50": query_times[2], "p95": query_times[-1]},
        "refresh_seconds": None,
        "api_latency_ms": None,
        "oltp_during_ingestion_latency_ms": None,
        "hardware": {"platform": platform.platform(), "processor": platform.processor(), "cpu_count": os.cpu_count()},
        "revision": repository_revision(),
    }
    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    result_path = results_dir / f"hf10m-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"Raw result: {result_path}")


if __name__ == "__main__":
    main()
