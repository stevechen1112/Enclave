"""Process-wide transaction read-only barrier for production shadow runs."""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import event


@contextmanager
def process_read_only(engine):
    """Force every transaction opened through ``engine`` to be read-only."""
    def _readonly(conn):
        conn.exec_driver_sql("SET TRANSACTION READ ONLY")

    event.listen(engine, "begin", _readonly)
    try:
        yield
    finally:
        event.remove(engine, "begin", _readonly)

