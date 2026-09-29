import os
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, List, Optional
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, Field, field_validator


def _has_profiles(db_path: Path) -> bool:
    if not db_path.is_file():
        return False
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM profiles")
            row = cur.fetchone()
            return bool(row and row[0] > 0)
    except sqlite3.Error:
        return False


def get_default_db_path() -> Path:
    """Resolve the SQLite profiles database path with multi-location fallback."""
    if "MCP_POSTGRES_DB_PATH" in os.environ:
        path = Path(os.environ["MCP_POSTGRES_DB_PATH"])
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    config_path = Path.home() / ".config" / "mcp-postgresql" / "profiles.db"
    local_path = Path.cwd() / ".data" / "profiles.db"

    if _has_profiles(config_path):
        return config_path

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
    password: str = Field(default="")
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


class ProfileStorage:
    """Manages CRUD operations for PostgreSQL connection profiles in a local SQLite database."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        if db_path is None:
            self.db_path = get_default_db_path()
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
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
            try:
                conn.execute("ALTER TABLE profiles ADD COLUMN statement_timeout_ms INTEGER NOT NULL DEFAULT 30000")
            except sqlite3.OperationalError:
                pass
            conn.commit()

    def _row_to_profile(self, row: sqlite3.Row) -> Profile:
        keys = row.keys()
        timeout = row["statement_timeout_ms"] if "statement_timeout_ms" in keys else 30000
        return Profile(
            id=row["id"],
            name=row["name"],
            host=row["host"],
            port=row["port"],
            database=row["database"],
            username=row["username"],
            password=row["password"],
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

            # No explicitly active profile — fall back to first stored
            fallback_row = conn.execute(
                "SELECT * FROM profiles ORDER BY id ASC LIMIT 1"
            ).fetchone()
            if fallback_row:
                return self._row_to_profile(fallback_row)

        return self._profile_from_env()

    def save_profile(self, profile: ProfileCreate) -> Profile:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            # If this is the first profile being saved, make it active automatically
            count = conn.execute("SELECT COUNT(*) as count FROM profiles").fetchone()["count"]
            is_active = 1 if count == 0 else 0

            cursor = conn.execute(
                """
                INSERT INTO profiles (name, host, port, database, username, password, sslmode, statement_timeout_ms, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.name,
                    profile.host,
                    profile.port,
                    profile.database,
                    profile.username,
                    profile.password,
                    profile.sslmode,
                    profile.statement_timeout_ms,
                    is_active,
                    now,
                    now,
                ),
            )
            profile_id = cursor.lastrowid
            conn.commit()

        return self.get_profile(profile_id)  # type: ignore

    def update_profile(self, profile_id: int, profile: ProfileCreate) -> Optional[Profile]:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE profiles
                SET name = ?, host = ?, port = ?, database = ?, username = ?, password = ?, sslmode = ?, statement_timeout_ms = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    profile.name,
                    profile.host,
                    profile.port,
                    profile.database,
                    profile.username,
                    profile.password,
                    profile.sslmode,
                    profile.statement_timeout_ms,
                    now,
                    profile_id,
                ),
            )
            conn.commit()
        return self.get_profile(profile_id)

    def set_active_profile(self, profile_id: int) -> Optional[Profile]:
        with self._get_connection() as conn:
            # First check if profile exists
            row = conn.execute("SELECT id FROM profiles WHERE id = ?", (profile_id,)).fetchone()
            if not row:
                return None

            conn.execute("UPDATE profiles SET is_active = 0")
            conn.execute("UPDATE profiles SET is_active = 1 WHERE id = ?", (profile_id,))
            conn.commit()

        return self.get_profile(profile_id)

    def delete_profile(self, profile_id: int) -> bool:
        with self._get_connection() as conn:
            # Check if active profile is being deleted
            profile = self.get_profile(profile_id)
            if not profile:
                return False

            cursor = conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
            conn.commit()

            # If the deleted profile was active, make another profile active if available
            if profile.is_active:
                remaining = conn.execute("SELECT id FROM profiles LIMIT 1").fetchone()
                if remaining:
                    conn.execute("UPDATE profiles SET is_active = 1 WHERE id = ?", (remaining["id"],))
                    conn.commit()

            return cursor.rowcount > 0
