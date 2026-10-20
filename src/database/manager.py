"""DatabaseManager facade — the single public entry point."""

import json
from typing import Any, Dict, List, Optional, Tuple, Union

from src.security import validate_readonly_query

from src.database import diagnostics, introspection
from src.database.pool import PoolManager
from src.database.types import (
    JsonValue,
    QueryResult,
    TableDescription,
    TableInfo,
    serialize_value,
)


class DatabaseManager:
    """Manages read-only connections and queries to a PostgreSQL database."""

    def __init__(self, profile, database: Optional[str] = None) -> None:
        self._pool = PoolManager(profile, database)

    @property
    def profile(self):
        return self._pool.profile

    @property
    def current_database(self) -> str:
        return self._pool.current_database

    @current_database.setter
    def current_database(self, value: str) -> None:
        self._pool.current_database = value

    def set_database(self, database: str) -> None:
        """Switches the active database for the connection."""
        self._pool.set_database(database)

    def get_conninfo(self, db_override: Optional[str] = None) -> str:
        """Constructs a PostgreSQL libpq connection string."""
        return self._pool.get_conninfo(db_override)

    def test_connection(self, timeout: float = 5.0) -> Tuple[bool, str]:
        """Tests the connection and returns (success, message_or_version)."""
        return self._pool.test_connection(timeout)

    def execute_query(
        self,
        query: str,
        params: Optional[Tuple[object, ...] | Dict[str, object]] = None,
        max_rows: int = 100,
    ) -> QueryResult:
        """Runs a read-only SQL query after AST validation."""
        clean_sql = validate_readonly_query(query)

        with self._pool.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(clean_sql, params)

                if not cur.description:
                    return {"columns": [], "rows": [], "row_count": 0, "truncated": False}

                columns = [desc.name for desc in cur.description]
                fetched = cur.fetchmany(max_rows + 1)
                truncated = len(fetched) > max_rows
                rows_data = fetched[:max_rows]

                serialized_rows = [
                    {col: serialize_value(val) for col, val in zip(columns, row)}
                    for row in rows_data
                ]

                return {
                    "columns": columns,
                    "rows": serialized_rows,
                    "row_count": len(serialized_rows),
                    "truncated": truncated,
                }

    def explain_query(
        self, query: str, analyze: bool = False, as_json: bool = False
    ) -> Union[str, List[Dict[str, Any]], Dict[str, Any]]:
        """Explains the execution plan of a read-only query."""
        clean_sql = validate_readonly_query(query)

        if as_json:
            prefix = "EXPLAIN (FORMAT JSON, ANALYZE, BUFFERS) " if analyze else "EXPLAIN (FORMAT JSON) "
        else:
            prefix = "EXPLAIN (ANALYZE, BUFFERS) " if analyze else "EXPLAIN "

        full_sql = prefix + clean_sql

        with self._pool.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(full_sql)
                rows = cur.fetchall()

                if as_json:
                    if not rows:
                        return []
                    first_val = rows[0][0]
                    if isinstance(first_val, (list, dict)):
                        return first_val
                    raw_json = "\n".join(str(r[0]) for r in rows)
                    return json.loads(raw_json)
                else:
                    lines = [r[0] for r in rows]
                    return "\n".join(lines)

    def list_databases(self) -> List[str]:
        """Lists accessible non-template databases on the PostgreSQL server."""
        return introspection.list_databases(self._pool)

    def list_schemas(self) -> List[str]:
        """Lists user-accessible schemas in the database."""
        return introspection.list_schemas(self._pool)

    def list_tables(self, schema: str = "public") -> List[TableInfo]:
        """Lists tables and views in the specified schema."""
        return introspection.list_tables(self._pool, schema)

    def describe_table(self, table_name: str, schema: str = "public") -> TableDescription:
        """Inspects columns, types, primary keys, and foreign keys of a table."""
        return introspection.describe_table(self._pool, table_name, schema)

    def list_indexes(self, table_name: str, schema: str = "public") -> list[dict[str, JsonValue]]:
        """Lists indexes on a table."""
        return introspection.list_indexes(self._pool, table_name, schema)

    def list_foreign_keys(self, table_name: str, schema: str = "public") -> list[dict[str, JsonValue]]:
        """Lists foreign key relationships for a table."""
        return introspection.list_foreign_keys(self._pool, table_name, schema)

    def list_constraints(self, table_name: str, schema: str = "public") -> list[dict[str, JsonValue]]:
        """Lists CHECK, UNIQUE, and EXCLUDE constraints for a table."""
        return introspection.list_constraints(self._pool, table_name, schema)

    def table_stats(self, table_name: str, schema: str = "public") -> Dict[str, JsonValue]:
        """Returns table statistics from pg_stat_user_tables."""
        return diagnostics.table_stats(self._pool, table_name, schema)

    def running_queries(self) -> List[Dict[str, JsonValue]]:
        """Returns currently running queries from pg_stat_activity."""
        return diagnostics.running_queries(self._pool)

    def database_size(self) -> Dict[str, JsonValue]:
        """Returns the size of the current database and its largest tables."""
        return diagnostics.database_size(self._pool)
