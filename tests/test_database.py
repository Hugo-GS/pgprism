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

    with patch.object(db, "_get_connection", return_value=mock_conn):
        result = db.execute_query("SELECT id, username FROM users", max_rows=10)

        # Ensure transaction was opened with read_only=True
        mock_conn.transaction.assert_called_once_with(read_only=True)
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

    with patch.object(db, "_get_connection", return_value=mock_conn):
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

    with patch.object(db, "_get_connection", return_value=mock_conn):
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

    with patch.object(db, "_get_connection", return_value=mock_conn):
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

    with patch.object(db, "_get_connection", return_value=mock_conn):
        plan = db.explain_query("SELECT * FROM users")
        assert "Seq Scan on users" in plan


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

    with patch.object(db, "_get_connection", return_value=mock_conn):
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


