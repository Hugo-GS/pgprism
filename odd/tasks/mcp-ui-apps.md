# MCP UI (MCP Apps Extension)

## Objectives
Implement the official Model Context Protocol UI extension (MCP Apps standard / `@modelcontextprotocol/ext-apps`) in `mcp-postgresql`. Provide interactive in-chat visual components for `explain_query` (interactive execution plan tree and flamegraph-style node inspector) and `read_query` (interactive sortable/filterable data grid), with graceful text fallback and local preview support in the web interface.

## Tasks
- [x] **TASK-1**: Enhance `src/database.py` to support structured JSON query plans (`explain_query(..., as_json=True)`) and update unit tests in `tests/test_database.py`.
- [x] **TASK-2**: Create self-contained MCP Apps frontend components in `src/static/ui/explain_viewer.html` and `src/static/ui/data_grid.html` with JSON-RPC postMessage bridge, styling, and fallback demo mode.
- [x] **TASK-3**: Register `ui://postgres/explain-viewer` and `ui://postgres/data-grid` resources and attach UI metadata to `explain_query` and `read_query` in `src/server.py`.
- [x] **TASK-4**: Expose UI preview endpoints (`/ui/explain-viewer` and `/ui/data-grid`) in `src/web.py` and update package data in `pyproject.toml`.
- [x] **TASK-5**: Add unit and integration tests in `tests/test_database.py`, `tests/test_server.py`, and `tests/test_web.py`, and verify with `pytest`.

## Phase 2: Audit Remediation (Spec Compliance & Security)
- [x] **TASK-6**: Refactor `src/server.py` to use official `mcp.server.apps.Apps` extension (`apps.add_html_resource`, `@apps.tool`), advertising `io.modelcontextprotocol/ui` and using `text/html;profile=mcp-app` MIME type.
- [x] **TASK-7**: Update postMessage communication in `src/static/ui/explain_viewer.html` and `src/static/ui/data_grid.html` to implement the standard `ui/initialize` handshake and `ui/notifications/tool-result` / `ui/notifications/tool-input` listeners.
- [x] **TASK-8**: Fix XSS in `data_grid.html` cell copy buttons, fix CSV export when filter matches zero rows, and escape HTML in table headers/node types.
- [x] **TASK-9**: Single-query execution for `explain_query` (avoid running query twice on `analyze=True`) and fix `_serialize_value` for Decimal NaN/Infinity in `src/database.py`.
- [x] **TASK-10**: Update and expand tests in `tests/test_server.py`, `tests/test_database.py`, and verify with `pytest`.

## Route
- Route: Delegated direct (Phase 2 touches 4 core files + tests)
- Engram mirror: Pending (Engram tool unavailable in runtime)

## Progress
- Initialized feature document.
- Completed TASK-1: Enhanced `explain_query` in `src/database.py` with `as_json: bool = False` returning parsed JSON structure with fallback, backward compatible with string return type. Added unit tests for JSON explain in `tests/test_database.py`.
- Completed TASK-2: Created `src/static/ui/explain_viewer.html` and `src/static/ui/data_grid.html`.
- Completed TASK-3: Registered `ui://` resources and attached tool metadata.
- Completed TASK-4: Added preview endpoints in `src/web.py` and updated package data in `pyproject.toml`.
- Completed TASK-5: Added unit and integration tests across tests files (99/99 tests passed).
- Completed Audit: Generated comprehensive audit artifact with 3 critical spec gaps, 1 high security bug, 3 medium issues, and 4 low issues. Approved by user for remediation.
- Completed TASK-6: Refactored `src/server.py` to initialize `Apps()`, register `ui://postgres/explain-viewer` and `ui://postgres/data-grid` via `apps.add_html_resource`, bind tools via `@apps.tool(...)`, pass `extensions=[apps]` to `MCPServer`, and format single-execution JSON plan to text when `analyze=True`.
- Completed TASK-7: Updated `src/static/ui/explain_viewer.html` and `src/static/ui/data_grid.html` to send `ui/initialize` handshake with `appCapabilities: {}` on page load, handle `ui/notifications/tool-result` and `ui/notifications/tool-input`, and preserve backwards compatibility.
- Completed TASK-8: Replaced inline string interpolation copy buttons with safe DOM event handlers to eliminate XSS, fixed CSV export fallback when filter is active, fixed row #1 visual highlight on initial load, and added `escapeHtml` to prevent script/markup injection.
- Completed TASK-9: In `_serialize_value`, converted Decimal/float NaN and Infinity to `None` to prevent invalid JSON generation.
- Completed TASK-10: Added unit tests verifying `io.modelcontextprotocol/ui` extension capability, `text/html;profile=mcp-app` MIME type, metadata bindings, Decimal NaN/Infinity serialization, and `explain_query` single-execution verification. 102/102 tests passing (100%).
- Work-unit commit: `9ebdce3` (`feat(ui): implement official MCP Apps extension, UI viewers, and spec enhancements`).

