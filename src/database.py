import json
import threading
from contextlib import contextmanager
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterator, List, Optional, Tuple, TypeAlias, TypedDict, Union
import uuid

import psycopg
from psycopg import sql
from psycopg_pool import ConnectionPool

from src.security import validate_readonly_query
from src.storage import Profile

JsonPrimitive: TypeAlias = Union[str, int, float, bool, None]
JsonValue: TypeAlias = Union[JsonPrimitive, List["JsonValue"], Dict[str, "JsonValue"]]


class QueryResult(TypedDict):
    columns: List[str]
    rows: List[Dict[str, JsonValue]]
    row_count: int
    truncated: bool


class TableInfo(TypedDict):
    table_name: str
    table_type: str


class ColumnInfo(TypedDict):
    name: str
    type: str
    nullable: bool
    default: Optional[str]
    is_primary_key: bool


class TableDescription(TypedDict):
    table: str
    schema: str
    columns: List[ColumnInfo]


def _serialize_value(val: object) -> JsonValue:
    """Convert PostgreSQL specific or non-JSON-serializable types to Python primitives."""
    if val is None:
        return None
    if isinstance(val, (datetime, date, time)):
        return val.isoformat()
    if isinstance(val, uuid.UUID):
        return str(val)
    if isinstance(val, Decimal):
        if val.is_nan() or val.is_infinite():
            return None
        try:
            return float(val) if val % 1 else int(val)
        except InvalidOperation:
            return None
    if isinstance(val, float):
        import math
        if math.isnan(val) or math.isinf(val):
            return None
        return val
    if isinstance(val, bytes):
        return val.hex()
    if isinstance(val, (list, tuple)):
        return [_serialize_value(x) for x in val]
    if isinstance(val, dict):
        return {str(k): _serialize_value(v) for k, v in val.items()}
    if isinstance(val, (str, int, bool)):
        return val
    return str(val)



_pool_lock = threading.Lock()
_pool_cache: dict[str, ConnectionPool] = {}


def _pool_key(profile: Profile, database: str) -> str:
    return f"{profile.host}:{profile.port}/{database}/{profile.username}/{profile.sslmode}"


def close_all_pools() -> None:
    with _pool_lock:
        for pool in _pool_cache.values():
            try:
                pool.close()
            except Exception:
                pass
        _pool_cache.clear()

class DatabaseManager:
    """Manages read-only connections and queries to a PostgreSQL database."""

    def __init__(self, profile: Profile, database: Optional[str] = None) -> None:
        self.profile = profile
        self.current_database = database or profile.database or "postgres"

    def set_database(self, database: str) -> None:
        """Switches the active database for the connection."""
        if not database or not database.strip():
            raise ValueError("Database name cannot be empty.")
        self.current_database = database.strip()

    def get_conninfo(self, db_override: Optional[str] = None) -> str:
        """Constructs a PostgreSQL libpq connection string."""
        target_db = db_override or self.current_database
        parts = [
            f"host={self.profile.host}",
            f"port={self.profile.port}",
            f"dbname={target_db}",
            f"user={self.profile.username}",
            f"sslmode={self.profile.sslmode}",
        ]
        if self.profile.password:
            parts.append(f"password={self.profile.password}")
        return " ".join(parts)

    def _get_pool(self, db_override: str | None = None) -> ConnectionPool:
        target_db = db_override or self.current_database
        key = _pool_key(self.profile, target_db)
        with _pool_lock:
            if key not in _pool_cache:
                conninfo = self.get_conninfo(db_override=target_db)
                _pool_cache[key] = ConnectionPool(
                    conninfo,
                    min_size=1,
                    max_size=3,
                    open=True,
                    timeout=10.0,
                    kwargs={"options": f"-c default_transaction_read_only=on -c statement_timeout={self.profile.statement_timeout_ms}", "connect_timeout": 5},
                )
            return _pool_cache[key]

    @contextmanager
    def _read_only_transaction(self, conn: psycopg.Connection) -> Iterator[None]:
        """Runs a transaction with an explicit PostgreSQL read-only mode."""
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
            yield

    def test_connection(self, timeout: float = 5.0) -> Tuple[bool, str]:
        """Tests the connection and returns (success, message_or_version)."""
        try:
            with self._get_pool().connection(timeout=timeout) as conn:
                with self._read_only_transaction(conn):
                    with conn.cursor() as cur:
                        cur.execute("SELECT version();")
                        row = cur.fetchone()
                        version = row[0] if row else "Unknown PostgreSQL version"
                        return True, version
        except Exception as e:
            return False, str(e)

    def execute_query(
        self,
        query: str,
        params: Optional[Tuple[object, ...] | Dict[str, object]] = None,
        max_rows: int = 100,
    ) -> QueryResult:
        """Runs a read-only SQL query after AST validation."""
        clean_sql = validate_readonly_query(query)

        with self._get_pool().connection() as conn:
            with self._read_only_transaction(conn):
                with conn.cursor() as cur:
                    cur.execute(clean_sql, params)

                    if not cur.description:
                        # For commands without rows returned (e.g. SHOW or EXPLAIN without output)
                        return {"columns": [], "rows": [], "row_count": 0, "truncated": False}

                    columns = [desc.name for desc in cur.description]
                    # Fetch max_rows + 1 to detect if results were truncated
                    fetched = cur.fetchmany(max_rows + 1)
                    truncated = len(fetched) > max_rows
                    rows_data = fetched[:max_rows]

                    serialized_rows = [
                        {col: _serialize_value(val) for col, val in zip(columns, row)}
                        for row in rows_data
                    ]

                    return {
                        "columns": columns,
                        "rows": serialized_rows,
                        "row_count": len(serialized_rows),
                        "truncated": truncated,
                    }

    def list_databases(self) -> List[str]:
        """Lists accessible non-template databases on the PostgreSQL server."""
        sql_text = """
            SELECT datname
            FROM pg_database
            WHERE datistemplate = false
            ORDER BY datname;
        """
        res = self.execute_query(sql_text, max_rows=500)
        return [str(r["datname"]) for r in res["rows"]]

    def list_schemas(self) -> List[str]:
        """Lists user-accessible schemas in the database."""
        sql_text = """
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name NOT IN ('pg_catalog', 'information_schema')
              AND schema_name NOT LIKE 'pg_temp%'
              AND schema_name NOT LIKE 'pg_toast%'
            ORDER BY schema_name;
        """
        res = self.execute_query(sql_text, max_rows=500)
        return [str(r["schema_name"]) for r in res["rows"]]

    def list_tables(self, schema: str = "public") -> List[TableInfo]:
        """Lists tables and views in the specified schema."""
        sql_text = """
            SELECT
                table_name,
                table_type
            FROM information_schema.tables
            WHERE table_schema = %s
            ORDER BY table_type, table_name;
        """
        # Execute query with parameter
        with self._get_pool().connection() as conn:
            with self._read_only_transaction(conn):
                with conn.cursor() as cur:
                    cur.execute(sql_text, (schema,))
                    rows = cur.fetchall()
                    return [
                        TableInfo(table_name=str(r[0]), table_type=str(r[1]))
                        for r in rows
                    ]

    def describe_table(self, table_name: str, schema: str = "public") -> TableDescription:
        """Inspects columns, types, primary keys, and foreign keys of a table."""
        col_sql = """
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position;
        """

        pk_sql = """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
              AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = %s
              AND tc.table_name = %s;
        """

        with self._get_pool().connection() as conn:
            with self._read_only_transaction(conn):
                with conn.cursor() as cur:
                    cur.execute(col_sql, (schema, table_name))
                    col_rows = cur.fetchall()

                    cur.execute(pk_sql, (schema, table_name))
                    pk_rows = cur.fetchall()
                    primary_keys = {r[0] for r in pk_rows}

                    columns: List[ColumnInfo] = [
                        ColumnInfo(
                            name=str(r[0]),
                            type=str(r[1]),
                            nullable=(r[2] == "YES"),
                            default=str(r[3]) if r[3] is not None else None,
                            is_primary_key=(r[0] in primary_keys),
                        )
                        for r in col_rows
                    ]

                    return TableDescription(
                        table=table_name,
                        schema=schema,
                        columns=columns,
                    )

    def explain_query(
        self, query: str, analyze: bool = False, as_json: bool = False
    ) -> Union[str, List[Dict[str, Any]], Dict[str, Any]]:
        """Explains the execution plan of a read-only query."""
        clean_sql = validate_readonly_query(query)

        if as_json:
            prefix = "EXPLAIN (FORMAT JSON, ANALYZE, BUFFERS) " if analyze else "EXPLAIN (FORMAT JSON) "
            full_sql = prefix + clean_sql
            with self._get_pool().connection() as conn:
                with self._read_only_transaction(conn):
                    with conn.cursor() as cur:
                        cur.execute(full_sql)
                        rows = cur.fetchall()
                        if not rows:
                            return []
                        first_val = rows[0][0]
                        if isinstance(first_val, (list, dict)):
                            return first_val
                        raw_json = "\n".join(str(r[0]) for r in rows)
                        return json.loads(raw_json)
        else:
            prefix = "EXPLAIN (ANALYZE, BUFFERS) " if analyze else "EXPLAIN "
            full_sql = prefix + clean_sql
            with self._get_pool().connection() as conn:
                with self._read_only_transaction(conn):
                    with conn.cursor() as cur:
                        cur.execute(full_sql)
                        lines = [r[0] for r in cur.fetchall()]
                        return "\n".join(lines)

    def list_indexes(self, table_name: str, schema: str = "public") -> List[Dict[str, JsonValue]]:
        """Lists indexes on a table."""
        sql_text = """
            SELECT
                indexname,
                indexdef
            FROM pg_indexes
            WHERE schemaname = %s AND tablename = %s
            ORDER BY indexname;
        """
        with self._get_pool().connection() as conn:
            with self._read_only_transaction(conn):
                with conn.cursor() as cur:
                    cur.execute(sql_text, (schema, table_name))
                    return [{"index_name": str(r[0]), "definition": str(r[1])} for r in cur.fetchall()]

    def list_foreign_keys(self, table_name: str, schema: str = "public") -> List[Dict[str, JsonValue]]:
        """Lists foreign key relationships for a table."""
        sql_text = """
            SELECT
                tc.constraint_name,
                kcu.column_name,
                ccu.table_schema AS foreign_schema,
                ccu.table_name AS foreign_table,
                ccu.column_name AS foreign_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = %s
              AND tc.table_name = %s
            ORDER BY tc.constraint_name;
        """
        with self._get_pool().connection() as conn:
            with self._read_only_transaction(conn):
                with conn.cursor() as cur:
                    cur.execute(sql_text, (schema, table_name))
                    return [
                        {
                            "constraint_name": str(r[0]),
                            "column": str(r[1]),
                            "foreign_schema": str(r[2]),
                            "foreign_table": str(r[3]),
                            "foreign_column": str(r[4]),
                        }
                        for r in cur.fetchall()
                    ]

    def list_constraints(self, table_name: str, schema: str = "public") -> List[Dict[str, JsonValue]]:
        """Lists CHECK, UNIQUE, and EXCLUDE constraints for a table."""
        sql_text = """
            SELECT
                conname AS constraint_name,
                contype AS constraint_type,
                pg_get_constraintdef(c.oid) AS definition
            FROM pg_constraint c
            JOIN pg_namespace n ON n.oid = c.connamespace
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE n.nspname = %s
              AND t.relname = %s
              AND contype IN ('c', 'u', 'x')
            ORDER BY conname;
        """
        type_map = {"c": "CHECK", "u": "UNIQUE", "x": "EXCLUDE"}
        with self._get_pool().connection() as conn:
            with self._read_only_transaction(conn):
                with conn.cursor() as cur:
                    cur.execute(sql_text, (schema, table_name))
                    return [
                        {
                            "constraint_name": str(r[0]),
                            "type": type_map.get(str(r[1]), str(r[1])),
                            "definition": str(r[2]),
                        }
                        for r in cur.fetchall()
                    ]

    def table_stats(self, table_name: str, schema: str = "public") -> Dict[str, JsonValue]:
        """Returns table statistics from pg_stat_user_tables."""
        sql_text = """
            SELECT
                n_live_tup,
                n_dead_tup,
                n_mod_since_analyze,
                last_vacuum,
                last_autovacuum,
                last_analyze,
                last_autoanalyze,
                seq_scan,
                idx_scan
            FROM pg_stat_user_tables
            WHERE schemaname = %s AND relname = %s;
        """
        with self._get_pool().connection() as conn:
            with self._read_only_transaction(conn):
                with conn.cursor() as cur:
                    cur.execute(sql_text, (schema, table_name))
                    row = cur.fetchone()
                    if not row:
                        return {"error": f"No stats found for {schema}.{table_name}"}
                    return {
                        "live_rows": row[0],
                        "dead_rows": row[1],
                        "modifications_since_analyze": row[2],
                        "last_vacuum": row[3].isoformat() if row[3] else None,
                        "last_autovacuum": row[4].isoformat() if row[4] else None,
                        "last_analyze": row[5].isoformat() if row[5] else None,
                        "last_autoanalyze": row[6].isoformat() if row[6] else None,
                        "sequential_scans": row[7],
                        "index_scans": row[8],
                    }

    def running_queries(self) -> List[Dict[str, JsonValue]]:
        """Returns currently running queries from pg_stat_activity."""
        sql_text = """
            SELECT
                pid,
                usename,
                datname,
                state,
                query,
                now() - query_start AS duration,
                wait_event_type,
                wait_event
            FROM pg_stat_activity
            WHERE state IS NOT NULL
              AND pid != pg_backend_pid()
            ORDER BY query_start ASC NULLS LAST;
        """
        with self._get_pool().connection() as conn:
            with self._read_only_transaction(conn):
                with conn.cursor() as cur:
                    cur.execute(sql_text)
                    return [
                        {
                            "pid": r[0],
                            "username": str(r[1]) if r[1] else None,
                            "database": str(r[2]) if r[2] else None,
                            "state": str(r[3]) if r[3] else None,
                            "query": str(r[4]) if r[4] else None,
                            "duration": str(r[5]) if r[5] else None,
                            "wait_event_type": str(r[6]) if r[6] else None,
                            "wait_event": str(r[7]) if r[7] else None,
                        }
                        for r in cur.fetchall()
                    ]

    def database_size(self) -> Dict[str, JsonValue]:
        """Returns the size of the current database and its largest tables."""
        db_size_sql = """
            SELECT
                pg_database_size(current_database()) AS db_size,
                pg_size_pretty(pg_database_size(current_database())) AS db_size_pretty;
        """
        tables_sql = """
            SELECT
                schemaname || '.' || relname AS table_name,
                pg_total_relation_size(relid) AS total_bytes,
                pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
                pg_relation_size(relid) AS table_bytes,
                pg_size_pretty(pg_relation_size(relid)) AS table_size,
                pg_indexes_size(relid) AS index_bytes,
                pg_size_pretty(pg_indexes_size(relid)) AS index_size
            FROM pg_stat_user_tables
            ORDER BY pg_total_relation_size(relid) DESC
            LIMIT 20;
        """
        with self._get_pool().connection() as conn:
            with self._read_only_transaction(conn):
                with conn.cursor() as cur:
                    cur.execute(db_size_sql)
                    db_row = cur.fetchone()
                    cur.execute(tables_sql)
                    table_rows = cur.fetchall()

                    return {
                        "database": self.current_database,
                        "total_size_bytes": db_row[0] if db_row else 0,
                        "total_size": str(db_row[1]) if db_row else "0 bytes",
                        "tables": [
                            {
                                "table": str(r[0]),
                                "total_bytes": r[1],
                                "total_size": str(r[2]),
                                "table_bytes": r[3],
                                "table_size": str(r[4]),
                                "index_bytes": r[5],
                                "index_size": str(r[6]),
                            }
                            for r in table_rows
                        ],
                    }
