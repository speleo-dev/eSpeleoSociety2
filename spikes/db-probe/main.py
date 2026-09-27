"""Phase 0 spike: verify connectivity from Cloud Run to the WebSupport PostgreSQL database.

Checks that the connection is encrypted (SSL) and measures round-trip latency.
The response never contains credentials or connection details.
"""

import ipaddress
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
            # Client-side view: is the TCP connection from Cloud Run encrypted?
            pgconn = conn.pgconn
            client_ssl = bool(pgconn.ssl_in_use)
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                server_version = cur.fetchone()[0]

                cur.execute("SELECT ssl, version, cipher FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
                ssl_row = cur.fetchone()

                # How PostgreSQL sees the client: a private/loopback address means a proxy
                # (connection pooler) sits between Cloud Run and PostgreSQL.
                cur.execute("SELECT host(inet_client_addr())")
                seen_client = cur.fetchone()[0]

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
        "client_ssl": client_ssl,
        "backend_ssl": bool(ssl_row and ssl_row[0]),
        "backend_sees_client_as": _classify_address(seen_client),
        "connect_ms": round(connect_ms, 1),
        "query_ms_median": round(statistics.median(timings), 1),
        "query_ms_max": round(max(timings), 1),
    }


def _classify_address(address: str | None) -> str:
    """Describe the client address category without exposing the address itself."""
    if not address:
        return "unix_socket"
    ip = ipaddress.ip_address(address)
    if ip.is_loopback:
        return "loopback (proxy on the DB server)"
    if ip.is_private:
        return "private network (proxy in front of DB)"
    return "public address (direct connection)"
