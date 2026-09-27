"""Phase 0 spike: verify connectivity from Cloud Run to the WebSupport PostgreSQL database.

Checks that the connection is encrypted (SSL) and measures round-trip latency.
The response never contains credentials or connection details.
"""

import os
import statistics
import time

import psycopg
from fastapi import FastAPI

app = FastAPI()

ROUND_TRIPS = 20


@app.get("/probe")
def probe() -> dict:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return {"ok": False, "error": "DATABASE_URL is not set"}

    started = time.perf_counter()
    try:
        # sslmode=require: the connection fails if the server does not offer SSL.
        with psycopg.connect(database_url, sslmode="require", connect_timeout=10) as conn:
            connect_ms = (time.perf_counter() - started) * 1000
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                server_version = cur.fetchone()[0]

                cur.execute("SELECT ssl, version, cipher FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
                ssl_row = cur.fetchone()

                timings = []
                for _ in range(ROUND_TRIPS):
                    t0 = time.perf_counter()
                    cur.execute("SELECT 1")
                    cur.fetchone()
                    timings.append((time.perf_counter() - t0) * 1000)
    except Exception as exc:  # report the failure class without leaking the connection string
        return {"ok": False, "error": type(exc).__name__, "detail": str(exc).split("\n")[0][:200]}

    return {
        "ok": True,
        "server_version": server_version,
        "ssl": bool(ssl_row and ssl_row[0]),
        "ssl_protocol": ssl_row[1] if ssl_row else None,
        "ssl_cipher": ssl_row[2] if ssl_row else None,
        "connect_ms": round(connect_ms, 1),
        "query_ms_median": round(statistics.median(timings), 1),
        "query_ms_max": round(max(timings), 1),
    }
