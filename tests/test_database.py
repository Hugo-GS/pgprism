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
    with patch.object(db, "_get_pool", return_value=mock_pool):
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
    with patch.object(db, "_get_pool", return_value=mock_pool):
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
    with patch.object(db, "_get_pool", return_value=mock_pool):
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
    with patch.object(db, "_get_pool", return_value=mock_pool):
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
    with patch.object(db, "_get_pool", return_value=mock_pool):
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
    with patch.object(db, "_get_pool", return_value=mock_pool):
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
    with patch.object(db, "_get_pool", return_value=mock_pool):
        plan = db.explain_query("SELECT * FROM users WHERE id = 1", analyze=False, as_json=True)
        mock_cursor.execute.assert_called_with("EXPLAIN (FORMAT JSON) SELECT * FROM users WHERE id = 1")
        assert plan == parsed_obj



def test_list_databases(sample_profile: Profile):
    db = DatabaseManager(sample_profile)

    mock_cursor = MagicMock()
    mock_cursor.description = [MagicMock(name="datname")]
    mock_cursor.description[0].name = "datname"
    mock_cursor.fetchmany.return_value = [("postgres",), ("analytics",), ("ecommerce",)]

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.transaction.return_value.__enter__.return_value = MagicMock()

    mock_pool = MagicMock()
    mock_pool.connection.return_value = mock_conn
    with patch.object(db, "_get_pool", return_value=mock_pool):
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


from src.database import _pool_key, _pool_cache

def test_pool_key(sample_profile: Profile):
    key1 = _pool_key(sample_profile, "db1")
    key2 = _pool_key(sample_profile, "db2")
    assert key1 == "localhost:5432/db1/test_user/prefer"
    assert key2 == "localhost:5432/db2/test_user/prefer"
    assert key1 != key2


def test_get_pool_instantiates_connection_pool(sample_profile: Profile):
    db = DatabaseManager(sample_profile)
    try:
        with patch("src.database.ConnectionPool") as mock_cp:
            mock_cp.return_value = MagicMock()
            pool = db._get_pool("custom_test_db")
            assert pool == mock_cp.return_value
            mock_cp.assert_called_once()
            args, kwargs = mock_cp.call_args
            assert "dbname=custom_test_db" in args[0]
            assert kwargs["min_size"] == 1
            assert kwargs["max_size"] == 3
    finally:
        _pool_cache.clear()


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
