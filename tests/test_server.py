import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult, InputRequiredResult, TextContent

from src.server import create_server
from src.storage import ProfileCreate, ProfileStorage


async def _call_tool(server: MCPServer, name: str, arguments: dict[str, Any]) -> CallToolResult:
    result = await server.call_tool(name, arguments)
    assert isinstance(result, CallToolResult)
    return result


def _text(content: object) -> str:
    assert isinstance(content, TextContent)
    return content.text


async def _read_resource(server: MCPServer, uri: str) -> list[ReadResourceContents]:
    result = await server.read_resource(uri)
    assert not isinstance(result, InputRequiredResult)
    return list(result)


def _resource_text(item: ReadResourceContents) -> str:
    assert isinstance(item.content, str)
    return item.content


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
    result = await _call_tool(server, "get_active_profile", {})
    text = _text(result.content[0])
    assert "No active database profile configured" in text


@pytest.mark.anyio
async def test_get_active_profile_masks_password(storage_with_profile: ProfileStorage):
    server = create_server(storage=storage_with_profile)
    result = await _call_tool(server, "get_active_profile", {})
    text = _text(result.content[0])
    assert "default-dev" in text
    assert "dev_user" in text
    assert "dev_password" not in text


@pytest.mark.anyio
async def test_read_query_rejects_mutation(storage_with_profile: ProfileStorage):
    server = create_server(storage=storage_with_profile)
    result = await _call_tool(server, "read_query", {"query": "DELETE FROM users WHERE id = 1"})
    assert result.is_error is True or "error" in _text(result.content[0]).lower()


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

        result = await _call_tool(server, "read_query", {"query": "SELECT id, val FROM items"})
        assert result.is_error is False
        assert "hello" in _text(result.content[0])


@pytest.mark.anyio
async def test_list_tables(storage_with_profile: ProfileStorage):
    server = create_server(storage=storage_with_profile)

    with patch("src.server.DatabaseManager") as MockDB:
        instance = MockDB.return_value
        instance.list_tables.return_value = [{"table_name": "users", "table_type": "BASE TABLE"}]

        result = await _call_tool(server, "list_tables", {"schema": "public"})
        assert result.is_error is False
        assert "users" in _text(result.content[0])


@pytest.mark.anyio
async def test_list_databases(storage_with_profile: ProfileStorage):
    server = create_server(storage=storage_with_profile)

    with patch("src.server.DatabaseManager") as MockDB:
        instance = MockDB.return_value
        instance.list_databases.return_value = ["postgres", "analytics"]

        result = await _call_tool(server, "list_databases", {})
        assert result.is_error is False
        full_text = " ".join(_text(item) for item in result.content)
        assert "analytics" in full_text
        assert "postgres" in full_text


@pytest.mark.anyio
async def test_select_database(storage_with_profile: ProfileStorage):
    server = create_server(storage=storage_with_profile)

    with patch("src.server.DatabaseManager"):
        result = await _call_tool(server, "select_database", {"database_name": "analytics_db"})
        assert result.is_error is False
        assert "analytics_db" in _text(result.content[0])

        profile_res = await _call_tool(server, "get_active_profile", {})
        assert "analytics_db" in _text(profile_res.content[0])


@pytest.mark.anyio
async def test_all_tools_have_readonly_annotations(storage_with_profile: ProfileStorage):
    """Verify all registered tools declare read_only_hint=True."""
    server = create_server(storage=storage_with_profile)
    tools_result = await server.list_tools()
    for tool in tools_result:
        assert tool.annotations is not None, f"Tool '{tool.name}' missing annotations"
        assert tool.annotations.read_only_hint is True, f"Tool '{tool.name}' not marked read-only"


@pytest.mark.anyio
async def test_resources_registered(storage_with_profile: ProfileStorage):
    """Verify standard MCP resources are registered."""
    server = create_server(storage=storage_with_profile)
    resources = await server.list_resources()
    resource_uris = [str(r.uri) for r in resources]
    assert "postgres://profiles" in resource_uris
    assert "postgres://schemas" in resource_uris
    # ui:// resources are not present by default
    assert "ui://postgres/explain-viewer" not in resource_uris
    assert "ui://postgres/data-grid" not in resource_uris

    # ui:// resources are registered when enable_ui=True
    server_ui = create_server(storage=storage_with_profile, enable_ui=True)
    resources_ui = await server_ui.list_resources()
    resource_uris_ui = [str(r.uri) for r in resources_ui]
    assert "ui://postgres/explain-viewer" in resource_uris_ui
    assert "ui://postgres/data-grid" in resource_uris_ui


@pytest.mark.anyio
async def test_resource_templates_registered(storage_with_profile: ProfileStorage):
    """Verify MCP resource templates are registered."""
    server = create_server(storage=storage_with_profile)
    templates = await server.list_resource_templates()
    template_uris = [str(t.uri_template) for t in templates]
    assert any("tables" in u for u in template_uris)


@pytest.mark.anyio
async def test_prompts_registered(storage_with_profile: ProfileStorage):
    """Verify MCP prompts are registered."""
    server = create_server(storage=storage_with_profile)
    prompts = await server.list_prompts()
    prompt_names = [p.name for p in prompts]
    assert "debug_slow_query" in prompt_names
    assert "explore_table" in prompt_names
    assert "find_data_issues" in prompt_names


@pytest.mark.anyio
async def test_profiles_resource_returns_data(storage_with_profile: ProfileStorage):
    """Verify the profiles resource returns stored profiles."""
    server = create_server(storage=storage_with_profile)
    content = _resource_text((await _read_resource(server, "postgres://profiles"))[0])
    assert "default-dev" in content


@pytest.mark.anyio
async def test_list_indexes(storage_with_profile: ProfileStorage):
    server = create_server(storage=storage_with_profile)
    with patch("src.server.DatabaseManager") as MockDB:
        instance = MockDB.return_value
        instance.list_indexes.return_value = [
            {
                "index_name": "users_pkey",
                "definition": "CREATE UNIQUE INDEX users_pkey ON public.users USING btree (id)",
            }
        ]
        result = await _call_tool(server, "list_indexes", {"table": "users"})
        assert result.is_error is False
        assert "users_pkey" in _text(result.content[0])


@pytest.mark.anyio
async def test_list_foreign_keys(storage_with_profile: ProfileStorage):
    server = create_server(storage=storage_with_profile)
    with patch("src.server.DatabaseManager") as MockDB:
        instance = MockDB.return_value
        instance.list_foreign_keys.return_value = [
            {
                "constraint_name": "orders_user_fk",
                "column": "user_id",
                "foreign_schema": "public",
                "foreign_table": "users",
                "foreign_column": "id",
            }
        ]
        result = await _call_tool(server, "list_foreign_keys", {"table": "orders"})
        assert result.is_error is False
        assert "orders_user_fk" in _text(result.content[0])


@pytest.mark.anyio
async def test_table_stats(storage_with_profile: ProfileStorage):
    server = create_server(storage=storage_with_profile)
    with patch("src.server.DatabaseManager") as MockDB:
        instance = MockDB.return_value
        instance.table_stats.return_value = {
            "live_rows": 1000,
            "dead_rows": 50,
            "sequential_scans": 200,
            "index_scans": 5000,
        }
        result = await _call_tool(server, "table_stats", {"table": "users"})
        assert result.is_error is False
        assert "1000" in _text(result.content[0])


@pytest.mark.anyio
async def test_running_queries(storage_with_profile: ProfileStorage):
    server = create_server(storage=storage_with_profile)
    with patch("src.server.DatabaseManager") as MockDB:
        instance = MockDB.return_value
        instance.running_queries.return_value = [
            {"pid": 123, "state": "active", "query": "SELECT 1", "duration": "00:00:01"}
        ]
        result = await _call_tool(server, "running_queries", {})
        assert result.is_error is False
        assert "SELECT 1" in _text(result.content[0])


@pytest.mark.anyio
async def test_database_size(storage_with_profile: ProfileStorage):
    server = create_server(storage=storage_with_profile)
    with patch("src.server.DatabaseManager") as MockDB:
        instance = MockDB.return_value
        instance.database_size.return_value = {
            "database": "dev_db",
            "total_size": "150 MB",
            "total_size_bytes": 157286400,
            "tables": [],
        }
        result = await _call_tool(server, "database_size", {})
        assert result.is_error is False
        assert "150 MB" in _text(result.content[0])


@pytest.mark.anyio
async def test_connection_tool_success(storage_with_profile: ProfileStorage):
    server = create_server(storage=storage_with_profile)
    with patch("src.server.DatabaseManager") as MockDB:
        instance = MockDB.return_value
        instance.current_database = "dev_db"
        instance.test_connection.return_value = (True, "PostgreSQL 16.1")

        result = await _call_tool(server, "test_connection", {})
        assert result.is_error is False
        text = _text(result.content[0])
        assert "PostgreSQL 16.1" in text
        assert "connected" in text


@pytest.mark.anyio
async def test_connection_tool_failure(storage_with_profile: ProfileStorage):
    server = create_server(storage=storage_with_profile)
    with patch("src.server.DatabaseManager") as MockDB:
        instance = MockDB.return_value
        instance.current_database = "dev_db"
        instance.test_connection.return_value = (False, "Connection timeout")

        result = await _call_tool(server, "test_connection", {})
        text = _text(result.content[0])
        assert "Connection timeout" in text
        assert "error" in text


@pytest.mark.anyio
async def test_server_resolves_env_profile_when_empty_storage(
    empty_storage: ProfileStorage, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@envhost:5432/envdb")
    server = create_server(storage=empty_storage)

    result = await _call_tool(server, "get_active_profile", {})
    assert result.is_error is False
    text = _text(result.content[0])
    assert "env-default" in text
    assert "envhost" in text
    assert "envdb" in text


@pytest.mark.anyio
async def test_search_profiles_tool(storage_with_profile: ProfileStorage):
    server = create_server(storage=storage_with_profile)

    # Search matching existing "default-dev" profile
    result = await _call_tool(server, "search_profiles", {"query": "dev"})
    assert result.is_error is False
    text = _text(result.content[0])
    assert "default-dev" in text
    assert "dev_user" in text
    assert "dev_password" not in text

    # Search with no match
    result_empty = await _call_tool(server, "search_profiles", {"query": "missing"})
    assert result_empty.is_error is False
    assert result_empty.content == []


@pytest.mark.anyio
async def test_server_default_no_ui_extension_capability(storage_with_profile: ProfileStorage):
    """Verify io.modelcontextprotocol/ui extension capability is NOT registered by default."""
    server = create_server(storage=storage_with_profile)
    assert "io.modelcontextprotocol/ui" not in server._lowlevel_server.extensions


@pytest.mark.anyio
async def test_server_advertises_ui_extension_capability_when_enabled(
    storage_with_profile: ProfileStorage,
):
    """Verify io.modelcontextprotocol/ui extension capability is registered when enable_ui=True."""
    server = create_server(storage=storage_with_profile, enable_ui=True)
    assert "io.modelcontextprotocol/ui" in server._lowlevel_server.extensions


@pytest.mark.anyio
async def test_tools_default_no_mcp_ui_metadata(storage_with_profile: ProfileStorage):
    """Verify explain_query and read_query do NOT expose UI metadata by default."""
    server = create_server(storage=storage_with_profile)
    tools = await server.list_tools()
    tool_map = {t.name: t for t in tools}

    assert "explain_query" in tool_map
    assert tool_map["explain_query"].meta is None

    assert "read_query" in tool_map
    assert tool_map["read_query"].meta is None


@pytest.mark.anyio
async def test_tools_have_mcp_ui_metadata_when_enabled(storage_with_profile: ProfileStorage):
    """Verify explain/read query tools expose MCP Apps UI resource metadata when enable_ui=True."""
    server = create_server(storage=storage_with_profile, enable_ui=True)
    tools = await server.list_tools()
    tool_map = {t.name: t for t in tools}

    assert "explain_query" in tool_map
    assert tool_map["explain_query"].meta == {"ui": {"resourceUri": "ui://postgres/explain-viewer"}}

    assert "read_query" in tool_map
    assert tool_map["read_query"].meta == {"ui": {"resourceUri": "ui://postgres/data-grid"}}


@pytest.mark.anyio
async def test_server_respects_env_var_for_ui(
    storage_with_profile: ProfileStorage, monkeypatch: pytest.MonkeyPatch
):
    """Verify PGPRISM_ENABLE_UI env var toggles UI extension."""
    monkeypatch.setenv("PGPRISM_ENABLE_UI", "1")
    server_enabled = create_server(storage=storage_with_profile)
    assert "io.modelcontextprotocol/ui" in server_enabled._lowlevel_server.extensions

    monkeypatch.setenv("PGPRISM_ENABLE_UI", "0")
    server_disabled = create_server(storage=storage_with_profile)
    assert "io.modelcontextprotocol/ui" not in server_disabled._lowlevel_server.extensions


@pytest.mark.anyio
async def test_ui_resources_read_contents_and_mime_type(storage_with_profile: ProfileStorage):
    """Verify ui:// resources are readable when enabled and absent from the default server."""
    from mcp.server.apps import APP_MIME_TYPE

    # Default server has no ui:// resources
    server_default = create_server(storage=storage_with_profile)
    resources_default = await server_default.list_resources()
    assert not any(str(r.uri).startswith("ui://") for r in resources_default)

    # Server with enable_ui=True exposes ui:// resources
    server = create_server(storage=storage_with_profile, enable_ui=True)

    resources = await server.list_resources()
    res_map = {str(r.uri): r for r in resources}

    assert "ui://postgres/explain-viewer" in res_map
    assert res_map["ui://postgres/explain-viewer"].mime_type == APP_MIME_TYPE
    assert res_map["ui://postgres/explain-viewer"].mime_type == "text/html;profile=mcp-app"

    assert "ui://postgres/data-grid" in res_map
    assert res_map["ui://postgres/data-grid"].mime_type == APP_MIME_TYPE
    assert res_map["ui://postgres/data-grid"].mime_type == "text/html;profile=mcp-app"

    explain_res = await _read_resource(server, "ui://postgres/explain-viewer")
    assert len(explain_res) > 0
    assert explain_res[0].mime_type == "text/html;profile=mcp-app"
    content = _resource_text(explain_res[0])
    assert "<!DOCTYPE html>" in content
    assert "explain-viewer" in content or "Execution Plan" in content

    grid_res = await _read_resource(server, "ui://postgres/data-grid")
    assert len(grid_res) > 0
    assert grid_res[0].mime_type == "text/html;profile=mcp-app"
    content_grid = _resource_text(grid_res[0])
    assert "<!DOCTYPE html>" in content_grid
    assert "Query Results" in content_grid


@pytest.mark.anyio
async def test_explain_query_returns_both_text_and_json(storage_with_profile: ProfileStorage):
    """Verify explain_query returns both formatted plan text and plan_json when analyze=False."""
    server = create_server(storage=storage_with_profile)

    mock_plan_text = "Seq Scan on items  (cost=0.00..1.05 rows=5 width=32)"
    mock_plan_json = [{"Plan": {"Node Type": "Seq Scan", "Total Cost": 1.05}}]

    with patch("src.server.DatabaseManager") as MockDB:
        instance = MockDB.return_value

        def fake_explain(query, analyze=False, as_json=False):
            if as_json:
                return mock_plan_json
            return mock_plan_text

        instance.explain_query.side_effect = fake_explain

        result = await _call_tool(server, "explain_query", {"query": "SELECT * FROM items"})
        assert result.is_error is False

        # Parse JSON from result content text
        data = json.loads(_text(result.content[0]))
        assert data["status"] == "ok"
        assert data["plan"] == mock_plan_text
        assert data["plan_json"] == mock_plan_json


@pytest.mark.anyio
async def test_explain_query_analyze_single_execution(storage_with_profile: ProfileStorage):
    """Verify that when analyze=True, explain_query only runs once against the database."""
    server = create_server(storage=storage_with_profile)

    mock_plan_json = [
        {
            "Plan": {
                "Node Type": "Seq Scan",
                "Relation Name": "items",
                "Startup Cost": 0.0,
                "Total Cost": 1.05,
                "Plan Rows": 5,
                "Plan Width": 32,
                "Actual Startup Time": 0.012,
                "Actual Total Time": 0.045,
                "Actual Rows": 5,
                "Actual Loops": 1,
            },
            "Planning Time": 0.035,
            "Execution Time": 0.055,
        }
    ]

    with patch("src.server.DatabaseManager") as MockDB:
        instance = MockDB.return_value
        instance.explain_query.return_value = mock_plan_json

        result = await _call_tool(
            server, "explain_query", {"query": "SELECT * FROM items", "analyze": True}
        )
        assert result.is_error is False

        # Assert explain_query was called exactly once on DatabaseManager
        assert instance.explain_query.call_count == 1
        call_args, call_kwargs = instance.explain_query.call_args
        assert call_kwargs.get("analyze") is True or (len(call_args) > 1 and call_args[1] is True)
        assert call_kwargs.get("as_json") is True or (len(call_args) > 2 and call_args[2] is True)

        data = json.loads(_text(result.content[0]))
        assert data["status"] == "ok"
        assert data["plan_json"] == mock_plan_json
        assert "Seq Scan on items" in data["plan"]
        assert "actual time=" in data["plan"]
        assert "Execution Time:" in data["plan"]


def test_main_closes_pools_even_when_run_raises():
    from src.server import main

    with (
        patch("src.server.create_server") as mock_create,
        patch("src.server.close_all_pools") as mock_close,
    ):
        mock_create.return_value.run.side_effect = RuntimeError("boom")
        with pytest.raises(RuntimeError):
            main()
    mock_create.return_value.run.assert_called_once_with(transport="stdio")
    mock_close.assert_called_once()
