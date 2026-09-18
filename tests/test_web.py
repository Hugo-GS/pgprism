from pathlib import Path
import pytest
from starlette.testclient import TestClient
from src.storage import ProfileStorage
from src.web import create_app


@pytest.fixture
def test_client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "web_profiles.db"
    storage = ProfileStorage(db_path=db_path)
    app = create_app(storage=storage)
    return TestClient(app)


def test_index_page_loads(test_client: TestClient):
    response = test_client.get("/")
    assert response.status_code == 200
    assert "MCP PostgreSQL" in response.text


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
    p1 = test_client.post(
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

