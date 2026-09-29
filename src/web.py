"""Local Web Configuration UI for PostgreSQL MCP Server."""

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from src.database import DatabaseManager
from src.storage import Profile, ProfileCreate, ProfileStorage

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"


def create_app(storage: Optional[ProfileStorage] = None) -> FastAPI:
    """Creates the FastAPI configuration app."""
    store = storage if storage is not None else ProfileStorage()
    app = FastAPI(title="MCP PostgreSQL Configuration")

    # Mount static assets (CSS, JS, etc.)
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=FileResponse)
    def index():
        if not INDEX_FILE.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Configuration UI template not found.",
            )
        return FileResponse(INDEX_FILE)

    @app.get("/ui/explain-viewer", response_class=FileResponse)
    def ui_explain_viewer():
        file_path = STATIC_DIR / "ui" / "explain_viewer.html"
        if not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Explain viewer UI component not found.",
            )
        return FileResponse(file_path)

    @app.get("/ui/data-grid", response_class=FileResponse)
    def ui_data_grid():
        file_path = STATIC_DIR / "ui" / "data_grid.html"
        if not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Data grid UI component not found.",
            )
        return FileResponse(file_path)

    @app.get("/api/info")
    def get_info():
        repo_root = Path(__file__).resolve().parent.parent
        venv_python = repo_root / ".venv" / "bin" / "python3"
        python_exec = str(venv_python) if venv_python.exists() else sys.executable
        cli_command = repo_root / ".venv" / "bin" / "mcp-postgresql"
        active = store.get_active_profile()
        return {
            "project_root": str(repo_root),
            "python_executable": python_exec,
            "cli_command": str(cli_command) if cli_command.exists() else "mcp-postgresql",
            "server_module": "src.server",
            "active_profile": active.name if active else None,
            "active_database": active.database if active else None,
        }

    @app.get("/api/profiles", response_model=List[Profile])
    def list_profiles(q: Optional[str] = None):
        if q and q.strip():
            return store.search_profiles(q.strip())
        return store.list_profiles()

    @app.post("/api/profiles", response_model=Profile, status_code=status.HTTP_201_CREATED)
    def create_profile(payload: ProfileCreate):
        existing = store.get_profile_by_name(payload.name)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Profile with name '{payload.name}' already exists.",
            )
        return store.save_profile(payload)

    @app.post("/api/profiles/{profile_id}/activate", response_model=Profile)
    def activate_profile(profile_id: int):
        profile = store.set_active_profile(profile_id)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile with id {profile_id} not found.",
            )
        return profile

    @app.delete("/api/profiles/{profile_id}")
    def delete_profile(profile_id: int):
        success = store.delete_profile(profile_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile with id {profile_id} not found.",
            )
        return {"success": True}

    @app.get("/api/profiles/{profile_id}/databases", response_model=List[str])
    def list_profile_databases(profile_id: int):
        profile = store.get_profile(profile_id)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile with id {profile_id} not found.",
            )
        db = DatabaseManager(profile)
        try:
            return db.list_databases()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to query server databases: {e}",
            )

    @app.post("/api/profiles/test")
    def test_profile_connection(payload: ProfileCreate):
        # Create temporary Profile instance to test
        temp_profile = Profile(
            id=0,
            name=payload.name,
            host=payload.host,
            port=payload.port,
            database=payload.database,
            username=payload.username,
            password=payload.password,
            sslmode=payload.sslmode,
            is_active=False,
            created_at="",
            updated_at="",
        )
        db = DatabaseManager(temp_profile)
        success, msg = db.test_connection()
        return {"success": success, "message": msg}

    return app


app = create_app()


def main():
    """Runs the local web configuration server on localhost:8000."""
    uvicorn.run("src.web:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
