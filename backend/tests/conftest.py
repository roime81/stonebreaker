import os
import shutil
import socket
import subprocess
import tempfile
import glob

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.seed import seed

KEY = "test-key-123456"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def pg_admin_dsn():
    """Use STONEBREAKER_TEST_PG_DSN if set, else start a throwaway local PostgreSQL cluster."""
    dsn = os.environ.get("STONEBREAKER_TEST_PG_DSN")
    if dsn:
        yield dsn
        return
    bins = glob.glob("/usr/lib/postgresql/*/bin")
    if not bins:
        pytest.skip("no PostgreSQL available; set STONEBREAKER_TEST_PG_DSN")
    bin_dir = sorted(bins)[-1]
    tmp = tempfile.mkdtemp()
    port = _free_port()
    data = os.path.join(tmp, "data")
    env = {**os.environ, "LC_ALL": "C"}
    if os.geteuid() == 0:
        pytest.skip("cannot run initdb as root; set STONEBREAKER_TEST_PG_DSN")
    subprocess.run([f"{bin_dir}/initdb", "-D", data, "-A", "trust", "-U", "postgres"], check=True, capture_output=True, env=env)
    subprocess.run([f"{bin_dir}/pg_ctl", "-D", data, "-o", f"-p {port} -k {tmp} -c listen_addresses=127.0.0.1", "-l", os.path.join(tmp, "pg.log"), "-w", "start"],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    try:
        yield f"host=127.0.0.1 port={port} user=postgres dbname=postgres"
    finally:
        subprocess.run([f"{bin_dir}/pg_ctl", "-D", data, "-m", "immediate", "stop"], capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture()
def settings(pg_admin_dsn, tmp_path):
    """Fresh database per test, seeded with a small dataset."""
    name = f"sb_{os.urandom(4).hex()}"
    with psycopg.connect(pg_admin_dsn, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {name}")
    dsn = " ".join(p for p in pg_admin_dsn.split() if not p.startswith("dbname=")) + f" dbname={name}"
    seed(dsn, orders=50)
    yield Settings(pg_dsn=dsn, duckdb_path=str(tmp_path / "a.duckdb"), api_key=KEY)
    with psycopg.connect(pg_admin_dsn, autocommit=True) as c:
        c.execute(f"DROP DATABASE {name} WITH (FORCE)")


@pytest.fixture()
def client(settings):
    with TestClient(create_app(settings), headers={"X-API-Key": KEY}) as c:
        c.settings = settings
        yield c
