"""Benchmark / stress / concurrency runner. Results are measurements for THIS machine and dataset only.

  python -m bench.run olap   --orders 1000000 [--duckdb /tmp/b.duckdb]   # analytical engine scale test
  python -m bench.run http   --url http://127.0.0.1:8000 --key $KEY --clients 16 --seconds 20
  python -m bench.run stress --url ... --key ... --steps 4,16,64,128 --seconds 10
  python -m bench.run pgload --dsn postgresql://... --orders 1000000     # load PG at scale
  python -m bench.run refresh --dsn ... --duckdb /tmp/a.duckdb --key ... # end-to-end snapshot refresh time
All commands print JSON and append to bench/results.jsonl.
"""
import argparse
import json
import os
import statistics
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from app.olap import REPORTS

from . import datagen


def _pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    return round(s[min(len(s) - 1, int(len(s) * p / 100))] * 1000, 2)


def summarize(lat, errors, elapsed, codes):
    return {
        "requests": len(lat) + errors, "errors": errors, "error_rate": round(errors / max(1, len(lat) + errors), 4),
        "throughput_rps": round((len(lat) + errors) / elapsed, 1),
        "p50_ms": _pct(lat, 50), "p95_ms": _pct(lat, 95), "p99_ms": _pct(lat, 99),
        "max_ms": round(max(lat) * 1000, 2) if lat else None, "status_codes": codes,
    }


def _call(url, key, method="GET", body=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-API-Key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def run_http(url, key, clients, seconds, write_ratio=0.2, products=1000, customers=10000):
    """Mixed workload: OLTP writes + OLTP reads + OLAP reports. 4xx business errors are not failures; 5xx/timeouts are."""
    lat, codes, errors = [], {}, 0
    lock = threading.Lock()
    reports = sorted(REPORTS)
    stop = time.perf_counter() + seconds

    def worker(i):
        nonlocal errors
        n = i
        while time.perf_counter() < stop:
            n += 1
            r = (n * 2654435761 % 100) / 100
            t = time.perf_counter()
            if r < write_ratio:
                code = _call(url + "/api/orders", key, "POST",
                             {"customer_id": 1 + n % customers, "product_id": 1 + n % products, "quantity": 1})
            elif r < 0.7:
                code = _call(url + "/api/orders?limit=10", key)
            else:
                code = _call(f"{url}/api/analytics/reports/{reports[n % len(reports)]}?limit=10", key)
            d = time.perf_counter() - t
            with lock:
                codes[code] = codes.get(code, 0) + 1
                if code == 0 or code >= 500:
                    errors += 1
                else:
                    lat.append(d)

    t0 = time.perf_counter()
    with ThreadPoolExecutor(clients) as ex:
        list(ex.map(worker, range(clients)))
    return {"clients": clients, **summarize(lat, errors, time.perf_counter() - t0, codes)}


def run_olap(orders, path):
    import duckdb

    load = datagen.load_duckdb(path, orders)
    con = duckdb.connect(path, read_only=True)
    out = {}
    for name, (sql, _) in REPORTS.items():
        times = []
        for _ in range(3):
            t = time.perf_counter()
            con.execute(sql, [10]).fetchall()
            times.append(time.perf_counter() - t)
        out[name] = {"best_ms": round(min(times) * 1000, 1), "median_ms": round(statistics.median(times) * 1000, 1)}
    con.close()
    return {"orders": orders, "load": load, "db_bytes": os.path.getsize(path), "reports": out}


def run_refresh(dsn, duckdb_path, max_rows=100):
    from app.olap import Analytics

    a = Analytics(duckdb_path, dsn, max_rows)
    t = time.perf_counter()
    s = a.refresh()
    return {"refresh_seconds": round(time.perf_counter() - t, 2), "status": s["last_run"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["olap", "http", "stress", "pgload", "refresh"])
    ap.add_argument("--orders", type=int, default=1_000_000)
    ap.add_argument("--duckdb", default="/tmp/stonebreaker_bench.duckdb")
    ap.add_argument("--dsn")
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--key", default=os.environ.get("STONEBREAKER_API_KEY", ""))
    ap.add_argument("--clients", type=int, default=16)
    ap.add_argument("--steps", default="4,16,64,128")
    ap.add_argument("--seconds", type=int, default=10)
    a = ap.parse_args()
    if a.cmd == "olap":
        res = run_olap(a.orders, a.duckdb)
    elif a.cmd == "pgload":
        res = datagen.load_postgres(a.dsn, a.orders)
    elif a.cmd == "refresh":
        res = run_refresh(a.dsn, a.duckdb)
    elif a.cmd == "http":
        res = run_http(a.url, a.key, a.clients, a.seconds)
    else:
        res = [run_http(a.url, a.key, int(c), a.seconds) for c in a.steps.split(",")]
    res = {"cmd": a.cmd, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "result": res}
    print(json.dumps(res, indent=2, default=str))
    with open(os.path.join(os.path.dirname(__file__), "results.jsonl"), "a") as f:
        f.write(json.dumps(res, default=str) + "\n")


if __name__ == "__main__":
    main()
