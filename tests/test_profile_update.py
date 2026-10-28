"""Tests for partial profile update (GET + PATCH endpoints and storage layer)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from src.storage import ProfileCreate, ProfileStorage, ProfileUpdate
from src.web import create_app

# ---------------------------------------------------------------------------
# Storage-layer tests
# ---------------------------------------------------------------------------


class MemorySecrets:
    def __init__(self):
        self.passwords = {}

    def get(self, reference):
        return self.passwords.get(reference)

    def set(self, reference, password):
        self.passwords[reference] = password

    def delete(self, reference):
        self.passwords.pop(reference, None)


@pytest.fixture
def secrets():
    return MemorySecrets()


@pytest.fixture
def storage(tmp_path: Path, secrets):
    return ProfileStorage(tmp_path / "profiles.db", credential_store=secrets)


def test_partial_update_name_only(storage: ProfileStorage):
    saved = storage.save_profile(ProfileCreate(name="old", username="reader", password="secret"))
    updated = storage.partial_update_profile(saved.id, ProfileUpdate(name="new"))
    assert updated is not None
    assert updated.name == "new"
    assert updated.host == saved.host
    assert updated.port == saved.port
    assert updated.database == saved.database
    assert updated.username == saved.username
    assert updated.password == "secret"


def test_partial_update_host_and_port(storage: ProfileStorage):
    saved = storage.save_profile(ProfileCreate(name="dev", username="reader"))
    updated = storage.partial_update_profile(saved.id, ProfileUpdate(host="db.internal", port=5433))
    assert updated is not None
    assert updated.host == "db.internal"
    assert updated.port == 5433
    assert updated.name == "dev"


def test_partial_update_password_replaces_old(storage: ProfileStorage, secrets: MemorySecrets):
    saved = storage.save_profile(ProfileCreate(name="dev", username="reader", password="old-pass"))
    assert len(secrets.passwords) == 1
    updated = storage.partial_update_profile(saved.id, ProfileUpdate(password="new-pass"))
    assert updated is not None
    assert updated.password == "new-pass"
    assert len(secrets.passwords) == 1
    assert "old-pass" not in secrets.passwords.values()


def test_partial_update_password_to_empty_clears(storage: ProfileStorage, secrets: MemorySecrets):
    saved = storage.save_profile(ProfileCreate(name="dev", username="reader", password="secret"))
    updated = storage.partial_update_profile(saved.id, ProfileUpdate(password=""))
    assert updated is not None
    assert updated.password == ""
    assert secrets.passwords == {}


def test_partial_update_without_password_keeps_existing(
    storage: ProfileStorage, secrets: MemorySecrets
):
    saved = storage.save_profile(ProfileCreate(name="dev", username="reader", password="keep-me"))
    snapshot = dict(secrets.passwords)
    updated = storage.partial_update_profile(saved.id, ProfileUpdate(name="renamed"))
    assert updated is not None
    assert updated.password == "keep-me"
    assert secrets.passwords == snapshot


def test_partial_update_nonexistent_returns_none(storage: ProfileStorage):
    result = storage.partial_update_profile(999, ProfileUpdate(name="ghost"))
    assert result is None


def test_partial_update_preserves_is_active(storage: ProfileStorage):
    p1 = storage.save_profile(ProfileCreate(name="first", username="reader"))
    p2 = storage.save_profile(ProfileCreate(name="second", username="reader"))
    assert p1.is_active is True
    assert p2.is_active is False
    updated = storage.partial_update_profile(p1.id, ProfileUpdate(host="new-host"))
    assert updated is not None
    assert updated.is_active is True


def test_partial_update_empty_patch_is_noop(storage: ProfileStorage):
    saved = storage.save_profile(ProfileCreate(name="stable", username="reader"))
    updated = storage.partial_update_profile(saved.id, ProfileUpdate())
    assert updated is not None
    assert updated == saved


# ---------------------------------------------------------------------------
# HTTP-layer tests
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    storage = ProfileStorage(db_path=tmp_path / "web.db")
    app = create_app(storage=storage)
    with TestClient(app) as c:
        yield c


def _create(client: TestClient, **overrides) -> dict:
    payload = {
        "name": "test-profile",
        "host": "localhost",
        "port": 5432,
        "database": "testdb",
        "username": "reader",
        "password": "original",
        **overrides,
    }
    res = client.post("/api/profiles", json=payload)
    assert res.status_code == 201
    return res.json()


def test_get_profile_returns_data_without_password(client: TestClient):
    created = _create(client)
    res = client.get(f"/api/profiles/{created['id']}")
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "test-profile"
    assert data["host"] == "localhost"
    assert data["port"] == 5432
    assert data["database"] == "testdb"
    assert data["username"] == "reader"
    assert "password" not in data
    assert "credential_id" not in data
    assert "original" not in res.text


def test_get_profile_not_found(client: TestClient):
    res = client.get("/api/profiles/9999")
    assert res.status_code == 404


def test_patch_updates_name(client: TestClient):
    created = _create(client)
    res = client.patch(f"/api/profiles/{created['id']}", json={"name": "renamed"})
    assert res.status_code == 200
    assert res.json()["name"] == "renamed"
    assert "password" not in res.json()


def test_patch_updates_host_and_port(client: TestClient):
    created = _create(client)
    res = client.patch(f"/api/profiles/{created['id']}", json={"host": "db.prod", "port": 5433})
    assert res.status_code == 200
    data = res.json()
    assert data["host"] == "db.prod"
    assert data["port"] == 5433
    assert data["name"] == "test-profile"


def test_patch_assigns_new_password_without_returning_it(client: TestClient):
    created = _create(client)
    res = client.patch(f"/api/profiles/{created['id']}", json={"password": "new-secret"})
    assert res.status_code == 200
    assert "new-secret" not in res.text
    assert "password" not in res.json()


def test_patch_clears_password(client: TestClient):
    created = _create(client)
    res = client.patch(f"/api/profiles/{created['id']}", json={"password": ""})
    assert res.status_code == 200


def test_patch_not_found(client: TestClient):
    res = client.patch("/api/profiles/9999", json={"name": "ghost"})
    assert res.status_code == 404


def test_patch_duplicate_name_conflict(client: TestClient):
    _create(client, name="profile-a")
    b = _create(client, name="profile-b")
    res = client.patch(f"/api/profiles/{b['id']}", json={"name": "profile-a"})
    assert res.status_code == 409


def test_patch_same_name_no_conflict(client: TestClient):
    created = _create(client, name="keep-name")
    res = client.patch(f"/api/profiles/{created['id']}", json={"name": "keep-name", "port": 5433})
    assert res.status_code == 200
    assert res.json()["port"] == 5433


def test_patch_password_never_retrievable_via_get(client: TestClient):
    created = _create(client, password="secret-password")
    get_res = client.get(f"/api/profiles/{created['id']}")
    assert "secret-password" not in get_res.text

    client.patch(f"/api/profiles/{created['id']}", json={"password": "updated-secret"})
    get_res2 = client.get(f"/api/profiles/{created['id']}")
    assert "updated-secret" not in get_res2.text

    list_res = client.get("/api/profiles")
    assert "updated-secret" not in list_res.text
