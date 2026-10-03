# Fix PostgreSQL connection pool leaks

## Objective
Bound the number of PostgreSQL backends held per process and drain them to zero when idle.

## Problem
`PoolManager._cache` grows without limit. Each pool keeps `min_size=1` connections forever. New keys appear on database switches, credential/timeout changes, profile switches, and web "Test connection" calls. Pools are never closed on shutdown.

## Why
Long-running sessions can exhaust the target server's `max_connections`. A web connection test with bad credentials also retries the login in the background for up to 300s.

## Scope (authorized)
- `src/database/pool.py`: OrderedDict LRU (`MAX_POOLS=4`), `min_size=0`, `max_size=3`, `max_idle=60s`, `application_name=mcp-postgresql`, stale-credential pool replacement, pools closed outside the lock, one checkout retry on `PoolClosed`, unpooled `test_connection`, non-blocking `close_all`.
- `src/web.py`: FastAPI lifespan that calls `close_all_pools()` on shutdown.
- `src/server.py`: `main()` calls `close_all_pools()` in a `finally`.
- Tests in `tests/test_database.py`, `tests/test_web.py`, `tests/test_server.py`.

## Constraints
- No public API change (`from src.database import DatabaseManager, close_all_pools`).
- No SQL changes and no new dependencies.
- The MCP server and the web UI are separate processes, so no cross-process eviction.

## Plan reference
Approved plan: `connection_leak_plan.md` (conversation artifact). Limits accepted: MAX_POOLS=4, max_idle=60s, max_size=3.

## TDD
Disabled. Source: no project or session config; the previous feature doc records it as disabled. Runner: `.venv/bin/python -m pytest tests/ -v`.

## Delivery
`single-pr` on `feat/mcp-postgresql-server`. Forecast: ~250 authored changed lines.

## Tasks
- [x] T1: Bound and self-drain pools in `pool.py` and add database tests. Route: delegated (writer trigger: pool.py + test_database.py are non-trivial). Commit: `9bbbb8f fix(database): bound and self-drain connection pools` (+193/-43). Suite: 109 passed.
- [x] T2: Shutdown hooks in `web.py` and `server.py` and add web/server tests. Route: delegated (same writer). Commit: `eed0ab9 fix: close connection pools on process shutdown` (+40/-5). Suite: 111 passed.
- [x] T3: Full test suite plus review assessment. Route: inline. Parent verified the diff and the suite (111 passed), corrected an inaccurate comment in `pool.py`, and committed it with this document.

## Acceptance criteria
- At most MAX_POOLS pools per process. Evicted and stale pools are closed.
- New pools open no connections until first use, then drain when idle.
- `test_connection` leaves nothing in the cache.
- Both entrypoints close all pools on exit.
- The full suite passes.

## Progress / Evidence
- Authored changed lines: ~283 (under the ~400 budget).
- RDD review assessment: UNAVAILABLE (`gentle-ai` CLI not installed). Unreviewed range: ba7a64c..HEAD. Per policy the commits are treated as due; run the preflight once the CLI is available.
- Manual verification against a real Postgres (pg_stat_activity, application_name='mcp-postgresql'): PENDING (user).
- Engram mirror: PENDING (Engram tools unavailable in this runtime).

## Next step
User runs the manual pg_stat_activity verification, then decides on push/PR.
