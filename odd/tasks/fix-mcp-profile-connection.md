# Fix MCP Profile Detection & Database Connection

## Objectives
Resolve runtime connection failure (`NameError: name 'ConnectionPool' is not defined`), enhance profile resolution edge cases, and add profile search capability across MCP, Web API, and UI.

## Tasks
- [x] **TASK-1**: Fix `ConnectionPool` missing import in `src/database.py` and add regression test in `tests/test_database.py`.
- [x] **TASK-2**: Implement robust fallback resolution in `src/storage.py` (first profile fallback when none active, environment variable fallback when empty, path resolution).
- [x] **TASK-3**: Enhance error handling in `src/server.py` with `test_connection` tool and graceful diagnostics.
- [x] **TASK-4**: Add comprehensive tests in `tests/test_storage.py`, `tests/test_database.py`, and `tests/test_server.py`, run `pytest`, and verify via simulated MCP stdio JSON-RPC client.
- [x] **TASK-5**: Add `search_profiles` (in storage, MCP server, web API `?q=`, and web UI profile search bar) and synchronize catalog documentation across `index.html` and `README.md` (all 18 tools).

## Route
- TASK-1: inline
- TASK-2: inline
- TASK-3: inline
- TASK-4: verification
- TASK-5: inline + verification (92/92 tests pass, JSON-RPC verified)

## Progress
- Completed all tasks.
- Root cause identified: `NameError: name 'ConnectionPool' is not defined` in `src/database.py:107` due to missing import from `psycopg_pool`. Fixed and added pool connection timeout protection.
- Enhanced `src/storage.py` with fallback to first stored profile, zero-config environment variables (`DATABASE_URL`, `POSTGRES_URL`, `PG*`), and smart database path discovery.
- Added `test_connection` and `search_profiles` tools to `src/server.py` (total: 18 tools).
- Synced frontend catalog, search bar, and README.md documentation.
- All 92 tests passing cleanly.
