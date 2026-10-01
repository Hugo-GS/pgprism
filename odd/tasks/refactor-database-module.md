# Refactor database.py → src/database/ package

## Objective
Break the 516-line God Module `src/database.py` into a cohesive `src/database/` package with clear SRP boundaries.

## Problem
`DatabaseManager` mixes 6 responsibilities: pool management, serialization, DTOs, query execution, schema introspection, and operational diagnostics. 7 of 10 methods duplicate 3-level connection boilerplate.

## Why
Improve maintainability, testability, and enable future extension without growing a single file. Fix stale pool key bug and dead import.

## Scope
- Convert `src/database.py` → `src/database/` package (5 modules + __init__.py)
- Update test imports and mock targets
- Fix `_pool_key` to include password/timeout hash
- Remove dead `from psycopg import sql` import
- Zero public API changes

## Constraints
- `from src.database import DatabaseManager` must keep working
- All 14 existing tests must pass
- No SQL query changes
- No new dependencies

## Route
Delegated direct (writer trigger: 6+ non-trivial files)

## TDD
Disabled (no project/session configuration found). Functional checks via existing test suite.

## Delivery
Single-pr, estimated ~600 authored changed lines (additions from new package structure + deletions of old monolith).

## Tasks

- [ ] T1: Create `src/database/` package — types.py, pool.py, introspection.py, diagnostics.py, manager.py, __init__.py — and delete old `src/database.py`
- [ ] T2: Update `tests/test_database.py` — fix import paths and mock targets
- [ ] T3: Verify — run full test suite, import checks, confirm no regressions

## Acceptance Criteria
- `python -m pytest tests/ -v` — all 14 tests pass
- `python -c "from src.database import DatabaseManager, close_all_pools, _serialize_value, _pool_cache"` — no errors
- `python -c "from src.server import create_server; from src.web import create_app"` — no errors
- `src/database.py` file no longer exists
- `src/database/` directory contains 6 .py files
