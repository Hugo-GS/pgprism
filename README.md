# MCP PostgreSQL (Strictly Read-Only)

A lightweight, strictly read-only Model Context Protocol (MCP) server for PostgreSQL built with Python.

Features:
- **Strict Read-Only Defense in Depth**:
  - **AST Layer**: Uses `sqlglot` to parse and validate queries before execution, rejecting any mutations (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `MERGE`), write CTEs, or administrative procedure calls.
  - **Session Layer**: Enforces `SET default_transaction_read_only = on` and runs all queries inside explicit read-only transactions at the PostgreSQL engine level.
- **Local SQLite Profile Storage**: Store and switch database credentials locally without cloud tokens or external dependencies.
- **Web Configuration UI**: A clean, local web dashboard to manage profiles, test connectivity, and activate databases.
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
   git clone <repo-url> mcp-postgresql
   cd mcp-postgresql
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
| `list_schemas` | _none_ | Lists user schemas in the database. |
| `list_tables` | `schema: str = "public"` | Lists tables and views in the schema. |
| `describe_table` | `table: str, schema: str = "public"` | Inspects column types, nullability, defaults, and primary keys. |
| `explain_query` | `query: str, analyze: bool = False` | Returns the EXPLAIN query execution plan. |
| `get_active_profile` | _none_ | Displays active database profile metadata (password masked). |
| `list_profiles` | _none_ | Lists all stored database profiles. |
| `switch_profile` | `profile_name: str` | Switches active database profile on the fly. |

---

## MCP Client Configuration

### Claude Desktop
Add to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "postgresql": {
      "command": "/path/to/mcp-postgresql/.venv/bin/python3",
      "args": ["-m", "src.server"],
      "cwd": "/path/to/mcp-postgresql"
    }
  }
}
```

### Antigravity / Cursor
Configure the command:
```json
{
  "command": "/path/to/mcp-postgresql/.venv/bin/mcp-postgresql"
}
```

---

## Testing

Run all unit tests:
```bash
.venv/bin/pytest -v
```
