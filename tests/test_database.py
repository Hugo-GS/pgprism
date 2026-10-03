from unittest.mock import MagicMock, patch
import pytest
from src.database import DatabaseManager
from src.security import SecurityError
from src.storage import Profile


@pytest.fixture
def sample_profile() -> Profile:
    return Profile(
        id=1,
        name="test-profile",
        host="localhost",
        port=5432,
        database="test_db",
        username="test_user",
        password="test_password",
        sslmode="prefer",
        is_active=True,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )


def test_conninfo_generation(sample_profile: Profile):
    db = DatabaseManager(sample_profile)
    conninfo = db.get_conninfo()
    assert "host=localhost" in conninfo
    assert "port=5432" in conninfo
    assert "dbname=test_db" in conninfo
    assert "user=test_user" in conninfo
    assert "password=test_password" in conninfo
    assert "sslmode=prefer" in conninfo


def test_rejects_mutating_query_before_execution(sample_profile: Profile):
    db = DatabaseManager(sample_profile)
    with pytest.raises(SecurityError):
        db.execute_query("DELETE FROM users WHERE id = 1")


def test_execute_query_formats_results(sample_profile: Profile):
    db = DatabaseManager(sample_profile)

    col1 = MagicMock()
    col1.name = "id"
    col2 = MagicMock()
    col2.name = "username"

    mock_cursor = MagicMock()
    mock_cursor.description = [col1, col2]
    mock_cursor.fetchmany.return_value = [
        (1, "alice"),
        (2, "bob"),
    ]

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.transaction.return_value.__enter__.return_value = MagicMock()

    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn
    with patch.object(db._pool, "get_pool", return_value=mock_pool):
        result = db.execute_query("SELECT id, username FROM users", max_rows=10)

        # Ensure the transaction uses the current psycopg API and is explicitly read-only.
        mock_conn.transaction.assert_called_once_with()
        mock_cursor.execute.assert_any_call("SET TRANSACTION READ ONLY")
        assert result["columns"] == ["id", "username"]
        assert result["row_count"] == 2
        assert result["rows"] == [
            {"id": 1, "username": "alice"},
            {"id": 2, "username": "bob"},
        ]
        assert result["truncated"] is False


def test_execute_query_truncation(sample_profile: Profile):
    db = DatabaseManager(sample_profile)

    col = MagicMock()
    col.name = "id"

    mock_cursor = MagicMock()
    mock_cursor.description = [col]
    # return max_rows + 1 items to simulate truncation
    mock_cursor.fetchmany.return_value = [(1,), (2,), (3,)]

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.transaction.return_value.__enter__.return_value = MagicMock()

    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn
    with patch.object(db._pool, "get_pool", return_value=mock_pool):
        result = db.execute_query("SELECT id FROM users", max_rows=2)
        assert result["row_count"] == 2
        assert result["truncated"] is True
        assert len(result["rows"]) == 2


def test_list_tables(sample_profile: Profile):
    db = DatabaseManager(sample_profile)

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        ("users", "BASE TABLE"),
        ("active_users", "VIEW"),
    ]

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.transaction.return_value.__enter__.return_value = MagicMock()

    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn
    with patch.object(db._pool, "get_pool", return_value=mock_pool):
        tables = db.list_tables(schema="public")
        assert len(tables) == 2
        assert tables[0] == {"table_name": "users", "table_type": "BASE TABLE"}
        assert tables[1] == {"table_name": "active_users", "table_type": "VIEW"}


def test_describe_table(sample_profile: Profile):
    db = DatabaseManager(sample_profile)

    mock_cursor = MagicMock()
    # First call: columns. Second call: primary keys
    mock_cursor.fetchall.side_effect = [
        [("id", "integer", "NO", None), ("email", "text", "YES", None)],
        [("id",)],
    ]

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.transaction.return_value.__enter__.return_value = MagicMock()

    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn
    with patch.object(db._pool, "get_pool", return_value=mock_pool):
        desc = db.describe_table("users", schema="public")
        assert desc["table"] == "users"
        assert len(desc["columns"]) == 2
        assert desc["columns"][0]["name"] == "id"
        assert desc["columns"][0]["is_primary_key"] is True
        assert desc["columns"][1]["name"] == "email"
        assert desc["columns"][1]["is_primary_key"] is False


def test_explain_query(sample_profile: Profile):
    db = DatabaseManager(sample_profile)

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        ("Seq Scan on users  (cost=0.00..1.02 rows=2 width=36)",)
    ]

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.transaction.return_value.__enter__.return_value = MagicMock()

    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn
    with patch.object(db._pool, "get_pool", return_value=mock_pool):
        plan = db.explain_query("SELECT * FROM users")
        assert "Seq Scan on users" in plan


def test_explain_query_json_raw_string(sample_profile: Profile):
    db = DatabaseManager(sample_profile)

    json_str = '[{"Plan": {"Node Type": "Seq Scan", "Relation Name": "users", "Startup Cost": 0.0, "Total Cost": 1.02, "Plan Rows": 2, "Plan Width": 36}}]'
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [(json_str,)]

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.transaction.return_value.__enter__.return_value = MagicMock()

    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn
    with patch.object(db._pool, "get_pool", return_value=mock_pool):
        plan = db.explain_query("SELECT * FROM users", analyze=True, as_json=True)
        mock_cursor.execute.assert_called_with("EXPLAIN (FORMAT JSON, ANALYZE, BUFFERS) SELECT * FROM users")
        assert isinstance(plan, list)
        assert len(plan) == 1
        assert plan[0]["Plan"]["Node Type"] == "Seq Scan"
        assert plan[0]["Plan"]["Relation Name"] == "users"


def test_explain_query_json_preparsed_object(sample_profile: Profile):
    db = DatabaseManager(sample_profile)

    parsed_obj = [{"Plan": {"Node Type": "Index Scan", "Relation Name": "users", "Total Cost": 0.5}}]
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [(parsed_obj,)]

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.transaction.return_value.__enter__.return_value = MagicMock()

    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn
    with patch.object(db._pool, "get_pool", return_value=mock_pool):
        plan = db.explain_query("SELECT * FROM users WHERE id = 1", analyze=False, as_json=True)
        mock_cursor.execute.assert_called_with("EXPLAIN (FORMAT JSON) SELECT * FROM users WHERE id = 1")
        assert plan == parsed_obj


def test_list_databases(sample_profile: Profile):
    db = DatabaseManager(sample_profile)

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [("postgres",), ("analytics",), ("ecommerce",)]

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.transaction.return_value.__enter__.return_value = MagicMock()

    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn
    with patch.object(db._pool, "get_pool", return_value=mock_pool):
        dbs = db.list_databases()
        assert dbs == ["postgres", "analytics", "ecommerce"]


def test_set_database(sample_profile: Profile):
    db = DatabaseManager(sample_profile)
    assert db.current_database == "test_db"

    db.set_database("analytics_prod")
    assert db.current_database == "analytics_prod"
    assert "dbname=analytics_prod" in db.get_conninfo()

    with pytest.raises(ValueError):
        db.set_database("")


from psycopg_pool import PoolClosed

from src.database.pool import MAX_POOLS, PoolManager


@pytest.fixture
def clean_pool_cache():
    PoolManager._cache.clear()
    yield
    PoolManager._cache.clear()


@pytest.fixture
def mock_connection_pool():
    # A fresh MagicMock per ConnectionPool(...) call so pools are distinguishable.
    with patch("src.database.pool.ConnectionPool", side_effect=lambda *a, **k: MagicMock()) as mock_cp:
        yield mock_cp


def test_pool_key(sample_profile: Profile):
    key1 = PoolManager._pool_key(sample_profile, "db1")
    key2 = PoolManager._pool_key(sample_profile, "db2")
    # Keys now include a password+timeout hash suffix
    assert key1.startswith("localhost:5432/db1/test_user/prefer/")
    assert key2.startswith("localhost:5432/db2/test_user/prefer/")
    assert key1 != key2


def test_get_pool_instantiates_connection_pool(sample_profile: Profile, clean_pool_cache):
    db = DatabaseManager(sample_profile)
    with patch("src.database.pool.ConnectionPool") as mock_cp:
        mock_cp.return_value = MagicMock()
        pool = db._pool.get_pool("custom_test_db")
        assert pool == mock_cp.return_value
        mock_cp.assert_called_once()
        args, kwargs = mock_cp.call_args
        assert "dbname=custom_test_db" in args[0]
        assert kwargs["min_size"] == 0
        assert kwargs["max_size"] == 3
        assert kwargs["max_idle"] == 60.0
        assert kwargs["kwargs"]["application_name"] == "mcp-postgresql"


def test_get_pool_reuses_cached_pool(sample_profile: Profile, clean_pool_cache, mock_connection_pool):
    manager = PoolManager(sample_profile)
    first = manager.get_pool("db1")
    second = manager.get_pool("db1")
    assert first is second
    assert mock_connection_pool.call_count == 1


def test_get_pool_lru_evicts_and_closes_oldest(sample_profile: Profile, clean_pool_cache, mock_connection_pool):
    manager = PoolManager(sample_profile)
    pools = [manager.get_pool(f"db{i}") for i in range(MAX_POOLS + 1)]
    assert len(PoolManager._cache) == MAX_POOLS
    pools[0].close.assert_called_once()
    for pool in pools[1:]:
        pool.close.assert_not_called()


def test_get_pool_lru_touch_protects_recent(sample_profile: Profile, clean_pool_cache, mock_connection_pool):
    manager = PoolManager(sample_profile)
    pools = [manager.get_pool(f"db{i}") for i in range(MAX_POOLS)]
    # Touch the oldest so db1 becomes the least recently used.
    assert manager.get_pool("db0") is pools[0]
    manager.get_pool("db_new")
    pools[0].close.assert_not_called()
    pools[1].close.assert_called_once()


def test_get_pool_credential_change_closes_stale_pool(sample_profile: Profile, clean_pool_cache, mock_connection_pool):
    old_pool = PoolManager(sample_profile).get_pool("db1")
    changed = sample_profile.model_copy(update={"password": "rotated"})
    new_pool = PoolManager(changed).get_pool("db1")
    assert new_pool is not old_pool
    old_pool.close.assert_called_once()
    assert len(PoolManager._cache) == 1


def test_close_all_closes_every_pool_and_clears_cache(sample_profile: Profile, clean_pool_cache, mock_connection_pool):
    manager = PoolManager(sample_profile)
    pools = [manager.get_pool("db1"), manager.get_pool("db2")]
    PoolManager.close_all()
    for pool in pools:
        pool.close.assert_called_once()
    assert len(PoolManager._cache) == 0


def test_connect_retries_once_on_pool_closed(sample_profile: Profile):
    manager = PoolManager(sample_profile)
    closed_pool = MagicMock()
    closed_pool.connection.return_value.__enter__.side_effect = PoolClosed("closed")
    fresh_conn = MagicMock()
    fresh_pool = MagicMock()
    fresh_pool.connection.return_value.__enter__.return_value = fresh_conn
    with patch.object(manager, "get_pool", side_effect=[closed_pool, fresh_pool]) as mock_get_pool:
        with manager.connect() as conn:
            assert conn is fresh_conn
    assert mock_get_pool.call_count == 2
    fresh_conn.transaction.assert_called_once()


def test_test_connection_uses_unpooled_connection(sample_profile: Profile, clean_pool_cache):
    manager = PoolManager(sample_profile)
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchone.return_value = ("PostgreSQL 16.0",)
    with patch("src.database.pool.psycopg.connect", return_value=mock_conn) as mock_connect, \
            patch("src.database.pool.ConnectionPool") as mock_cp:
        ok, version = manager.test_connection(timeout=3.0)
    assert ok is True
    assert version == "PostgreSQL 16.0"
    mock_cp.assert_not_called()
    _, kwargs = mock_connect.call_args
    assert kwargs["connect_timeout"] == 3
    assert kwargs["application_name"] == "mcp-postgresql"
    assert len(PoolManager._cache) == 0


def test_serialize_value_handles_nan_and_infinity():
    from decimal import Decimal
    from src.database import _serialize_value

    assert _serialize_value(Decimal("NaN")) is None
    assert _serialize_value(Decimal("Infinity")) is None
    assert _serialize_value(Decimal("-Infinity")) is None
    assert _serialize_value(float("nan")) is None
    assert _serialize_value(float("inf")) is None
    assert _serialize_value(Decimal("123.45")) == 123.45
    assert _serialize_value(Decimal("100")) == 100
