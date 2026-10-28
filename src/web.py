"""Local Web Configuration UI for PostgreSQL MCP Server."""

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from src.database import DatabaseManager, close_all_pools
from src.credentials import CredentialStoreError
from src.storage import Profile, ProfileCreate, ProfileStorage, ProfileUpdate, PublicProfile

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize profile storage at startup and release pools at shutdown."""
    try:
        if app.state.storage is None:
            app.state.storage = ProfileStorage()
        yield
    finally:
        close_all_pools()


def create_app(storage: Optional[ProfileStorage] = None) -> FastAPI:
    """Creates the FastAPI configuration app."""
    app = FastAPI(title="PgPrism Configuration", lifespan=lifespan)
    app.state.storage = storage

    def get_storage() -> ProfileStorage:
        return app.state.storage

    @app.exception_handler(CredentialStoreError)
    async def credential_store_error(_request, error: CredentialStoreError):
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(error)})

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(_request, error: RequestValidationError):
        # Even a missing unrelated field can include the entire body in "input".
        # Return only validation metadata, never raw inputs or exception context.
        details = [
            {key: item[key] for key in ("type", "loc", "msg")}
            for item in error.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": details})

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
        cli_command = repo_root / ".venv" / "bin" / "pgprism"
        if not cli_command.exists():
            cli_command = repo_root / ".venv" / "bin" / "mcp-postgresql"
        active = get_storage().get_active_profile()
        return {
            "project_root": str(repo_root),
            "python_executable": python_exec,
            "cli_command": str(cli_command) if cli_command.exists() else "pgprism",
            "server_module": "src.server",
            "active_profile": active.name if active else None,
            "active_database": active.database if active else None,
        }

    @app.get("/api/profiles", response_model=List[PublicProfile])
    def list_profiles(q: Optional[str] = None):
        if q and q.strip():
            return get_storage().search_profiles(q.strip())
        return get_storage().list_profiles()

    @app.post("/api/profiles", response_model=PublicProfile, status_code=status.HTTP_201_CREATED)
    def create_profile(payload: ProfileCreate):
        store = get_storage()
        existing = store.get_profile_by_name(payload.name)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Profile with name '{payload.name}' already exists.",
            )
        return store.save_profile(payload)

    @app.get("/api/profiles/{profile_id}", response_model=PublicProfile)
    def get_profile(profile_id: int):
        profile = get_storage().get_profile(profile_id)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile with id {profile_id} not found.",
            )
        return profile

    @app.patch("/api/profiles/{profile_id}", response_model=PublicProfile)
    def update_profile(profile_id: int, payload: ProfileUpdate):
        store = get_storage()
        if payload.name is not None:
            existing = store.get_profile_by_name(payload.name)
            if existing and existing.id != profile_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Profile with name '{payload.name}' already exists.",
                )
        updated = store.partial_update_profile(profile_id, payload)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile with id {profile_id} not found.",
            )
        return updated

    @app.post("/api/profiles/{profile_id}/activate", response_model=PublicProfile)
    def activate_profile(profile_id: int):
        profile = get_storage().set_active_profile(profile_id)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile with id {profile_id} not found.",
            )
        return profile

    @app.delete("/api/profiles/{profile_id}")
    def delete_profile(profile_id: int):
        success = get_storage().delete_profile(profile_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile with id {profile_id} not found.",
            )
        return {"success": True}

    @app.get("/api/profiles/{profile_id}/databases", response_model=List[str])
    def list_profile_databases(profile_id: int):
        profile = get_storage().get_profile(profile_id)
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
