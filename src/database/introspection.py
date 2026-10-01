"""Schema and catalog introspection queries."""

from typing import List

from src.database.pool import PoolManager
from src.database.types import (
    ColumnInfo,
    JsonValue,
    TableDescription,
    TableInfo,
)


def list_databases(pool: PoolManager) -> List[str]:
    """Lists accessible non-template databases on the PostgreSQL server."""
    with pool.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT datname FROM pg_database "
                "WHERE datistemplate = false ORDER BY datname"
            )
            return [str(r[0]) for r in cur.fetchall()]


def list_schemas(pool: PoolManager) -> List[str]:
    """Lists user-accessible schemas in the database."""
    with pool.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name NOT IN ('pg_catalog', 'information_schema')
                  AND schema_name NOT LIKE 'pg_temp%%'
                  AND schema_name NOT LIKE 'pg_toast%%'
                ORDER BY schema_name
            """)
            return [str(r[0]) for r in cur.fetchall()]


def list_tables(pool: PoolManager, schema: str = "public") -> List[TableInfo]:
    """Lists tables and views in the specified schema."""
    with pool.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name, table_type "
                "FROM information_schema.tables "
                "WHERE table_schema = %s "
                "ORDER BY table_type, table_name",
                (schema,),
            )
            return [
                TableInfo(table_name=str(r[0]), table_type=str(r[1]))
                for r in cur.fetchall()
            ]


def describe_table(
    pool: PoolManager, table_name: str, schema: str = "public"
) -> TableDescription:
    """Inspects columns, types, primary keys, and foreign keys of a table."""
    col_sql = """
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
    """
    pk_sql = """
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
          AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = %s AND tc.table_name = %s
    """
    with pool.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(col_sql, (schema, table_name))
            col_rows = cur.fetchall()
            cur.execute(pk_sql, (schema, table_name))
            primary_keys = {r[0] for r in cur.fetchall()}

    return TableDescription(
        table=table_name,
        schema=schema,
        columns=[
            ColumnInfo(
                name=str(r[0]),
                type=str(r[1]),
                nullable=(r[2] == "YES"),
                default=str(r[3]) if r[3] is not None else None,
                is_primary_key=(r[0] in primary_keys),
            )
            for r in col_rows
        ],
    )


def list_indexes(
    pool: PoolManager, table_name: str, schema: str = "public"
) -> list[dict[str, JsonValue]]:
    """Lists indexes on a table."""
    with pool.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = %s AND tablename = %s ORDER BY indexname",
                (schema, table_name),
            )
            return [
                {"index_name": str(r[0]), "definition": str(r[1])}
                for r in cur.fetchall()
            ]


def list_foreign_keys(
    pool: PoolManager, table_name: str, schema: str = "public"
) -> list[dict[str, JsonValue]]:
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
          ON tc.constraint_name = kcu.constraint_name
          AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name
          AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = %s AND tc.table_name = %s
        ORDER BY tc.constraint_name
    """
    with pool.connect() as conn:
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


def list_constraints(
    pool: PoolManager, table_name: str, schema: str = "public"
) -> list[dict[str, JsonValue]]:
    """Lists CHECK, UNIQUE, and EXCLUDE constraints for a table."""
    sql_text = """
        SELECT
            conname AS constraint_name,
            contype AS constraint_type,
            pg_get_constraintdef(c.oid) AS definition
        FROM pg_constraint c
        JOIN pg_namespace n ON n.oid = c.connamespace
        JOIN pg_class t ON t.oid = c.conrelid
        WHERE n.nspname = %s AND t.relname = %s
          AND contype IN ('c', 'u', 'x')
        ORDER BY conname
    """
    type_map = {"c": "CHECK", "u": "UNIQUE", "x": "EXCLUDE"}
    with pool.connect() as conn:
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
