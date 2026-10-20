# PgPrism

**PgPrism** is a strictly read-only Model Context Protocol (MCP) server for PostgreSQL. It bridges the gap between complex PostgreSQL databases and AI agents, transforming relational data structures into clear, safe, and actionable insights.

- **PostgreSQL**: Houses your schemas, tables, relationships, and raw data.
- **PgPrism**: Refracts and exposes that database information through a hardened read-only interface.
- **AI Agents**: Query, inspect, and analyze the database via MCP without any ability to mutate data, execute DDL, or trigger destructive locks.

## Key Features

- **Strict Read-Only Defense in Depth**:
  - **AST Layer**: Uses `sqlglot` to parse and validate queries before execution, rejecting any mutations (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `MERGE`), write CTEs, `SELECT INTO`, row locks (`FOR UPDATE`), or dangerous administrative functions.
  - **Session Layer**: Enforces `SET default_transaction_read_only = on` and runs all queries inside explicit read-only transactions at the PostgreSQL engine level.
- **Bounded Connection Pooling**: Self-draining LRU pool cache that prevents connection leaks and bounds resource usage per process.
- **Local Profile Storage**: SQLite holds connection metadata; passwords live in the operating system's secret store through `keyring`, with no plaintext fallback.
- **Web Configuration UI**: A clean, local web dashboard to manage profiles, test connectivity, and inspect documentation.
- **Interactive MCP UI (MCP Apps)**: Built-in visual in-chat components for execution plan exploration (`explain_query`) and tabular data inspection (`read_query`) following the official `@modelcontextprotocol/ext-apps` standard.
- **Pragmatic Modular Architecture**: Zero enterprise boilerplate or unnecessary abstract classes.

---

## Architecture Overview

```text
src/
├── security.py         # SQL AST validator (sqlglot) enforcing read-only queries
├── database/           # PostgreSQL connection management with read-only sessions
│   ├── pool.py         # Bounded LRU connection pool management
│   ├── manager.py      # Database query and schema facade
│   ├── introspection.py# Database, schema, table, index, and constraint discovery
│   ├── diagnostics.py  # Query inspection, stats, and database size telemetry
│   └── types.py        # Typed contracts and JSON serialization
├── credentials.py      # Native OS keyring access, with no file/null fallback
├── storage.py          # SQLite profile metadata and OS credential references
├── server.py           # FastMCP server exposing read-only tools over stdio
└── web.py              # Local web UI (FastAPI) on localhost:8000
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
   - Click **Save Profile** to store metadata in SQLite and the password in your OS secret store. Your OS may ask you to unlock the keychain.
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
Saved connection passwords use the operating system's secret store through [Python keyring](https://keyring.readthedocs.io/). SQLite contains connection metadata and opaque credential references, never new passwords. MCP profile metadata does not include passwords.

| Platform | Supported native store | Setup |
| :--- | :--- | :--- |
| macOS | Keychain | Unlock the user's login keychain when prompted. |
| Windows | Credential Locker | Run the web UI and MCP client as the same Windows user. |
| Linux | Secret Service or KWallet | Start and unlock a compatible desktop secret service. KWallet also needs the Python D-Bus bindings available to the virtual environment. |

Run the web UI and MCP client as the same OS user and in the same desktop session. On Linux, both need access to the session D-Bus. Installing the Python package alone does not install or unlock a desktop secret service. GNOME Keyring provides Secret Service; KDE users can use KWallet with its D-Bus bindings.

PgPrism accepts only native OS backends. Plaintext files, `keyrings.alt` file backends, null keyrings and custom backends are rejected. If `keyring` selects a chain, PgPrism pins one native backend rather than falling through to another store. A locked or unavailable store raises an explicit error; HTTP requests return 503. Profiles with empty passwords and environment-only connections do not require a stored secret.

#### Existing profiles and migration
On startup, PgPrism automatically moves existing SQLite passwords to the OS store. The web app initializes storage during its ASGI lifespan, not when importing `src.web` or constructing `create_app()`. Each secret is written and read back before its SQLite value is cleared. If a secret cannot be stored, the migration rolls back and the original profiles remain available for retry after unlocking the store. Close older PgPrism processes before upgrading so they cannot write plaintext again.

Migration enables SQLite secure deletion, compacts the database and requests a WAL checkpoint. A busy checkpoint logs a warning; close other readers and checkpoint the database before treating old WAL files as sanitized. These steps cannot erase passwords from existing backups, filesystem snapshots or storage-device history. Protect or remove old copies appropriately, and rotate credentials if they may have been exposed.

The metadata database remains at `~/.config/pgprism/profiles.db`, with the existing legacy and local path fallbacks. Copying that file to a different user or machine does **not** copy its passwords. Recreate profiles with their passwords on the destination. If a saved secret is missing, PgPrism reports it rather than treating it as an empty password.

Updating a password creates a new reference and removes the old secret after SQLite commits. If removal of an obsolete secret fails, PgPrism logs its reference for manual cleanup under the `pgprism` service in the OS store. SQLite and the OS store are not one atomic transaction; interruption can leave unused secrets in the OS store. Deleting a profile also removes its saved secret.

This protects passwords at rest, not a compromised desktop session or process. Hostnames, usernames, database names and other profile metadata remain readable in SQLite. Passwords must be present in process memory while connecting. Environment-provided credentials remain supported and are not copied into SQLite or the keyring.

### Tool Annotations
All MCP tools declare `readOnlyHint: true` and `destructiveHint: false` in their annotations, allowing MCP clients to auto-approve tool execution without user confirmation.

---

## Testing

Run all unit tests:
```bash
.venv/bin/pytest -v
```

Web tests should use `with TestClient(app)` to run startup and shutdown. SQLite connections are closed after each storage operation, including failures; closing does not replace transaction commit or rollback.
