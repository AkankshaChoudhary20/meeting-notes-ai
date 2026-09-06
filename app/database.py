"""Thin synchronous Postgres access layer (psycopg 3).

Kept intentionally simple for this MVP: a small connection pool and plain
SQL, no ORM. Endpoints that touch the DB are defined as regular ``def``
functions in main.py so FastAPI runs them in its worker threadpool, which
keeps this synchronous code from blocking the event loop.
"""
import logging
from contextlib import contextmanager
from typing import Any, Iterator, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import DATABASE_URL

logger = logging.getLogger(__name__)

_pool: Optional[ConnectionPool] = None


def init_pool(min_size: int = 1, max_size: int = 10) -> None:
    """Create the connection pool. Safe to call more than once."""
    global _pool
    if _pool is not None:
        return
    # open=False: don't block/fail at construction time if Postgres isn't up
    # yet (e.g. during app startup before `docker compose up` finishes).
    _pool = ConnectionPool(
        conninfo=DATABASE_URL, min_size=min_size, max_size=max_size, open=False
    )
    _pool.open(wait=False)
    logger.info("Postgres connection pool initialized")


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_conn() -> Iterator[Any]:
    """Borrow a connection from the pool, returning it when done."""
    if _pool is None:
        init_pool()
    assert _pool is not None
    with _pool.connection() as conn:
        yield conn


def check_connection() -> bool:
    """Used by /health — returns True if the DB is reachable."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except Exception as exc:  # noqa: BLE001 - deliberately broad for a health check
        logger.warning("Database health check failed: %s", exc)
        return False


def dict_cursor(conn):
    return conn.cursor(row_factory=dict_row)
