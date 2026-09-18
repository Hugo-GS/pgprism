"""SQL AST query safety validator for PostgreSQL read-only MCP server."""

import re
from typing import Set, Tuple, Type
import sqlglot
from sqlglot import exp


class SecurityError(Exception):
    """Raised when a SQL query violates read-only safety rules."""
    pass


FORBIDDEN_AST_NODES: Tuple[Type[exp.Expression], ...] = (
    # DML mutations
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    # DDL mutations
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.TruncateTable,
    # Permissions, Transactions, and Session controls
    exp.Grant,
    exp.Revoke,
    exp.Commit,
    exp.Rollback,
    exp.Set,
    exp.Transaction,
    exp.Pragma,
    # Data export / bulk load
    exp.Copy,
    # Table creation via SELECT INTO
    exp.Into,
    # Row-level locking (FOR UPDATE, FOR SHARE, etc.)
    exp.Lock,
)

ALLOWED_ROOT_NODES: Tuple[Type[exp.Expression], ...] = (
    exp.Select,
    exp.Describe,
    exp.Values,
)

FORBIDDEN_FUNCTIONS: Set[str] = {
    # Session / Configuration mutation
    "set_config",

    # Server administration / Backend signaling
    "pg_terminate_backend",
    "pg_cancel_backend",
    "pg_reload_conf",
    "pg_rotate_logfile",
    "pg_promote",
    "pg_log_backend_memory_contexts",

    # File system access
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_stat_file",
    "pg_write_file",

    # Large object exports / imports
    "lo_export",
    "lo_import",
    "lo_unlink",
    "lo_create",

    # Denial of Service / Connection stalling
    "pg_sleep",
    "pg_sleep_for",
    "pg_sleep_until",

    # Advisory locks (can cause deadlocks / starve other clients)
    "pg_advisory_lock",
    "pg_advisory_lock_shared",
    "pg_advisory_unlock",
    "pg_advisory_unlock_all",
    "pg_try_advisory_lock",
    "pg_try_advisory_lock_shared",
    "pg_advisory_xact_lock",
    "pg_advisory_xact_lock_shared",

    # WAL and replication controls
    "pg_switch_wal",
    "pg_create_restore_point",
    "pg_wal_replay_pause",
    "pg_wal_replay_resume",

    # External database links / remote execution
    "dblink_exec",
    "dblink_connect",
    "dblink_open",
    "dblink_send_query",
}


def _validate_explain_command(command_expr: exp.Command) -> None:
    """Validate that an EXPLAIN command is running on a strictly read-only query."""
    text = command_expr.expression.this if command_expr.expression else ""
    # Strip EXPLAIN options (e.g. (ANALYZE, BUFFERS) or ANALYZE VERBOSE) to isolate the target query
    options_pattern = (
        r"^\s*(?:\([^)]*\)|\b(?:ANALYZE|VERBOSE|COSTS|BUFFERS|TIMING|SUMMARY|SETTINGS|"
        r"GENERIC_PLAN|WAL|MEMORY|FORMAT\s+(?:TEXT|XML|JSON|YAML))\b\s*)*"
    )
    match = re.match(options_pattern, text, re.IGNORECASE)
    inner_sql = text[match.end():].strip() if match else ""
    if not inner_sql:
        raise SecurityError(
            f"EXPLAIN must be followed by a valid query statement, got: '{text}'"
        )
    validate_readonly_query(inner_sql)


def validate_readonly_query(sql: str) -> str:
    """Validate that the query contains exactly one statement and is strictly read-only.

    Returns the original cleaned SQL string or raises SecurityError.
    """
    stripped = sql.strip()
    if not stripped:
        raise SecurityError("Empty query provided.")

    try:
        parsed = sqlglot.parse(stripped, read="postgres")
    except Exception as e:
        raise SecurityError(f"SQL parsing error: {e}") from e

    # Filter out None statements (can happen with comments or trailing semicolons)
    statements = [stmt for stmt in parsed if stmt is not None]
    if len(statements) == 0:
        raise SecurityError("Empty query provided.")
    if len(statements) > 1:
        raise SecurityError("Multiple statements are not permitted. Execute one query at a time.")

    root = statements[0]

    # Handle Command expressions (e.g. EXPLAIN and SHOW)
    if isinstance(root, exp.Command):
        cmd_name = (root.this or "").upper()
        if cmd_name == "EXPLAIN":
            _validate_explain_command(root)
            return stripped.rstrip(";")
        elif cmd_name == "SHOW":
            return stripped.rstrip(";")
        else:
            raise SecurityError(f"Command '{cmd_name}' is not permitted.")

    # Check top-level statement type
    if not isinstance(root, ALLOWED_ROOT_NODES):
        statement_type = root.key.upper() if hasattr(root, "key") else type(root).__name__
        raise SecurityError(
            f"Statement type '{statement_type}' is not permitted. Only SELECT, EXPLAIN, and SHOW queries are allowed."
        )

    # Walk full AST to detect forbidden operations anywhere (e.g. within CTEs or subqueries)
    for node in root.walk():
        if isinstance(node, FORBIDDEN_AST_NODES):
            node_name = node.key.upper() if hasattr(node, "key") else type(node).__name__
            raise SecurityError(
                f"Forbidden mutating operation '{node_name}' detected in query."
            )

        if isinstance(node, exp.Command):
            raise SecurityError("Forbidden embedded command detected in query.")

        # Check for dangerous functions
        if isinstance(node, (exp.Anonymous, exp.Func)):
            fn_name = node.name.lower()
            if fn_name in FORBIDDEN_FUNCTIONS:
                raise SecurityError(f"Forbidden function call '{fn_name}' is not permitted.")

    return stripped.rstrip(";")
