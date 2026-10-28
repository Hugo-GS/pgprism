import sqlite3
from pathlib import Path

import pytest

from src.storage import ProfileCreate, ProfileStorage, get_default_db_path


@pytest.fixture
def sqlite_connections(monkeypatch: pytest.MonkeyPatch):
    connections = []
    connect = sqlite3.connect

    def track_connection(*args, **kwargs):
        conn = connect(*args, **kwargs)
        connections.append(conn)
        return conn

    monkeypatch.setattr("src.storage.sqlite3.connect", track_connection)
    yield connections
    for conn in connections:
        conn.close()


def assert_connections_closed(connections):
    assert connections
    for conn in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            conn.execute("SELECT 1")


def test_connections_close_after_save_and_reopen(tmp_path: Path, sqlite_connections):
    path = tmp_path / "profiles.db"
    storage = ProfileStorage(path)
    saved = storage.save_profile(ProfileCreate(name="persisted", username="reader"))

    reopened = ProfileStorage(path)
    assert reopened.get_profile(saved.id) == saved
    assert_connections_closed(sqlite_connections)


def test_connections_close_and_roll_back_failed_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sqlite_connections
):
    storage = ProfileStorage(tmp_path / "profiles.db")
    first = storage.save_profile(ProfileCreate(name="first", username="reader"))
    second = storage.save_profile(ProfileCreate(name="second", username="reader"))
    connect = sqlite3.connect

    class FailedCommitConnection(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("simulated commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(
            "src.storage.sqlite3.connect",
            lambda *args, **kwargs: connect(*args, factory=FailedCommitConnection, **kwargs),
        )
        with pytest.raises(sqlite3.OperationalError, match="simulated commit failure"):
            storage.set_active_profile(second.id)

    assert storage.list_profiles() == [first, second]
    assert_connections_closed(sqlite_connections)


def test_default_path_probes_close_connections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sqlite_connections
):
    monkeypatch.delenv("PGPRISM_DB_PATH", raising=False)
    monkeypatch.delenv("MCP_POSTGRES_DB_PATH", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.chdir(tmp_path)
    config = tmp_path / ".config" / "pgprism" / "profiles.db"
    config.parent.mkdir(parents=True)
    config.write_bytes(b"not a SQLite database")
    legacy = tmp_path / ".config" / "mcp-postgresql" / "profiles.db"
    ProfileStorage(legacy).save_profile(ProfileCreate(name="legacy", username="reader"))

    assert get_default_db_path() == legacy
    assert_connections_closed(sqlite_connections)


@pytest.fixture
def temp_storage(tmp_path: Path) -> ProfileStorage:
    db_file = tmp_path / "test_profiles.db"
    return ProfileStorage(db_path=db_file)


def test_initial_state_empty(temp_storage: ProfileStorage):
    assert temp_storage.list_profiles() == []
    assert temp_storage.get_active_profile() is None


def test_create_and_get_profile(temp_storage: ProfileStorage):
    new_profile = ProfileCreate(
        name="local-db",
        host="localhost",
        port=5432,
        database="test_db",
        username="postgres",
        password="secretpassword",
        sslmode="disable",
    )
    saved = temp_storage.save_profile(new_profile)
    assert saved.id is not None
    assert saved.name == "local-db"
    assert saved.database == "test_db"
    assert saved.is_active is True  # First profile becomes active automatically

    retrieved = temp_storage.get_profile(saved.id)
    assert retrieved is not None
    assert retrieved.name == "local-db"
    assert retrieved.password == "secretpassword"


def test_set_active_profile(temp_storage: ProfileStorage):
    p1 = temp_storage.save_profile(ProfileCreate(name="db-one", database="db1", username="user1"))
    p2 = temp_storage.save_profile(ProfileCreate(name="db-two", database="db2", username="user2"))

    # p1 was initially active
    initial = temp_storage.get_active_profile()
    assert initial is not None
    assert initial.id == p1.id

    # Switch active to p2
    temp_storage.set_active_profile(p2.id)
    active = temp_storage.get_active_profile()
    assert active is not None
    assert active.id == p2.id
    assert active.name == "db-two"

    # Verify p1 is no longer active
    p1_refreshed = temp_storage.get_profile(p1.id)
    assert p1_refreshed is not None
    assert p1_refreshed.is_active is False


def test_delete_profile(temp_storage: ProfileStorage):
    p1 = temp_storage.save_profile(ProfileCreate(name="to-delete", database="db", username="u"))
    assert temp_storage.delete_profile(p1.id) is True
    assert temp_storage.get_profile(p1.id) is None
    assert temp_storage.delete_profile(9999) is False


def test_update_existing_profile(temp_storage: ProfileStorage):
    p = temp_storage.save_profile(
        ProfileCreate(name="prod-replica", database="prod", username="reader")
    )
    update_data = ProfileCreate(
        name="prod-replica",
        host="replica.internal",
        port=5433,
        database="prod",
        username="reader_v2",
        password="newpassword",
    )
    updated = temp_storage.update_profile(p.id, update_data)
    assert updated is not None
    assert updated.host == "replica.internal"
    assert updated.port == 5433
    assert updated.username == "reader_v2"
    assert updated.password == "newpassword"


def test_database_field_optional_defaults_to_postgres(temp_storage: ProfileStorage):
    # Omitted database
    p1 = temp_storage.save_profile(ProfileCreate(name="no-db", username="postgres"))
    assert p1.database == "postgres"

    # Empty string database
    p2 = temp_storage.save_profile(ProfileCreate(name="empty-db", database="", username="postgres"))
    assert p2.database == "postgres"


def test_statement_timeout_ms_default(temp_storage: ProfileStorage):
    p1 = temp_storage.save_profile(ProfileCreate(name="timeout-default", username="postgres"))
    assert p1.statement_timeout_ms == 30000


def test_statement_timeout_ms_persistence(temp_storage: ProfileStorage):
    p2 = temp_storage.save_profile(
        ProfileCreate(name="timeout-custom", username="postgres", statement_timeout_ms=50000)
    )
    assert p2.statement_timeout_ms == 50000
    retrieved = temp_storage.get_profile(p2.id)
    assert retrieved is not None
    assert retrieved.statement_timeout_ms == 50000

    updated = temp_storage.update_profile(
        p2.id, ProfileCreate(name="timeout-custom", username="postgres", statement_timeout_ms=60000)
    )
    assert updated is not None
    assert updated.statement_timeout_ms == 60000


def test_get_active_profile_fallback_to_first_when_none_active(temp_storage: ProfileStorage):
    p1 = temp_storage.save_profile(ProfileCreate(name="first-db", username="postgres"))
    temp_storage.save_profile(ProfileCreate(name="second-db", username="postgres"))

    # Deactivate all profiles manually
    with temp_storage._get_connection() as conn:
        conn.execute("UPDATE profiles SET is_active = 0")
        conn.commit()

    # Should fallback to the first stored profile
    active = temp_storage.get_active_profile()
    assert active is not None
    assert active.id == p1.id
    assert active.name == "first-db"


def test_get_active_profile_fallback_to_database_url(
    temp_storage: ProfileStorage, monkeypatch: pytest.MonkeyPatch
):
    assert temp_storage.get_active_profile() is None
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://pguser:secretpass@remotedb:5433/prod_data?sslmode=require",
    )
    profile = temp_storage.get_active_profile()
    assert profile is not None
    assert profile.name == "env-default"
    assert profile.host == "remotedb"
    assert profile.port == 5433
    assert profile.database == "prod_data"
    assert profile.username == "pguser"
    assert profile.password == "secretpass"
    assert profile.sslmode == "require"


def test_get_active_profile_fallback_to_pghost_vars(
    temp_storage: ProfileStorage, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PGHOST", "postgres.internal")
    monkeypatch.setenv("PGPORT", "5434")
    monkeypatch.setenv("PGDATABASE", "app_db")
    monkeypatch.setenv("PGUSER", "app_admin")
    monkeypatch.setenv("PGPASSWORD", "envpassword")

    profile = temp_storage.get_active_profile()
    assert profile is not None
    assert profile.name == "env-default"
    assert profile.host == "postgres.internal"
    assert profile.port == 5434
    assert profile.database == "app_db"
    assert profile.username == "app_admin"
    assert profile.password == "envpassword"


def test_search_profiles(temp_storage: ProfileStorage):
    temp_storage.save_profile(
        ProfileCreate(
            name="analytics-prod", host="prod.db.internal", database="warehouse", username="pguser"
        )
    )
    temp_storage.save_profile(
        ProfileCreate(
            name="analytics-staging",
            host="stage.db.internal",
            database="warehouse_stg",
            username="pguser",
        )
    )
    temp_storage.save_profile(
        ProfileCreate(
            name="billing-db", host="payments.internal", database="invoices", username="pguser"
        )
    )

    # Partial name match
    results = temp_storage.search_profiles("analytics")
    assert len(results) == 2
    assert {r.name for r in results} == {"analytics-prod", "analytics-staging"}

    # Partial host match
    results = temp_storage.search_profiles("payments")
    assert len(results) == 1
    assert results[0].name == "billing-db"

    # Partial database match
    results = temp_storage.search_profiles("warehouse")
    assert len(results) == 2

    # Empty or whitespace query
    assert temp_storage.search_profiles("") == []
    assert temp_storage.search_profiles("   ") == []

    # No match
    assert temp_storage.search_profiles("nonexistent_cluster") == []
