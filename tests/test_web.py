import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from src.storage import ProfileStorage
from src.web import create_app


@pytest.fixture
def test_client(tmp_path: Path) -> Iterator[TestClient]:
    db_path = tmp_path / "web_profiles.db"
    storage = ProfileStorage(db_path=db_path)
    app = create_app(storage=storage)
    with TestClient(app) as client:
        yield client


def test_index_page_loads(test_client: TestClient):
    response = test_client.get("/")
    assert response.status_code == 200
    assert "PgPrism" in response.text
    assert "/static/tokens.css" in response.text
    assert "/static/components.css" in response.text
    assert "/static/style.css" in response.text
    assert "/static/app.js" in response.text
    assert "Connection Guide" in response.text
    assert "MCP Reference" in response.text
    assert "Strict Read-Only Defense in Depth" in response.text


def test_static_assets_serve(test_client: TestClient):
    tokens_res = test_client.get("/static/tokens.css")
    assert tokens_res.status_code == 200
    assert "--fc-canvas:" in tokens_res.text
    assert ":root[data-theme='light']" in tokens_res.text

    components_res = test_client.get("/static/components.css")
    assert components_res.status_code == 200
    assert ".fc-panel" in components_res.text
    assert ".fc-table" in components_res.text

    css_res = test_client.get("/static/style.css")
    assert css_res.status_code == 200
    assert "var(--fc-" in css_res.text

    js_res = test_client.get("/static/app.js")
    assert js_res.status_code == 200
    assert "loadProfiles" in js_res.text
    assert "switchTab" in js_res.text
    assert "copySnippet" in js_res.text
    assert "openSettingsModal" in js_res.text
    assert "closeSettingsModal" in js_res.text


def test_index_page_contains_settings_modal(test_client: TestClient):
    response = test_client.get("/")
    assert response.status_code == 200
    assert 'id="settingsModal"' in response.text
    assert 'id="settingsProfileForm"' in response.text
    assert "Connection Settings" in response.text
    assert "Danger Zone" in response.text


def test_create_and_list_profiles_api(test_client: TestClient):
    # List is empty initially
    res = test_client.get("/api/profiles")
    assert res.status_code == 200
    assert res.json() == []

    # Create profile
    payload = {
        "name": "dev-pg",
        "host": "localhost",
        "port": 5432,
        "database": "postgres",
        "username": "postgres",
        "password": "secret",
        "sslmode": "prefer",
    }
    create_res = test_client.post("/api/profiles", json=payload)
    assert create_res.status_code == 201
    created = create_res.json()
    assert created["name"] == "dev-pg"
    assert created["is_active"] is True

    # List now returns the created profile
    res2 = test_client.get("/api/profiles")
    assert len(res2.json()) == 1


def test_activate_profile_api(test_client: TestClient):
    # Create two profiles
    test_client.post(
        "/api/profiles",
        json={"name": "p1", "database": "db1", "username": "u1"},
    ).json()
    p2 = test_client.post(
        "/api/profiles",
        json={"name": "p2", "database": "db2", "username": "u2"},
    ).json()

    # Activate p2
    act_res = test_client.post(f"/api/profiles/{p2['id']}/activate")
    assert act_res.status_code == 200
    assert act_res.json()["is_active"] is True


def test_delete_profile_api(test_client: TestClient):
    p = test_client.post(
        "/api/profiles",
        json={"name": "temp-db", "database": "db", "username": "u"},
    ).json()

    del_res = test_client.delete(f"/api/profiles/{p['id']}")
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    # Not found when deleting again
    del_res2 = test_client.delete(f"/api/profiles/{p['id']}")
    assert del_res2.status_code == 404


def test_create_profile_without_database_defaults_to_postgres(test_client: TestClient):
    payload = {
        "name": "cluster-default",
        "username": "admin",
    }
    res = test_client.post("/api/profiles", json=payload)
    assert res.status_code == 201
    assert res.json()["database"] == "postgres"


def test_create_profile_with_custom_timeout(test_client: TestClient):
    """Test that profiles can be created with a custom statement timeout."""
    response = test_client.post(
        "/api/profiles",
        json={
            "name": "timeout-test",
            "host": "localhost",
            "port": 5432,
            "database": "testdb",
            "username": "user",
            "password": "pass",
            "statement_timeout_ms": 60000,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["statement_timeout_ms"] == 60000


def test_get_info_endpoint(test_client: TestClient):
    """Test that /api/info returns project environment details."""
    response = test_client.get("/api/info")
    assert response.status_code == 200
    data = response.json()
    assert "project_root" in data
    assert "python_executable" in data
    assert "cli_command" in data
    assert data["server_module"] == "src.server"
    assert data["active_profile"] is None


def test_get_info_with_active_profile(test_client: TestClient):
    """Test that /api/info returns active profile information when configured."""
    test_client.post(
        "/api/profiles",
        json={
            "name": "prod-read",
            "host": "db.internal",
            "port": 5432,
            "database": "analytics",
            "username": "readonly_user",
        },
    )
    response = test_client.get("/api/info")
    assert response.status_code == 200
    data = response.json()
    assert data["active_profile"] == "prod-read"
    assert data["active_database"] == "analytics"


def test_search_profiles_api(test_client: TestClient):
    """Test searching profiles via /api/profiles?q=..."""
    test_client.post(
        "/api/profiles",
        json={"name": "finance-dw", "host": "fin.internal", "database": "ledger", "username": "pg"},
    )
    test_client.post(
        "/api/profiles",
        json={
            "name": "marketing-dw",
            "host": "mkt.internal",
            "database": "leads",
            "username": "pg",
        },
    )

    # Search by q=dw
    res = test_client.get("/api/profiles?q=dw")
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 2

    # Search by q=ledger
    res = test_client.get("/api/profiles?q=ledger")
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 1
    assert items[0]["name"] == "finance-dw"

    # Search with no match
    res = test_client.get("/api/profiles?q=nonexistent")
    assert res.status_code == 200
    assert res.json() == []


def test_ui_explain_viewer_endpoint(test_client: TestClient):
    """Test that /ui/explain-viewer serves the self-contained execution plan component."""
    response = test_client.get("/ui/explain-viewer")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "<!DOCTYPE html>" in response.text
    assert "PostgreSQL Execution Plan" in response.text
    assert "postMessage" in response.text


def test_ui_data_grid_endpoint(test_client: TestClient):
    """Test that /ui/data-grid serves the self-contained data grid component."""
    response = test_client.get("/ui/data-grid")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "<!DOCTYPE html>" in response.text
    assert "Query Results" in response.text
    assert "postMessage" in response.text


def test_import_does_not_initialize_profile_storage(tmp_path: Path):
    db_path = tmp_path / "import.db"
    script = """
from unittest.mock import patch

storage_error = AssertionError("storage opened during import")
with patch("src.storage.ProfileStorage", side_effect=storage_error) as constructor, \
     patch("sqlite3.connect", side_effect=AssertionError("SQLite opened during import")), \
     patch("keyring.get_keyring", side_effect=AssertionError("keyring accessed during import")):
    import src.web
    constructor.assert_not_called()
    src.web.create_app()
    constructor.assert_not_called()
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "PGPRISM_DB_PATH": str(db_path)},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
    assert not db_path.exists()


def test_lifespan_closes_pools_on_shutdown(tmp_path: Path):
    db_path = tmp_path / "lifespan.db"
    with (
        patch(
            "src.web.ProfileStorage", side_effect=lambda: ProfileStorage(db_path=db_path)
        ) as constructor,
        patch("src.web.close_all_pools") as mock_close,
    ):
        app = create_app()
        constructor.assert_not_called()
        assert not db_path.exists()
        with TestClient(app) as client:
            constructor.assert_called_once_with()
            assert db_path.is_file()
            mock_close.assert_not_called()
            created = client.post("/api/profiles", json={"name": "startup", "username": "reader"})
            assert created.status_code == 201
            assert client.get("/api/profiles").json() == [created.json()]
            assert client.get("/api/info").json()["active_profile"] == "startup"
            constructor.assert_called_once_with()
        mock_close.assert_called_once_with()


def test_lifespan_uses_injected_storage_without_constructing_another(tmp_path: Path):
    storage = ProfileStorage(db_path=tmp_path / "injected.db")
    with patch(
        "src.web.ProfileStorage", side_effect=AssertionError("unexpected default storage")
    ) as constructor:
        app = create_app(storage=storage)
        constructor.assert_not_called()
        with TestClient(app) as client:
            created = client.post("/api/profiles", json={"name": "injected", "username": "reader"})
            assert created.status_code == 201
            assert client.get("/api/profiles").json() == [created.json()]
            active = storage.get_active_profile()
            assert active is not None
            assert active.name == "injected"
        constructor.assert_not_called()
