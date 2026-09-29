# Web Documentation & MCP Connection Guide

## Objectives
Integrate an interactive MCP Connection Guide and full MCP Reference into the local web interface (`src/web.py` and `src/static/`), with dynamic path detection and copyable client configurations.

## Tasks
- [x] **TASK-1**: Implement `GET /api/info` in `src/web.py` and add unit tests in `tests/test_web.py`.
- [x] **TASK-2**: Update `src/static/index.html` and `src/static/style.css` with tab navigation, connection guide cards, and complete MCP reference (tools, resources, prompts, security model).
- [x] **TASK-3**: Update `src/static/app.js` to handle tab switching, fetch `/api/info`, populate real paths into config snippets, and enable one-click copy.
- [x] **TASK-4**: Verify with automated test suite (`pytest`) and validate all web endpoints.

## Route
- TASK-1: inline
- TASK-2: inline batch
- TASK-3: inline
- TASK-4: verification (82/82 tests pass)

## Progress
- Completed all tasks. Added backward-compatible fallback in `storage.py` for legacy profiles database schemas. All 82 tests passing cleanly.
