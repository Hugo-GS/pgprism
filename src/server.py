"""FastMCP server exposing strictly read-only PostgreSQL tools."""

from typing import Any, Dict, List, Optional
from mcp.server.mcpserver import MCPServer
from src.database import DatabaseManager
from src.security import SecurityError
from src.storage import ProfileStorage


def create_server(storage: Optional[ProfileStorage] = None) -> MCPServer:
    """Creates and configures the MCP server instance."""
    store = storage if storage is not None else ProfileStorage()
    server = MCPServer(
        name="mcp-postgresql",
        version="0.1.0",
        description="Strictly read-only PostgreSQL MCP server with local SQLite profile configuration",
    )

    def _get_active_db() -> DatabaseManager:
        profile = store.get_active_profile()
        if not profile:
            raise ValueError(
                "No active database profile configured. Please add and activate a connection profile."
            )
        return DatabaseManager(profile)

    @server.tool()
    def get_active_profile() -> Dict[str, Any]:
        """Returns details about the currently active PostgreSQL connection profile."""
        profile = store.get_active_profile()
        if not profile:
            return {"status": "error", "message": "No active database profile configured."}

        return {
            "status": "ok",
            "profile": {
                "name": profile.name,
                "host": profile.host,
                "port": profile.port,
                "database": profile.database,
                "username": profile.username,
                "sslmode": profile.sslmode,
                "is_active": profile.is_active,
            },
        }

    @server.tool()
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
                "is_active": p.is_active,
            }
            for p in profiles
        ]

    @server.tool()
    def switch_profile(profile_name: str) -> Dict[str, Any]:
        """Switches the active database connection to another existing profile."""
        profile = store.get_profile_by_name(profile_name)
        if not profile:
            return {"status": "error", "message": f"Profile '{profile_name}' not found."}

        updated = store.set_active_profile(profile.id)
        return {
            "status": "ok",
            "message": f"Active profile switched to '{updated.name}'.",  # type: ignore
        }

    @server.tool()
    def list_schemas() -> List[str]:
        """Lists all user schemas available in the active database."""
        db = _get_active_db()
        return db.list_schemas()

    @server.tool()
    def list_tables(schema: str = "public") -> List[Dict[str, Any]]:
        """Lists all tables and views present in the specified schema."""
        db = _get_active_db()
        return db.list_tables(schema=schema)

    @server.tool()
    def describe_table(table: str, schema: str = "public") -> Dict[str, Any]:
        """Inspects table columns, types, primary keys, and nullability."""
        db = _get_active_db()
        return db.describe_table(table_name=table, schema=schema)

    @server.tool()
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

    @server.tool()
    def explain_query(query: str, analyze: bool = False) -> Dict[str, Any]:
        """Explains the execution plan for a read-only SQL query."""
        try:
            db = _get_active_db()
            plan = db.explain_query(query=query, analyze=analyze)
            return {"status": "ok", "plan": plan}
        except (SecurityError, ValueError) as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            return {"status": "error", "message": f"Explain execution error: {e}"}

    return server


def main() -> None:
    """Entrypoint for running the MCP server over stdio."""
    server = create_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
