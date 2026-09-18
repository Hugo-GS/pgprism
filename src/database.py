"""PostgreSQL database manager with strict read-only enforcement."""

from datetime import date, datetime, time
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, TypeAlias, TypedDict, Union
import uuid
import psycopg
from psycopg import sql
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
        return float(val) if val % 1 else int(val)
    if isinstance(val, bytes):
        return val.hex()
    if isinstance(val, (list, tuple)):
        return [_serialize_value(x) for x in val]
    if isinstance(val, dict):
        return {str(k): _serialize_value(v) for k, v in val.items()}
    if isinstance(val, (str, int, float, bool)):
        return val
    return str(val)


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

    def _get_connection(self, db_override: Optional[str] = None) -> psycopg.Connection:
        """Establishes a connection with default_transaction_read_only=on."""
        # Enforce read-only default at session level through options
        return psycopg.connect(
            self.get_conninfo(db_override=db_override),
            options="-c default_transaction_read_only=on",
            connect_timeout=10,
        )

    def test_connection(self) -> Tuple[bool, str]:
        """Tests the connection and returns (success, message_or_version)."""
        try:
            with self._get_connection() as conn:
                with conn.transaction(read_only=True):
                    with conn.cursor() as cur:
                        cur.execute("SELECT version();")
                        version = cur.fetchone()[0]  # type: ignore
                        return True, version
        except Exception as e:
            return False, str(e)

    def execute_query(
        self,
        query: str,
        params: Optional[Tuple[object, ...] | Dict[str, object]] = None,
        max_rows: int = 100,
    ) -> QueryResult:
        """Validates and executes a strictly read-only SQL query."""
        # 1. AST Safety check (Defense layer 1)
        clean_sql = validate_readonly_query(query)

        # 2. Database level read-only transaction (Defense layer 2)
        with self._get_connection() as conn:
            with conn.transaction(read_only=True):
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
        with self._get_connection() as conn:
            with conn.transaction(read_only=True):
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

        with self._get_connection() as conn:
            with conn.transaction(read_only=True):
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

    def explain_query(self, query: str, analyze: bool = False) -> str:
        """Explains the execution plan of a read-only query."""
        clean_sql = validate_readonly_query(query)
        prefix = "EXPLAIN (ANALYZE, BUFFERS) " if analyze else "EXPLAIN "
        full_sql = prefix + clean_sql

        with self._get_connection() as conn:
            with conn.transaction(read_only=True):
                with conn.cursor() as cur:
                    cur.execute(full_sql)
                    lines = [r[0] for r in cur.fetchall()]
                    return "\n".join(lines)
