"""Credential privacy at the public HTTP boundary."""

from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from src.storage import ProfileStorage
from src.web import create_app


def test_profile_responses_never_return_password(tmp_path: Path):
    storage = ProfileStorage(tmp_path / "web.db")
    with TestClient(create_app(storage)) as client:
        response = client.post(
            "/api/profiles",
            json={
                "name": "private",
                "username": "reader",
                "password": "http-secret-marker",
            },
        )
        assert response.status_code == 201
        profile_id = response.json()["id"]
        for result in [
            response,
            client.get("/api/profiles"),
            client.get("/api/profiles?q=private"),
            client.post(f"/api/profiles/{profile_id}/activate"),
        ]:
            assert result.status_code in (200, 201)
            assert "http-secret-marker" not in result.text
            profiles = result.json() if isinstance(result.json(), list) else [result.json()]
            assert len(profiles) == 1
            assert profiles[0]["id"] == profile_id
            assert all(
                "password" not in profile and "credential_id" not in profile for profile in profiles
            )
        stored = storage.get_profile(profile_id)
        assert stored is not None
        assert stored.password == "http-secret-marker"
        with patch("src.web.DatabaseManager") as manager:
            manager.return_value.list_databases.return_value = ["postgres"]
            assert client.get(f"/api/profiles/{profile_id}/databases").json() == ["postgres"]
            assert manager.call_args.args[0].password == "http-secret-marker"


def test_keyring_failure_is_service_unavailable_without_changes(tmp_path: Path):
    from src.credentials import CredentialStoreError

    storage = ProfileStorage(tmp_path / "web.db")
    with TestClient(create_app(storage)) as client:
        with patch.object(
            storage.credential_store,
            "set",
            side_effect=CredentialStoreError("OS credential store is unavailable or locked."),
        ):
            result = client.post(
                "/api/profiles",
                json={
                    "name": "rejected",
                    "username": "reader",
                    "password": "rejected-http-secret",
                },
            )
        assert result.status_code == 503
        assert result.json() == {"detail": "OS credential store is unavailable or locked."}
        assert client.get("/api/profiles").json() == []
