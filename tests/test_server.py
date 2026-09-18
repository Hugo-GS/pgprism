from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from src.server import create_server
from src.storage import ProfileCreate, ProfileStorage


@pytest.fixture
def storage_with_profile(tmp_path: Path) -> ProfileStorage:
    storage = ProfileStorage(db_path=tmp_path / "profiles.db")
    storage.save_profile(
        ProfileCreate(
            name="default-dev",
            host="localhost",
            port=5432,
            database="dev_db",
            username="dev_user",
            password="dev_password",
        )
    )
    return storage


@pytest.fixture
def empty_storage(tmp_path: Path) -> ProfileStorage:
    return ProfileStorage(db_path=tmp_path / "empty.db")


@pytest.mark.anyio
async def test_tool_fails_gracefully_when_no_active_profile(empty_storage: ProfileStorage):
    server = create_server(storage=empty_storage)
    result = await server.call_tool("get_active_profile", {})
    text = result.content[0].text
    assert "No active database profile configured" in text


@pytest.mark.anyio
async def test_get_active_profile_masks_password(storage_with_profile: ProfileStorage):
    server = create_server(storage=storage_with_profile)
    result = await server.call_tool("get_active_profile", {})
    text = result.content[0].text
    assert "default-dev" in text
    assert "dev_user" in text
    assert "dev_password" not in text


@pytest.mark.anyio
async def test_read_query_rejects_mutation(storage_with_profile: ProfileStorage):
    server = create_server(storage=storage_with_profile)
    result = await server.call_tool(
        "read_query", {"query": "DELETE FROM users WHERE id = 1"}
    )
    assert result.is_error is True or "error" in result.content[0].text.lower()


@pytest.mark.anyio
async def test_read_query_executes_successfully(storage_with_profile: ProfileStorage):
    server = create_server(storage=storage_with_profile)

    mock_db_result = {
        "columns": ["id", "val"],
        "rows": [{"id": 1, "val": "hello"}],
        "row_count": 1,
        "truncated": False,
    }

    with patch("src.server.DatabaseManager") as MockDB:
        instance = MockDB.return_value
        instance.execute_query.return_value = mock_db_result

        result = await server.call_tool("read_query", {"query": "SELECT id, val FROM items"})
        assert result.is_error is False
        assert "hello" in result.content[0].text


@pytest.mark.anyio
async def test_list_tables(storage_with_profile: ProfileStorage):
    server = create_server(storage=storage_with_profile)

    with patch("src.server.DatabaseManager") as MockDB:
        instance = MockDB.return_value
        instance.list_tables.return_value = [{"table_name": "users", "table_type": "BASE TABLE"}]

        result = await server.call_tool("list_tables", {"schema": "public"})
        assert result.is_error is False
        assert "users" in result.content[0].text


@pytest.mark.anyio
async def test_list_databases(storage_with_profile: ProfileStorage):
    server = create_server(storage=storage_with_profile)

    with patch("src.server.DatabaseManager") as MockDB:
        instance = MockDB.return_value
        instance.list_databases.return_value = ["postgres", "analytics"]

        result = await server.call_tool("list_databases", {})
        assert result.is_error is False
        full_text = " ".join(item.text for item in result.content)
        assert "analytics" in full_text
        assert "postgres" in full_text


@pytest.mark.anyio
async def test_select_database(storage_with_profile: ProfileStorage):
    server = create_server(storage=storage_with_profile)

    with patch("src.server.DatabaseManager"):
        result = await server.call_tool("select_database", {"database_name": "analytics_db"})
        assert result.is_error is False
        assert "analytics_db" in result.content[0].text

        profile_res = await server.call_tool("get_active_profile", {})
        assert "analytics_db" in profile_res.content[0].text

