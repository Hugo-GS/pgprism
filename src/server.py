"""FastMCP server exposing strictly read-only PostgreSQL tools."""

from pathlib import Path
from typing import Any, Dict, List, Optional
import json
from mcp_types import ToolAnnotations
from mcp.server.mcpserver import MCPServer
from mcp.server.apps import Apps, APP_MIME_TYPE

STATIC_DIR = Path(__file__).resolve().parent / "static"

READONLY_ANNOTATIONS = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
from src.database import DatabaseManager, close_all_pools
from src.security import SecurityError
from src.storage import ProfileStorage


def _format_plan_node(node: Dict[str, Any], indent: int = 0) -> List[str]:
    lines: List[str] = []
    prefix = "  " * indent
    if indent > 0:
        prefix = prefix[:-2] + "->  "
    node_type = str(node.get("Node Type", "Node"))
    rel = node.get("Relation Name")
    rel_str = f" on {rel}" if rel else ""
    alias = node.get("Alias")
    alias_str = f" {alias}" if alias and alias != rel else ""
    startup_cost = float(node.get("Startup Cost", 0.0))
    total_cost = float(node.get("Total Cost", 0.0))
    plan_rows = node.get("Plan Rows", 0)
    plan_width = node.get("Plan Width", 0)
    cost_str = f"(cost={startup_cost:.2f}..{total_cost:.2f} rows={plan_rows} width={plan_width})"
    actual_str = ""
    if "Actual Total Time" in node:
        actual_startup = float(node.get("Actual Startup Time", 0.0))
        actual_total = float(node.get("Actual Total Time", 0.0))
        actual_rows = node.get("Actual Rows", 0)
        actual_loops = node.get("Actual Loops", 1)
        actual_str = f" (actual time={actual_startup:.3f}..{actual_total:.3f} rows={actual_rows} loops={actual_loops})"
    lines.append(f"{prefix}{node_type}{rel_str}{alias_str}  {cost_str}{actual_str}")
    extra_indent = "  " * (indent + 1)
    if "Filter" in node:
        lines.append(f"{extra_indent}Filter: {node['Filter']}")
    if "Rows Removed by Filter" in node:
        lines.append(f"{extra_indent}Rows Removed by Filter: {node['Rows Removed by Filter']}")
    if "Index Cond" in node:
        lines.append(f"{extra_indent}Index Cond: {node['Index Cond']}")
    if "Hash Cond" in node:
        lines.append(f"{extra_indent}Hash Cond: {node['Hash Cond']}")
    for child in node.get("Plans", []):
        lines.extend(_format_plan_node(child, indent + 1))
    return lines


def _format_json_plan_to_text(plan_json: Any) -> str:
    if not isinstance(plan_json, list) or not plan_json:
        return json.dumps(plan_json, indent=2) if plan_json else ""
    first = plan_json[0]
    if not isinstance(first, dict):
        return json.dumps(plan_json, indent=2)
    lines: List[str] = []
    if "Plan" in first and isinstance(first["Plan"], dict):
        lines.extend(_format_plan_node(first["Plan"]))
    if "Planning Time" in first:
        lines.append(f"Planning Time: {first['Planning Time']:.3f} ms")
    if "Execution Time" in first:
        lines.append(f"Execution Time: {first['Execution Time']:.3f} ms")
    return "\n".join(lines) if lines else json.dumps(plan_json, indent=2)


def create_server(storage: Optional[ProfileStorage] = None) -> MCPServer:
    """Creates and configures the MCP server instance."""
    store = storage if storage is not None else ProfileStorage()

    apps = Apps()
    explain_file = STATIC_DIR / "ui" / "explain_viewer.html"
    explain_html = explain_file.read_text(encoding="utf-8") if explain_file.exists() else "<html><body>Explain viewer not found</body></html>"
    data_grid_file = STATIC_DIR / "ui" / "data_grid.html"
    data_grid_html = data_grid_file.read_text(encoding="utf-8") if data_grid_file.exists() else "<html><body>Data grid not found</body></html>"

    apps.add_html_resource(
        uri="ui://postgres/explain-viewer",
        html=explain_html,
        title="PostgreSQL Explain Plan Viewer",
        description="Interactive execution plan tree viewer with bottleneck analysis and metrics.",
    )
    apps.add_html_resource(
        uri="ui://postgres/data-grid",
        html=data_grid_html,
        title="PostgreSQL Data Grid",
        description="Interactive data grid with sorting, search, pagination, and export.",
    )

    active_state: Dict[str, Any] = {"current_db": None, "profile_id": None}

    def _get_active_db() -> DatabaseManager:
        profile = store.get_active_profile()
        if not profile:
            raise ValueError(
                "No active database profile configured. Please add and activate a connection profile."
            )
        if active_state["profile_id"] != profile.id:
            active_state["profile_id"] = profile.id
            active_state["current_db"] = profile.database or "postgres"

        return DatabaseManager(profile, database=active_state["current_db"])

    @apps.tool(
        resource_uri="ui://postgres/data-grid",
        annotations=READONLY_ANNOTATIONS,
    )
    def read_query(query: str, max_rows: int = 100) -> Dict[str, Any]:
        """Executes a strictly read-only SQL query against the active PostgreSQL database.
        
        Mutating queries (INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, etc.) are blocked.
        """
        try:
            db = _get_active_db()
            return db.execute_query(query=query, max_rows=max_rows)
        except (SecurityError, ValueError) as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            return {"status": "error", "message": f"Database execution error: {e}"}

    @apps.tool(
        resource_uri="ui://postgres/explain-viewer",
        annotations=READONLY_ANNOTATIONS,
    )
    def explain_query(query: str, analyze: bool = False) -> Dict[str, Any]:
        """Explains the execution plan for a read-only SQL query."""
        try:
            db = _get_active_db()
            if analyze:
                plan_json = db.explain_query(query=query, analyze=True, as_json=True)
                plan_text = _format_json_plan_to_text(plan_json)
            else:
                plan_text = db.explain_query(query=query, analyze=False, as_json=False)
                try:
                    plan_json = db.explain_query(query=query, analyze=False, as_json=True)
                except Exception:
                    plan_json = None
            return {"status": "ok", "plan": plan_text, "plan_json": plan_json}
        except (SecurityError, ValueError) as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            return {"status": "error", "message": f"Explain execution error: {e}"}

    server = MCPServer(
        name="pgprism",
        version="0.1.0",
        description="PgPrism: Strictly read-only PostgreSQL MCP server with local SQLite profile configuration",
        extensions=[apps],
    )

    @server.tool(annotations=READONLY_ANNOTATIONS)
    def get_active_profile() -> Dict[str, Any]:
        """Returns the currently active PostgreSQL connection profile."""
        profile = store.get_active_profile()
        if not profile:
            return {
                "status": "error",
                "message": "No active database profile configured. Add one via the web UI or set DATABASE_URL / PGHOST environment variables.",
            }

        current_db = active_state["current_db"] or profile.database or "postgres"
        return {
            "status": "ok",
            "profile": {
                "name": profile.name,
                "host": profile.host,
                "port": profile.port,
                "database": current_db,
                "default_database": profile.database,
                "username": profile.username,
                "sslmode": profile.sslmode,
                "statement_timeout_ms": profile.statement_timeout_ms,
                "is_active": profile.is_active,
            },
        }

    @server.tool(annotations=READONLY_ANNOTATIONS)
    def test_connection() -> Dict[str, Any]:
        """Tests connectivity to the active PostgreSQL database and returns the server version or error."""
        try:
            db = _get_active_db()
            success, message = db.test_connection(timeout=5.0)
            if success:
                return {
                    "status": "ok",
                    "connected": True,
                    "database": db.current_database,
                    "server_version": message,
                }
            return {
                "status": "error",
                "connected": False,
                "database": db.current_database,
                "error": message,
            }
        except Exception as e:
            return {
                "status": "error",
                "connected": False,
                "error": str(e),
            }

    @server.tool(annotations=READONLY_ANNOTATIONS)
    def list_databases() -> List[str]:
        """Lists all accessible non-template databases on the PostgreSQL server."""
        db = _get_active_db()
        return db.list_databases()

    @server.tool(annotations=READONLY_ANNOTATIONS)
    def select_database(database_name: str) -> Dict[str, Any]:
        """Switches the target database for subsequent queries and schema exploration."""
        _get_active_db()
        cleaned = database_name.strip()
        if not cleaned:
            return {"status": "error", "message": "Database name cannot be empty."}
        active_state["current_db"] = cleaned
        return {
            "status": "ok",
            "message": f"Active target database set to '{cleaned}'.",
            "database": cleaned,
        }

    @server.tool(annotations=READONLY_ANNOTATIONS)
    def list_profiles() -> List[Dict[str, Any]]:
        """Lists all stored database connection profiles."""
        profiles = store.list_profiles()
        return [
            {
                "id": p.id,
                "name": p.name,
                "host": p.host,
                "port": p.port,
                "database": p.database,
                "username": p.username,
                "sslmode": p.sslmode,
                "statement_timeout_ms": p.statement_timeout_ms,
                "is_active": p.is_active,
            }
            for p in profiles
        ]

    @server.tool(annotations=READONLY_ANNOTATIONS)
    def search_profiles(query: str) -> List[Dict[str, Any]]:
        """Searches stored database connection profiles by partial match on name, host, or database."""
        matches = store.search_profiles(query)
        return [
            {
                "id": p.id,
                "name": p.name,
                "host": p.host,
                "port": p.port,
                "database": p.database,
                "username": p.username,
                "sslmode": p.sslmode,
                "statement_timeout_ms": p.statement_timeout_ms,
                "is_active": p.is_active,
            }
            for p in matches
        ]

    @server.tool(annotations=READONLY_ANNOTATIONS)
    def switch_profile(profile_name: str) -> Dict[str, Any]:
        """Switches the active database connection to another existing profile."""
        profile = store.get_profile_by_name(profile_name)
        if not profile:
            return {"status": "error", "message": f"Profile '{profile_name}' not found."}

        updated = store.set_active_profile(profile.id)
        if not updated:
            return {"status": "error", "message": f"Failed to activate profile '{profile_name}'."}
        active_state["profile_id"] = None
        active_state["current_db"] = None
        return {
            "status": "ok",
            "message": f"Active profile switched to '{updated.name}'.",
        }

    @server.tool(annotations=READONLY_ANNOTATIONS)
    def list_schemas() -> List[str]:
        """Lists all user schemas available in the active database."""
        db = _get_active_db()
        return db.list_schemas()

    @server.tool(annotations=READONLY_ANNOTATIONS)
    def list_tables(schema: str = "public") -> List[Dict[str, Any]]:
        """Lists all tables and views present in the specified schema."""
        db = _get_active_db()
        return db.list_tables(schema=schema)

    @server.tool(annotations=READONLY_ANNOTATIONS)
    def describe_table(table: str, schema: str = "public") -> Dict[str, Any]:
        """Inspects table columns, types, primary keys, and nullability."""
        db = _get_active_db()
        return db.describe_table(table_name=table, schema=schema)


    @server.tool(annotations=READONLY_ANNOTATIONS)
    def list_indexes(table: str, schema: str = "public") -> List[Dict[str, Any]]:
        """Lists indexes on a table, including index definitions."""
        db = _get_active_db()
        return db.list_indexes(table_name=table, schema=schema)

    @server.tool(annotations=READONLY_ANNOTATIONS)
    def list_foreign_keys(table: str, schema: str = "public") -> List[Dict[str, Any]]:
        """Lists foreign key relationships for a table."""
        db = _get_active_db()
        return db.list_foreign_keys(table_name=table, schema=schema)

    @server.tool(annotations=READONLY_ANNOTATIONS)
    def list_constraints(table: str, schema: str = "public") -> List[Dict[str, Any]]:
        """Lists CHECK, UNIQUE, and EXCLUDE constraints on a table."""
        db = _get_active_db()
        return db.list_constraints(table_name=table, schema=schema)

    @server.tool(annotations=READONLY_ANNOTATIONS)
    def table_stats(table: str, schema: str = "public") -> Dict[str, Any]:
        """Returns table statistics: row estimates, dead tuples, vacuum info, scan counts."""
        db = _get_active_db()
        return db.table_stats(table_name=table, schema=schema)

    @server.tool(annotations=READONLY_ANNOTATIONS)
    def running_queries() -> List[Dict[str, Any]]:
        """Shows currently running queries on the server with duration and wait events."""
        db = _get_active_db()
        return db.running_queries()

    @server.tool(annotations=READONLY_ANNOTATIONS)
    def database_size() -> Dict[str, Any]:
        """Returns the size of the current database and its largest tables/indexes."""
        db = _get_active_db()
        return db.database_size()

    @server.resource("postgres://profiles", name="profiles", title="Connection Profiles", description="List of stored database connection profiles.", mime_type="application/json")
    def resource_profiles() -> str:
        profiles = store.list_profiles()
        return json.dumps([{"id": p.id, "name": p.name, "host": p.host, "port": p.port, "database": p.database, "username": p.username, "sslmode": p.sslmode, "is_active": p.is_active} for p in profiles])

    @server.resource("postgres://schemas", name="schemas", title="Database Schemas", description="Schemas in the active database.", mime_type="application/json")
    def resource_schemas() -> str:
        try:
            db = _get_active_db()
            return json.dumps(db.list_schemas())
        except ValueError as e:
            return json.dumps({"error": str(e)})

    @server.resource("postgres://schemas/{schema}/tables", name="schema_tables", title="Schema Tables", description="Tables and views in a schema.", mime_type="application/json")
    def resource_schema_tables(schema: str) -> str:
        try:
            db = _get_active_db()
            tables = db.list_tables(schema=schema)
            return json.dumps(tables)
        except ValueError as e:
            return json.dumps({"error": str(e)})

    @server.resource("postgres://schemas/{schema}/tables/{table}", name="table_description", title="Table Description", description="Column details, types, and primary keys for a table.", mime_type="application/json")
    def resource_table_description(schema: str, table: str) -> str:
        try:
            db = _get_active_db()
            desc = db.describe_table(table_name=table, schema=schema)
            return json.dumps(desc)
        except ValueError as e:
            return json.dumps({"error": str(e)})



    @server.prompt(name="debug_slow_query", title="Debug Slow Query", description="Guides the agent through analyzing and optimizing a slow SQL query.")
    def prompt_debug_slow_query(query: str) -> list[dict]:
        return [
            {
                "role": "user",
                "content": (
                    f"I have a slow SQL query that needs optimization. Please help me debug it:\n\n"
                    f"```sql\n{query}\n```\n\n"
                    "Please follow these steps:\n"
                    "1. Run `explain_query` with `analyze=True` to get the actual execution plan.\n"
                    "2. Use `list_indexes` on the tables involved to check existing indexes.\n"
                    "3. Use `table_stats` to check row estimates and dead tuple counts.\n"
                    "4. Identify bottlenecks (sequential scans, nested loops, high row estimates).\n"
                    "5. Suggest specific index creation or query rewrites to improve performance."
                ),
            }
        ]

    @server.prompt(name="explore_table", title="Explore Table", description="Guides the agent through a comprehensive table exploration for debugging.")
    def prompt_explore_table(table: str, schema: str = "public") -> list[dict]:
        return [
            {
                "role": "user",
                "content": (
                    f"I need to understand the table `{schema}.{table}` for debugging. Please:\n\n"
                    "1. Run `describe_table` to show columns, types, and primary keys.\n"
                    "2. Run `list_indexes` to show existing indexes.\n"
                    "3. Run `list_foreign_keys` to show relationships with other tables.\n"
                    "4. Run `table_stats` to show row estimates, dead tuples, and vacuum info.\n"
                    "5. Run `read_query` with `SELECT * FROM {schema}.{table} LIMIT 5` to show sample data.\n"
                    "6. Summarize the table structure, relationships, and any potential issues."
                ),
            }
        ]

    @server.prompt(name="find_data_issues", title="Find Data Quality Issues", description="Guides the agent through checking a table for common data quality problems.")
    def prompt_find_data_issues(table: str, schema: str = "public") -> list[dict]:
        return [
            {
                "role": "user",
                "content": (
                    f"Please check `{schema}.{table}` for data quality issues:\n\n"
                    "1. Run `describe_table` to understand the schema.\n"
                    "2. For each nullable column, count NULLs: `SELECT column_name, COUNT(*) FILTER (WHERE column_name IS NULL) FROM table`.\n"
                    "3. Check for duplicate rows on primary/unique key columns.\n"
                    "4. Run `list_foreign_keys` and check for orphaned foreign key references.\n"
                    "5. Check for empty strings in text columns that might should be NULL.\n"
                    "6. Report a summary of all issues found with counts and suggested fixes."
                ),
            }
        ]

    return server


def main() -> None:
    """Entrypoint for running the MCP server over stdio."""
    server = create_server()
    try:
        server.run(transport="stdio")
    finally:
        close_all_pools()


if __name__ == "__main__":
    main()
