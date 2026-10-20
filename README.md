# PgPrism (Strictly Read-Only PostgreSQL MCP Server)

A lightweight, strictly read-only Model Context Protocol (MCP) server for PostgreSQL built with Python.

Features:
- **Strict Read-Only Defense in Depth**:
  - **AST Layer**: Uses `sqlglot` to parse and validate queries before execution, rejecting any mutations (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `MERGE`), write CTEs, or administrative procedure calls.
  - **Session Layer**: Enforces `SET default_transaction_read_only = on` and runs all queries inside explicit read-only transactions at the PostgreSQL engine level.
- **Local SQLite Profile Storage**: Store and switch database credentials locally without cloud tokens or external dependencies.
- **Web Configuration UI**: A clean, local web dashboard to manage profiles, test connectivity, and activate databases.
- **Interactive MCP UI (MCP Apps)**: Built-in rich in-chat UI components for query plan visualization (`explain_query`) and tabular data inspection (`read_query`) following the official `@modelcontextprotocol/ext-apps` standard.
- **Pragmatic Modular Architecture**: Zero enterprise boilerplate or unnecessary abstract classes.

---

## Architecture Overview

```text
src/
├── security.py   # SQL AST validator (sqlglot) enforcing read-only queries
├── database.py   # PostgreSQL connection management (psycopg v3) with read-only sessions
├── storage.py    # Local SQLite CRUD for connection profiles
├── server.py     # FastMCP server exposing read-only tools over stdio
└── web.py        # Local web UI (FastAPI) on localhost:8000
```

---

## Installation & Setup

1. **Clone the repository**:
   ```bash
   git clone <repo-url> pgprism
   cd pgprism
   ```

2. **Create virtual environment and install**:
   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -e ".[dev]"
   ```

3. **Run the Web Configuration UI**:
   ```bash
   .venv/bin/python3 -m src.web
   ```
   Open [http://localhost:8000](http://localhost:8000) in your browser:
   - Add your database connection parameters (Host, Port, Database, User, Password, SSL mode).
   - Click **Test Connection** to verify connectivity.
   - Click **Save Profile** to store it in your local SQLite database.
   - Click **Activate** on the profile you wish the MCP server to use.

---

## MCP Tools Available

| Tool | Parameters | Description |
| :--- | :--- | :--- |
| `read_query` | `query: str, max_rows: int = 100` | Executes a strictly read-only query and returns formatted rows. |
| `list_databases` | _none_ | Lists all accessible non-template databases in the PostgreSQL cluster. |
| `select_database` | `database_name: str` | Switches the active target database dynamically. |
| `list_schemas` | _none_ | Lists user schemas in the active database. |
| `list_tables` | `schema: str = "public"` | Lists tables and views in the schema. |
| `describe_table` | `table: str, schema: str = "public"` | Inspects column types, nullability, defaults, and primary keys. |
| `explain_query` | `query: str, analyze: bool = False` | Returns the EXPLAIN query execution plan. |
| `list_indexes` | `table: str, schema: str = "public"` | Lists indexes on a table with their definitions. |
| `list_foreign_keys` | `table: str, schema: str = "public"` | Lists foreign key relationships for a table. |
| `list_constraints` | `table: str, schema: str = "public"` | Lists CHECK, UNIQUE, and EXCLUDE constraints. |
| `table_stats` | `table: str, schema: str = "public"` | Shows row estimates, dead tuples, vacuum info, scan counts. |
| `running_queries` | _none_ | Shows active queries with duration and wait events. |
| `database_size` | _none_ | Returns database and table/index sizes. |
| `test_connection` | _none_ | Verifies connectivity to the active database and returns PostgreSQL version. |
| `get_active_profile` | _none_ | Displays active database profile metadata (password masked). |
| `list_profiles` | _none_ | Lists all stored database profiles. |
| `search_profiles` | `query: str` | Searches stored profiles by partial match on name, host, or database. |
| `switch_profile` | `profile_name: str` | Switches active database profile on the fly. |

---

## MCP Resources Available

Resources provide passive, browsable access to the database structure without tool calls.

| Resource URI | Description |
| :--- | :--- |
| `postgres://profiles` | List of stored connection profiles. |
| `postgres://schemas` | Schemas in the active database. |
| `postgres://schemas/{schema}/tables` | Tables and views in a schema. |
| `postgres://schemas/{schema}/tables/{table}` | Column details, types, and primary keys for a table. |
| `ui://postgres/explain-viewer` | Interactive execution plan visualizer and bottleneck inspector (MCP Apps UI). |
| `ui://postgres/data-grid` | Interactive query results data grid with sorting, filtering, and CSV export (MCP Apps UI). |

---

## MCP Prompts Available

Prompts provide structured debugging workflows for the agent.

| Prompt | Parameters | Description |
| :--- | :--- | :--- |
| `debug_slow_query` | `query: str` | Guides EXPLAIN ANALYZE, index check, and optimization suggestions. |
| `explore_table` | `table: str, schema: str` | Comprehensive table exploration: schema, indexes, FKs, stats, sample data. |
| `find_data_issues` | `table: str, schema: str` | Checks for NULLs, duplicates, orphan FKs, and empty strings. |

---

## MCP Client Configuration

### Claude Desktop
Add to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "pgprism": {
      "command": "/path/to/pgprism/.venv/bin/python3",
      "args": ["-m", "src.server"],
      "cwd": "/path/to/pgprism"
    }
  }
}
```

### Antigravity / Cursor
Configure the command:
```json
{
  "command": "/path/to/pgprism/.venv/bin/pgprism"
}
```

---

## Security Notes

### Read-Only Enforcement
All queries pass through two defense layers:
1. **AST Layer**: `sqlglot` parses and validates queries, rejecting mutations.
2. **Session Layer**: PostgreSQL `default_transaction_read_only = on` + explicit `SET TRANSACTION READ ONLY`.

### Statement Timeout
Each profile has a configurable `statement_timeout_ms` (default: 30,000ms / 30s). This prevents runaway queries from consuming server resources. Configure via the Web UI or when creating profiles.

### EXPLAIN ANALYZE
The `explain_query` tool with `analyze=True` **actually executes the query** to collect real timing data. While the query itself is validated as read-only, complex analytical queries may impact server performance. Use with caution on production databases.

### Password Storage
Connection passwords are stored **unencrypted** in the local SQLite database at `~/.config/pgprism/profiles.db` (with backward-compatible fallback to `~/.config/mcp-postgresql/profiles.db`). This is acceptable for local development debugging. For production environments, consider:
- Using `PGPASSFILE` or environment variables
- OS keychain integration (planned for a future release)

### Tool Annotations
All MCP tools declare `readOnlyHint: true` and `destructiveHint: false` in their annotations, allowing MCP clients to auto-approve tool execution without user confirmation.

---

## Testing

Run all unit tests:
```bash
.venv/bin/pytest -v
```
