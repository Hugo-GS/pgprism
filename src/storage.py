"""Local SQLite storage for PostgreSQL connection profiles."""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, List, Optional
from pydantic import BaseModel, Field


import os

def get_default_db_path() -> Path:
    """Returns the database path, respecting MCP_POSTGRES_DB_PATH or falling back to ~/.config or local .data."""
    if "MCP_POSTGRES_DB_PATH" in os.environ:
        path = Path(os.environ["MCP_POSTGRES_DB_PATH"])
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    config_dir = Path.home() / ".config" / "mcp-postgresql"
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "profiles.db"
    except OSError:
        local_dir = Path.cwd() / ".data"
        local_dir.mkdir(parents=True, exist_ok=True)
        return local_dir / "profiles.db"


from pydantic import BaseModel, Field, field_validator


class ProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    host: str = Field(default="localhost")
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(default="postgres")
    username: str = Field(..., min_length=1)
    password: str = Field(default="")
    sslmode: str = Field(default="prefer")

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
            conn.commit()

    def _row_to_profile(self, row: sqlite3.Row) -> Profile:
        return Profile(
            id=row["id"],
            name=row["name"],
            host=row["host"],
            port=row["port"],
            database=row["database"],
            username=row["username"],
            password=row["password"],
            sslmode=row["sslmode"],
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

    def get_active_profile(self) -> Optional[Profile]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM profiles WHERE is_active = 1 LIMIT 1"
            ).fetchone()
            return self._row_to_profile(row) if row else None

    def save_profile(self, profile: ProfileCreate) -> Profile:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            # If this is the first profile being saved, make it active automatically
            count = conn.execute("SELECT COUNT(*) as count FROM profiles").fetchone()["count"]
            is_active = 1 if count == 0 else 0

            cursor = conn.execute(
                """
                INSERT INTO profiles (name, host, port, database, username, password, sslmode, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.name,
                    profile.host,
                    profile.port,
                    profile.database,
                    profile.username,
                    profile.password,
                    profile.sslmode,
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
                SET name = ?, host = ?, port = ?, database = ?, username = ?, password = ?, sslmode = ?, updated_at = ?
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
