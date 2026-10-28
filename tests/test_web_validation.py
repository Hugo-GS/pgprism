"""Invalid HTTP requests must not reflect credentials or change saved profiles."""

from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from src.storage import ProfileStorage
from src.web import create_app

SECRET = "validation-secret-marker"


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(ProfileStorage(tmp_path / "validation.db"))) as client:
        yield client


@pytest.fixture
def unchanged_profiles(client, memory_keyring):
    saved = client.post(
        "/api/profiles",
        json={
            "name": "existing",
            "username": "reader",
            "password": "stored-secret",
        },
    )
    assert saved.status_code == 201
    before = client.get("/api/profiles").json()
    assert before == [saved.json()]
    secrets_before = dict(memory_keyring.passwords)
    assert secrets_before
    with patch("src.web.DatabaseManager") as manager:
        yield
        manager.assert_not_called()
    assert client.get("/api/profiles").json() == before
    assert memory_keyring.passwords == secrets_before
    next_profile = client.post("/api/profiles", json={"name": "next", "username": "reader"})
    assert next_profile.status_code == 201
    assert next_profile.json()["id"] == saved.json()["id"] + 1
    assert next_profile.json()["is_active"] is False


def assert_validation_metadata(response, error_type, location):
    assert response.status_code == 422
    assert SECRET not in response.text
    payload = response.json()
    assert set(payload) == {"detail"}
    assert len(payload["detail"]) == 1
    error = payload["detail"][0]
    assert set(error) == {"type", "loc", "msg"}
    assert error["type"] == error_type
    assert isinstance(error["msg"], str) and error["msg"].strip()
    assert len(error["loc"]) == 2
    assert error["loc"][: len(location)] == location
    return error


@pytest.mark.parametrize("endpoint", ["/api/profiles", "/api/profiles/test"])
def test_missing_field_does_not_reflect_password(client, unchanged_profiles, endpoint):
    response = client.post(endpoint, json={"name": "invalid", "password": SECRET})
    assert_validation_metadata(response, "missing", ["body", "username"])


@pytest.mark.parametrize(
    "fields, error_type, location",
    [
        ({"password": {"nested": SECRET}}, "string_type", ["body", "password"]),
        ({"password": SECRET, "port": 0}, "greater_than_equal", ["body", "port"]),
    ],
)
def test_invalid_profile_returns_only_validation_metadata(
    client, unchanged_profiles, fields, error_type, location
):
    response = client.post(
        "/api/profiles", json={"name": "invalid", "username": "reader", **fields}
    )
    assert_validation_metadata(response, error_type, location)


def test_malformed_json_does_not_reflect_body(client, unchanged_profiles):
    body = '{"name":"invalid","password":"' + SECRET + '",'
    response = client.post(
        "/api/profiles/test", content=body, headers={"Content-Type": "application/json"}
    )
    error = assert_validation_metadata(response, "json_invalid", ["body"])
    assert isinstance(error["loc"][1], int)


def test_invalid_profile_id_keeps_422_without_reflecting_input(client, unchanged_profiles):
    response = client.delete(f"/api/profiles/{SECRET}")
    assert_validation_metadata(response, "int_parsing", ["path", "profile_id"])


def test_valid_connection_test_still_receives_password(client, memory_keyring):
    with patch("src.web.DatabaseManager") as manager:
        manager.return_value.test_connection.return_value = (True, "PostgreSQL test version")
        response = client.post(
            "/api/profiles/test",
            json={
                "name": "valid",
                "username": "reader",
                "password": SECRET,
            },
        )
        assert manager.call_args.args[0].password == SECRET
        manager.return_value.test_connection.assert_called_once_with()
    assert response.status_code == 200
    assert response.json() == {"success": True, "message": "PostgreSQL test version"}
    assert SECRET not in response.text
    assert client.get("/api/profiles").json() == []
    assert memory_keyring.passwords == {}
