"""Connection pool management for PostgreSQL."""

import hashlib
import threading
from contextlib import contextmanager
from typing import Iterator, Optional

import psycopg
from psycopg_pool import ConnectionPool

from src.storage import Profile


class PoolManager:
    """Manages connection pools with read-only enforcement and caching."""

    _lock = threading.Lock()
    _cache: dict[str, ConnectionPool] = {}

    def __init__(self, profile: Profile, database: Optional[str] = None) -> None:
        self.profile = profile
        self.current_database = database or profile.database or "postgres"

    def set_database(self, database: str) -> None:
        """Switches the active database for the connection."""
        if not database or not database.strip():
            raise ValueError("Database name cannot be empty.")
        self.current_database = database.strip()

    def get_conninfo(self, db_override: Optional[str] = None) -> str:
        """Constructs a PostgreSQL libpq connection string."""
        target_db = db_override or self.current_database
        parts = [
            f"host={self.profile.host}",
            f"port={self.profile.port}",
            f"dbname={target_db}",
            f"user={self.profile.username}",
            f"sslmode={self.profile.sslmode}",
        ]
        if self.profile.password:
            parts.append(f"password={self.profile.password}")
        return " ".join(parts)

    @staticmethod
    def _pool_key(profile: Profile, database: str) -> str:
        # Include a hash of sensitive/mutable fields to detect credential changes.
        secret = f"{profile.password or ''}:{profile.statement_timeout_ms}"
        secret_hash = hashlib.sha256(secret.encode()).hexdigest()[:12]
        return f"{profile.host}:{profile.port}/{database}/{profile.username}/{profile.sslmode}/{secret_hash}"

    def get_pool(self, db_override: str | None = None) -> ConnectionPool:
        target_db = db_override or self.current_database
        key = self._pool_key(self.profile, target_db)
        with self._lock:
            if key not in self._cache:
                conninfo = self.get_conninfo(db_override=target_db)
                self._cache[key] = ConnectionPool(
                    conninfo,
                    min_size=1,
                    max_size=3,
                    open=True,
                    timeout=10.0,
                    kwargs={
                        "options": f"-c default_transaction_read_only=on -c statement_timeout={self.profile.statement_timeout_ms}",
                        "connect_timeout": 5,
                    },
                )
            return self._cache[key]

    @contextmanager
    def read_only_transaction(self, conn: psycopg.Connection) -> Iterator[None]:
        """Runs a transaction with an explicit PostgreSQL read-only mode."""
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
            yield

    @contextmanager
    def connect(self, db_override: str | None = None) -> Iterator[psycopg.Connection]:
        """Yields a read-only connection from the pool."""
        with self.get_pool(db_override).connection() as conn:
            with self.read_only_transaction(conn):
                yield conn

    def test_connection(self, timeout: float = 5.0) -> tuple[bool, str]:
        """Tests the connection and returns (success, message_or_version)."""
        try:
            with self.get_pool().connection(timeout=timeout) as conn:
                with self.read_only_transaction(conn):
                    with conn.cursor() as cur:
                        cur.execute("SELECT version();")
                        row = cur.fetchone()
                        version = row[0] if row else "Unknown PostgreSQL version"
                        return True, version
        except Exception as e:
            return False, str(e)

    @classmethod
    def close_all(cls) -> None:
        """Closes all cached connection pools."""
        with cls._lock:
            for pool in cls._cache.values():
                try:
                    pool.close()
                except Exception:
                    pass
            cls._cache.clear()
