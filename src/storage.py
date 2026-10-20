import logging
import os
from contextlib import closing, contextmanager
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, Iterator, List, Optional
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, Field, field_validator

from src.credentials import CredentialStore, CredentialStoreError, OSCredentialStore

logger = logging.getLogger(__name__)


def _has_profiles(db_path: Path) -> bool:
    if not db_path.is_file():
        return False
    try:
        with closing(sqlite3.connect(db_path)) as conn, conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM profiles")
            row = cur.fetchone()
            return bool(row and row[0] > 0)
    except sqlite3.Error:
        return False


def get_default_db_path() -> Path:
    """Resolve the SQLite profiles database path with multi-location fallback."""
    if "PGPRISM_DB_PATH" in os.environ:
        path = Path(os.environ["PGPRISM_DB_PATH"])
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    if "MCP_POSTGRES_DB_PATH" in os.environ:
        path = Path(os.environ["MCP_POSTGRES_DB_PATH"])
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    config_path = Path.home() / ".config" / "pgprism" / "profiles.db"
    legacy_config_path = Path.home() / ".config" / "mcp-postgresql" / "profiles.db"
    local_path = Path.cwd() / ".data" / "profiles.db"

    if _has_profiles(config_path):
        return config_path

    if _has_profiles(legacy_config_path):
        return legacy_config_path

    if _has_profiles(local_path):
        return local_path

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        return config_path
    except OSError:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        return local_path


def _safe_port(raw: str) -> int:
    try:
        port = int(raw)
    except (ValueError, TypeError):
        return 5432
    return port if 1 <= port <= 65535 else 5432


class ProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    host: str = Field(default="localhost")
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(default="postgres")
    username: str = Field(..., min_length=1)
    password: str = Field(default="", repr=False)
    sslmode: str = Field(default="prefer")
    statement_timeout_ms: int = Field(default=30000, ge=1000, le=300000)

    @field_validator("database", mode="before")
    @classmethod
    def default_database_if_empty(cls, v: Any) -> str:
        if not v or not str(v).strip():
            return "postgres"
        return str(v).strip()


class Profile(ProfileCreate):
    id: int
    is_active: bool = False
    created_at: str
    updated_at: str


class PublicProfile(Profile):
    """Profile metadata exposed by HTTP; never serialize the connection password."""

    password: str = Field(default="", exclude=True, repr=False)


class ProfileStorage:
    """SQLite profile metadata with passwords held in the OS credential store."""

    def __init__(
        self,
        db_path: Optional[Path | str] = None,
        *,
        credential_store: CredentialStore | None = None,
    ) -> None:
        self.credential_store = credential_store if credential_store is not None else OSCredentialStore()
        if db_path is None:
            self.db_path = get_default_db_path()
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        """Commit or roll back before closing, including when setup fails."""
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA secure_delete = ON")
            yield conn

    def _discard_secret(self, reference: str | None) -> None:
        if reference:
            try:
                self.credential_store.delete(reference)
            except CredentialStoreError:
                # An orphan in the OS vault is safer than losing the committed profile.
                logger.warning("Could not remove an unused OS credential (%s).", reference)

    def _init_db(self) -> None:
        created_references: list[str] = []
        try:
            self._initialize_and_migrate(created_references)
        except Exception:
            for reference in created_references:
                self._discard_secret(reference)
            raise

    def _initialize_and_migrate(self, created_references: list[str]) -> None:
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    host TEXT NOT NULL DEFAULT 'localhost',
                    port INTEGER NOT NULL DEFAULT 5432,
                    database TEXT NOT NULL,
                    username TEXT NOT NULL,
                    password TEXT NOT NULL DEFAULT '',
                    sslmode TEXT NOT NULL DEFAULT 'prefer',
                    is_active INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(profiles)")}
            if "statement_timeout_ms" not in columns:
                conn.execute("ALTER TABLE profiles ADD COLUMN statement_timeout_ms INTEGER NOT NULL DEFAULT 30000")
            if "credential_id" not in columns:
                conn.execute("ALTER TABLE profiles ADD COLUMN credential_id TEXT")
            for row in conn.execute("SELECT id, password FROM profiles WHERE password != ''").fetchall():
                reference = uuid4().hex
                created_references.append(reference)
                self.credential_store.set(reference, row["password"])
                conn.execute(
                    "UPDATE profiles SET password = '', credential_id = ? WHERE id = ?",
                    (reference, row["id"]),
                )
            conn.commit()
        migrated = bool(created_references)
        created_references.clear()  # Committed references must never be rolled back.
        # secure_delete wipes overwritten cells. Compaction also removes freelist
        # pages. Old backups and filesystem snapshots remain outside our control.
        if migrated:
            with self._get_connection() as conn:
                conn.execute("VACUUM")
                checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if checkpoint[0]:
                    logger.warning("Legacy credential cleanup needs a WAL checkpoint after other readers close.")

    def _row_to_profile(self, row: sqlite3.Row) -> Profile:
        keys = row.keys()
        timeout = row["statement_timeout_ms"] if "statement_timeout_ms" in keys else 30000
        password = ""
        if row["credential_id"]:
            password = self.credential_store.get(row["credential_id"])
            if password is None:
                raise CredentialStoreError(
                    "Saved connection password is missing from the OS credential store. "
                    "Delete and recreate the profile with its password."
                )
        return Profile(
            id=row["id"],
            name=row["name"],
            host=row["host"],
            port=row["port"],
            database=row["database"],
            username=row["username"],
            password=password,
            sslmode=row["sslmode"],
            statement_timeout_ms=timeout,
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_profiles(self) -> List[Profile]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM profiles ORDER BY is_active DESC, name ASC"
            ).fetchall()
            return [self._row_to_profile(r) for r in rows]

    def get_profile(self, profile_id: int) -> Optional[Profile]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            return self._row_to_profile(row) if row else None

    def get_profile_by_name(self, name: str) -> Optional[Profile]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM profiles WHERE name = ?", (name,)
            ).fetchone()
            return self._row_to_profile(row) if row else None

    def search_profiles(self, query: str) -> List[Profile]:
        """Search profiles by partial match on name, host, or database."""
        cleaned = query.strip()
        if not cleaned:
            return []
        pattern = f"%{cleaned}%"
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM profiles
                WHERE name LIKE ? OR host LIKE ? OR database LIKE ?
                ORDER BY is_active DESC, name ASC
                """,
                (pattern, pattern, pattern),
            ).fetchall()
            return [self._row_to_profile(r) for r in rows]

    def _profile_from_env(self) -> Optional[Profile]:
        """Build a profile from DATABASE_URL or PG* environment variables."""
        database_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
        now = datetime.now(timezone.utc).isoformat()
        if database_url:
            parsed = urlparse(database_url)
            username = parsed.username or os.environ.get("PGUSER", "postgres")
            password = parsed.password or os.environ.get("PGPASSWORD", "")
            host = parsed.hostname or os.environ.get("PGHOST", "localhost")
            port = parsed.port or _safe_port(os.environ.get("PGPORT", "5432"))
            db_path = parsed.path.lstrip("/") if parsed.path else ""
            database = db_path if db_path else os.environ.get("PGDATABASE", "postgres")
            query_params = parse_qs(parsed.query)
            sslmode = query_params.get("sslmode", [os.environ.get("PGSSLMODE", "prefer")])[0]
            return Profile(
                id=0,
                name="env-default",
                host=host,
                port=port,
                database=database or "postgres",
                username=username,
                password=password,
                sslmode=sslmode,
                statement_timeout_ms=30000,
                is_active=True,
                created_at=now,
                updated_at=now,
            )

        if any(k in os.environ for k in ("PGHOST", "PGDATABASE", "PGUSER")):
            return Profile(
                id=0,
                name="env-default",
                host=os.environ.get("PGHOST", "localhost"),
                port=_safe_port(os.environ.get("PGPORT", "5432")),
                database=os.environ.get("PGDATABASE", "postgres"),
                username=os.environ.get("PGUSER", "postgres"),
                password=os.environ.get("PGPASSWORD", ""),
                sslmode=os.environ.get("PGSSLMODE", "prefer"),
                statement_timeout_ms=30000,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        return None

    def get_active_profile(self) -> Optional[Profile]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM profiles WHERE is_active = 1 LIMIT 1"
            ).fetchone()
            if row:
                return self._row_to_profile(row)

            fallback_row = conn.execute(
                "SELECT * FROM profiles ORDER BY id ASC LIMIT 1"
            ).fetchone()
            if fallback_row:
                return self._row_to_profile(fallback_row)

        return self._profile_from_env()

    def _store_password(self, password: str) -> str | None:
        if not password:
            return None
        reference = uuid4().hex
        try:
            self.credential_store.set(reference, password)
        except Exception:
            self._discard_secret(reference)
            raise
        return reference

    def save_profile(self, profile: ProfileCreate) -> Profile:
        now = datetime.now(timezone.utc).isoformat()
        reference = None
        try:
            with self._get_connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                count = conn.execute("SELECT COUNT(*) as count FROM profiles").fetchone()["count"]
                is_active = count == 0
                reference = self._store_password(profile.password)
                cursor = conn.execute(
                    """
                    INSERT INTO profiles (name, host, port, database, username, credential_id, sslmode, statement_timeout_ms, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (profile.name, profile.host, profile.port, profile.database,
                     profile.username, reference, profile.sslmode,
                     profile.statement_timeout_ms, is_active, now, now),
                )
                profile_id = cursor.lastrowid
                conn.commit()
        except Exception:
            self._discard_secret(reference)
            raise
        return Profile(**profile.model_dump(), id=profile_id, is_active=is_active, created_at=now, updated_at=now)

    def update_profile(self, profile_id: int, profile: ProfileCreate) -> Optional[Profile]:
        now = datetime.now(timezone.utc).isoformat()
        reference = None
        try:
            with self._get_connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
                if existing is None:
                    return None
                reference = self._store_password(profile.password)
                conn.execute(
                    """
                    UPDATE profiles
                    SET name = ?, host = ?, port = ?, database = ?, username = ?, credential_id = ?, sslmode = ?, statement_timeout_ms = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (profile.name, profile.host, profile.port, profile.database,
                     profile.username, reference, profile.sslmode,
                     profile.statement_timeout_ms, now, profile_id),
                )
                conn.commit()
        except Exception:
            self._discard_secret(reference)
            raise
        self._discard_secret(existing["credential_id"])
        return Profile(**profile.model_dump(), id=profile_id, is_active=bool(existing["is_active"]), created_at=existing["created_at"], updated_at=now)

    def set_active_profile(self, profile_id: int) -> Optional[Profile]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT id FROM profiles WHERE id = ?", (profile_id,)).fetchone()
            if not row:
                return None

            conn.execute("UPDATE profiles SET is_active = 0")
            conn.execute("UPDATE profiles SET is_active = 1 WHERE id = ?", (profile_id,))
            conn.commit()

        return self.get_profile(profile_id)

    def delete_profile(self, profile_id: int) -> bool:
        removed_reference = None
        removed_password = None
        try:
            with self._get_connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
                if row is None:
                    return False
                reference = row["credential_id"]
                if reference:
                    removed_password = self.credential_store.get(reference)
                    removed_reference = reference
                    self.credential_store.delete(reference)
                conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
                if row["is_active"]:
                    remaining = conn.execute("SELECT id FROM profiles ORDER BY id LIMIT 1").fetchone()
                    if remaining:
                        conn.execute("UPDATE profiles SET is_active = 1 WHERE id = ?", (remaining["id"],))
                conn.commit()
        except Exception:
            if removed_reference and removed_password is not None:
                self.credential_store.set(removed_reference, removed_password)
            raise
        return True
