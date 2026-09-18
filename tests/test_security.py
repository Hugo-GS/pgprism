import pytest
from src.security import validate_readonly_query, SecurityError


def test_valid_select():
    sql = "SELECT id, name FROM users WHERE active = true ORDER BY id LIMIT 10"
    validated = validate_readonly_query(sql)
    assert "users" in validated.lower()


def test_valid_cte_select():
    sql = "WITH active_users AS (SELECT id, name FROM users WHERE active = true) SELECT * FROM active_users"
    validated = validate_readonly_query(sql)
    assert "active_users" in validated


def test_valid_explain():
    sql = "EXPLAIN SELECT * FROM users"
    validated = validate_readonly_query(sql)
    assert "EXPLAIN" in validated.upper()


def test_valid_show():
    sql = "SHOW server_version"
    validated = validate_readonly_query(sql)
    assert "SHOW" in validated.upper()


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO users (name) VALUES ('evil')",
        "UPDATE users SET name = 'evil'",
        "DELETE FROM users WHERE id = 1",
        "DROP TABLE users CASCADE",
        "ALTER TABLE users ADD COLUMN hacked boolean",
        "TRUNCATE users",
        "CREATE TABLE backdoor (id int)",
        "GRANT ALL PRIVILEGES ON DATABASE test TO evil",
    ],
)
def test_rejects_modifications(sql: str):
    with pytest.raises(SecurityError):
        validate_readonly_query(sql)


def test_rejects_data_modifying_cte():
    sql = "WITH deleted AS (DELETE FROM users RETURNING *) SELECT * FROM deleted"
    with pytest.raises(SecurityError):
        validate_readonly_query(sql)


def test_rejects_data_modifying_cte_update():
    sql = "WITH updated AS (UPDATE users SET role = 'admin' RETURNING *) SELECT * FROM updated"
    with pytest.raises(SecurityError):
        validate_readonly_query(sql)


def test_rejects_explain_with_write_query():
    sql = "EXPLAIN ANALYZE DELETE FROM users"
    with pytest.raises(SecurityError):
        validate_readonly_query(sql)


def test_rejects_multiple_statements():
    sql = "SELECT 1; DROP TABLE users;"
    with pytest.raises(SecurityError, match="Multiple statements"):
        validate_readonly_query(sql)


def test_rejects_empty_or_whitespace():
    with pytest.raises(SecurityError, match="Empty query"):
        validate_readonly_query("   ")


def test_rejects_dangerous_functions():
    sql = "SELECT pg_terminate_backend(1234)"
    with pytest.raises(SecurityError, match="Forbidden function"):
        validate_readonly_query(sql)


def test_rejects_merge():
    sql = "MERGE INTO users USING source ON users.id = source.id WHEN MATCHED THEN UPDATE SET name = source.name"
    with pytest.raises(SecurityError):
        validate_readonly_query(sql)


def test_rejects_transaction_controls():
    with pytest.raises(SecurityError):
        validate_readonly_query("COMMIT")
    with pytest.raises(SecurityError):
        validate_readonly_query("ROLLBACK")


def test_valid_explain_analyze_select():
    sql = "EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM users"
    validated = validate_readonly_query(sql)
    assert "EXPLAIN" in validated.upper()

