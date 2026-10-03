"""Connection pool management for PostgreSQL."""

import hashlib
import threading
from collections import OrderedDict
from contextlib import ExitStack, contextmanager
from typing import Any, Iterable, Iterator, Optional

import psycopg
from psycopg_pool import ConnectionPool, PoolClosed

from src.storage import Profile

# Maximum number of pools kept per process; the least recently used is evicted.
MAX_POOLS = 4
# Maximum connections held by a single pool.
POOL_MAX_SIZE = 3
# Seconds an idle connection is kept before the pool closes it.
POOL_MAX_IDLE_S = 60.0
# Reported to the server so backends opened by this tool are identifiable.
APPLICATION_NAME = "mcp-postgresql"


def _close_quietly(pools: Iterable[ConnectionPool]) -> None:
    """Closes pools, ignoring errors. Must be called outside the cache lock."""
    for pool in pools:
        try:
            pool.close()
        except Exception:
            pass


class PoolManager:
    """Manages connection pools with read-only enforcement and caching."""

    _lock = threading.Lock()
    _cache: "OrderedDict[str, ConnectionPool]" = OrderedDict()

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
    def _pool_identity(profile: Profile, database: str) -> str:
        return f"{profile.host}:{profile.port}/{database}/{profile.username}/{profile.sslmode}"

    @staticmethod
    def _pool_key(profile: Profile, database: str) -> str:
        # Include a hash of sensitive/mutable fields to detect credential changes.
        secret = f"{profile.password or ''}:{profile.statement_timeout_ms}"
        secret_hash = hashlib.sha256(secret.encode()).hexdigest()[:12]
        return f"{PoolManager._pool_identity(profile, database)}/{secret_hash}"

    def _connect_kwargs(self) -> dict[str, Any]:
        """Connection parameters shared by pooled and unpooled connections."""
        return {
            "options": f"-c default_transaction_read_only=on -c statement_timeout={self.profile.statement_timeout_ms}",
            "connect_timeout": 5,
            "application_name": APPLICATION_NAME,
        }

    def get_pool(self, db_override: str | None = None) -> ConnectionPool:
        target_db = db_override or self.current_database
        identity = self._pool_identity(self.profile, target_db)
        key = self._pool_key(self.profile, target_db)
        to_close: list[ConnectionPool] = []
        with self._lock:
            pool = self._cache.get(key)
            if pool is not None:
                self._cache.move_to_end(key)
                return pool

            # Same target with different credentials/timeout: the old pool is stale.
            for stale_key in [k for k in self._cache if k.rsplit("/", 1)[0] == identity]:
                to_close.append(self._cache.pop(stale_key))

            pool = ConnectionPool(
                self.get_conninfo(db_override=target_db),
                min_size=0,
                max_size=POOL_MAX_SIZE,
                max_idle=POOL_MAX_IDLE_S,
                open=True,
                timeout=10.0,
                kwargs=self._connect_kwargs(),
            )
            self._cache[key] = pool

            while len(self._cache) > MAX_POOLS:
                _, evicted = self._cache.popitem(last=False)
                to_close.append(evicted)

        # Closing waits for in-flight connections, so never hold the lock here.
        _close_quietly(to_close)
        return pool

    @contextmanager
    def read_only_transaction(self, conn: psycopg.Connection) -> Iterator[None]:
        """Runs a transaction with an explicit PostgreSQL read-only mode."""
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
            yield

    def _checkout(self, stack: ExitStack, db_override: str | None) -> psycopg.Connection:
        """Checks out a connection, retrying once if the pool was closed concurrently."""
        try:
            return stack.enter_context(self.get_pool(db_override).connection())
        except PoolClosed:
            # The pool was evicted by another thread; get_pool returns a fresh one.
            return stack.enter_context(self.get_pool(db_override).connection())

    @contextmanager
    def connect(self, db_override: str | None = None) -> Iterator[psycopg.Connection]:
        """Yields a read-only connection from the pool."""
        with ExitStack() as stack:
            conn = self._checkout(stack, db_override)
            stack.enter_context(self.read_only_transaction(conn))
            yield conn

    def test_connection(self, timeout: float = 5.0) -> tuple[bool, str]:
        """Tests the connection and returns (success, message_or_version).

        Uses a single unpooled connection so failed attempts leave no pool
        retrying in the background.
        """
        kwargs = self._connect_kwargs()
        kwargs["connect_timeout"] = max(1, int(timeout))
        try:
            with psycopg.connect(self.get_conninfo(), **kwargs) as conn:
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
            pools = list(cls._cache.values())
            cls._cache.clear()
        _close_quietly(pools)
