# Feature: Local Read-Only PostgreSQL MCP Server

## Objective
Build a lightweight, strictly read-only PostgreSQL Model Context Protocol (MCP) server in Python using a pragmatic modular architecture, local SQLite profile management, AST-level query safety, and a minimal web configuration interface.

## Problem & Rationale
MCP clients (Claude Desktop, Cursor, Antigravity, etc.) need to inspect database structures and execute analytical queries without any risk of accidental schema changes, data loss, or write mutations. Using defense-in-depth ensures safety at both the query parsing layer and the PostgreSQL transaction/session layer.

## Scope & Constraints
- Language: Python (3.14+ compatible)
- Environment: Local `venv` with `pip`
- MCP SDK: Official Python `mcp` (FastMCP)
- Database: `psycopg` (v3) with pooling
- Safety: `sqlglot` AST parsing + session `default_transaction_read_only = on`
- Storage: Local SQLite database for connection profiles
- UI: Minimal FastAPI web UI to manage profiles locally
- Architecture: Pragmatic modular (no unnecessary enterprise boilerplate)
- Engram Mirror: Pending (Engram MCP unavailable in this session)

## Task Checklist
- [ ] **TASK-1**: Environment setup, dependency configuration (`pyproject.toml`, `.venv`), and test framework.
- [ ] **TASK-2**: Read-only AST security validator (`src/security.py`) and unit tests (`tests/test_security.py`).
- [ ] **TASK-3**: Local SQLite profile repository (`src/storage.py`) and unit tests (`tests/test_storage.py`).
- [ ] **TASK-4**: PostgreSQL client with read-only transaction/session enforcement (`src/database.py`).
- [ ] **TASK-5**: FastMCP server integration (`src/server.py`) exposing read-only tools.
- [ ] **TASK-6**: Local web configuration interface (`src/web.py`) and documentation (`README.md`).

## Applicable Checks
- Automated unit tests via `pytest` for security AST validation and SQLite storage.
- Python syntax and import checks.
- MCP tool execution verification.
