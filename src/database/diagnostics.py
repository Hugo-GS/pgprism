"""Operational diagnostics and monitoring queries."""

from typing import Dict, List

from src.database.pool import PoolManager
from src.database.types import JsonValue


def table_stats(
    pool: PoolManager, table_name: str, schema: str = "public"
) -> Dict[str, JsonValue]:
    """Returns table statistics from pg_stat_user_tables."""
    sql_text = """
        SELECT
            n_live_tup, n_dead_tup, n_mod_since_analyze,
            last_vacuum, last_autovacuum,
            last_analyze, last_autoanalyze,
            seq_scan, idx_scan
        FROM pg_stat_user_tables
        WHERE schemaname = %s AND relname = %s
    """
    with pool.connect() as conn:
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


def running_queries(pool: PoolManager) -> List[Dict[str, JsonValue]]:
    """Returns currently running queries from pg_stat_activity."""
    sql_text = """
        SELECT
            pid, usename, datname, state, query,
            now() - query_start AS duration,
            wait_event_type, wait_event
        FROM pg_stat_activity
        WHERE state IS NOT NULL AND pid != pg_backend_pid()
        ORDER BY query_start ASC NULLS LAST
    """
    with pool.connect() as conn:
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


def database_size(pool: PoolManager) -> Dict[str, JsonValue]:
    """Returns the size of the current database and its largest tables."""
    db_size_sql = """
        SELECT
            pg_database_size(current_database()) AS db_size,
            pg_size_pretty(pg_database_size(current_database())) AS db_size_pretty
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
        LIMIT 20
    """
    with pool.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(db_size_sql)
            db_row = cur.fetchone()
            cur.execute(tables_sql)
            table_rows = cur.fetchall()

    return {
        "database": pool.current_database,
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
