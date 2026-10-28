"""Public storage behavior and on-disk secrecy, using only isolated profiles."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from src.credentials import CredentialStoreError
from src.storage import ProfileCreate, ProfileStorage


class MemorySecrets:
    def __init__(self):
        self.passwords = {}
        self.fail = False
        self.fail_delete = False

    def get(self, reference):
        if self.fail:
            raise CredentialStoreError("OS credential store is unavailable or locked.")
        return self.passwords.get(reference)

    def set(self, reference, password):
        if self.fail:
            raise CredentialStoreError("OS credential store is unavailable or locked.")
        self.passwords[reference] = password

    def delete(self, reference):
        if self.fail:
            raise CredentialStoreError("OS credential store is unavailable or locked.")
        if self.fail_delete:
            raise CredentialStoreError("Credential deletion failed.")
        self.passwords.pop(reference, None)


def test_saved_password_is_not_in_sqlite(tmp_path: Path):
    path = tmp_path / "profiles.db"
    storage = ProfileStorage(path)
    password = "unique-at-rest-secret-123"
    storage.save_profile(ProfileCreate(name="local", username="reader", password=password))
    assert password.encode() not in path.read_bytes()


def test_secret_lifecycle_and_reopen(tmp_path: Path):
    secrets = MemorySecrets()
    path = tmp_path / "profiles.db"
    storage = ProfileStorage(path, credential_store=secrets)
    saved = storage.save_profile(
        ProfileCreate(name="dev", username="reader", password="first-secret")
    )
    assert list(secrets.passwords.values()) == ["first-secret"]
    reopened = ProfileStorage(path, credential_store=secrets)
    active = reopened.get_active_profile()
    assert active is not None
    assert active.password == "first-secret"
    reopened.update_profile(
        saved.id, ProfileCreate(name="renamed", username="reader", password="second-secret")
    )
    assert reopened.search_profiles("renamed")[0].password == "second-secret"
    renamed = reopened.get_profile_by_name("renamed")
    assert renamed is not None
    assert renamed.password == "second-secret"
    assert list(secrets.passwords.values()) == ["second-secret"]
    assert b"first-secret" not in path.read_bytes()
    assert b"second-secret" not in path.read_bytes()
    assert reopened.delete_profile(saved.id)
    assert secrets.passwords == {}


def test_unavailable_store_rejects_save_without_changes(tmp_path: Path):
    secrets = MemorySecrets()
    storage = ProfileStorage(tmp_path / "profiles.db", credential_store=secrets)
    secrets.fail = True
    with pytest.raises(CredentialStoreError):
        storage.save_profile(
            ProfileCreate(name="rejected", username="reader", password="never-persist")
        )
    secrets.fail = False
    assert storage.list_profiles() == []
    assert secrets.passwords == {}
    saved = storage.save_profile(ProfileCreate(name="accepted", username="reader", password="ok"))
    assert saved.id == 1
    assert saved.is_active is True


def test_failed_update_and_delete_preserve_profile(tmp_path: Path):
    secrets = MemorySecrets()
    storage = ProfileStorage(tmp_path / "profiles.db", credential_store=secrets)
    saved = storage.save_profile(
        ProfileCreate(name="original", username="reader", password="original-secret")
    )
    snapshot = dict(secrets.passwords)
    secrets.fail = True
    with pytest.raises(CredentialStoreError):
        storage.update_profile(
            saved.id, ProfileCreate(name="changed", username="other", password="new")
        )
    secrets.fail = False
    secrets.fail_delete = True
    with pytest.raises(CredentialStoreError, match="Credential deletion failed"):
        storage.delete_profile(saved.id)
    secrets.fail_delete = False
    assert storage.get_profile(saved.id) == saved
    assert secrets.passwords == snapshot


def test_missing_secret_does_not_become_empty_password(tmp_path: Path):
    secrets = MemorySecrets()
    storage = ProfileStorage(tmp_path / "profiles.db", credential_store=secrets)
    saved = storage.save_profile(ProfileCreate(name="dev", username="reader", password="secret"))
    secrets.passwords.clear()
    with pytest.raises(CredentialStoreError, match="missing"):
        storage.get_profile(saved.id)


def test_password_can_be_cleared_without_losing_profile(tmp_path: Path):
    secrets = MemorySecrets()
    storage = ProfileStorage(tmp_path / "profiles.db", credential_store=secrets)
    saved = storage.save_profile(ProfileCreate(name="dev", username="reader", password="secret"))
    storage.update_profile(saved.id, ProfileCreate(name="dev", username="reader"))
    cleared = storage.get_profile(saved.id)
    assert cleared is not None
    assert cleared.password == ""
    assert secrets.passwords == {}


def test_duplicate_name_rolls_back_metadata_and_new_secret(tmp_path: Path):
    secrets = MemorySecrets()
    storage = ProfileStorage(tmp_path / "profiles.db", credential_store=secrets)
    saved = storage.save_profile(ProfileCreate(name="dev", username="reader", password="original"))
    snapshot = dict(secrets.passwords)
    with pytest.raises(sqlite3.IntegrityError):
        storage.save_profile(ProfileCreate(name="dev", username="other", password="rejected"))
    assert storage.list_profiles() == [saved]
    assert secrets.passwords == snapshot
    other = storage.save_profile(ProfileCreate(name="other", username="reader", password="other"))
    snapshot = dict(secrets.passwords)
    with pytest.raises(sqlite3.IntegrityError):
        storage.update_profile(
            other.id, ProfileCreate(name="dev", username="changed", password="rejected-update")
        )
    assert storage.get_profile(other.id) == other
    assert secrets.passwords == snapshot
    assert other.id == saved.id + 1


def test_distinct_databases_do_not_collide(tmp_path: Path):
    secrets = MemorySecrets()
    a = ProfileStorage(tmp_path / "a.db", credential_store=secrets)
    b = ProfileStorage(tmp_path / "b.db", credential_store=secrets)
    pa = a.save_profile(ProfileCreate(name="same", username="same", password="a-password"))
    pb = b.save_profile(ProfileCreate(name="same", username="same", password="b-password"))
    stored_a = a.get_profile(pa.id)
    stored_b = b.get_profile(pb.id)
    assert stored_a is not None
    assert stored_b is not None
    assert stored_a.password == "a-password"
    assert stored_b.password == "b-password"
    assert len(secrets.passwords) == 2


def make_legacy_database(path: Path):
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("""CREATE TABLE profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
            host TEXT NOT NULL, port INTEGER NOT NULL, database TEXT NOT NULL,
            username TEXT NOT NULL, password TEXT NOT NULL DEFAULT '',
            sslmode TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        conn.execute("""INSERT INTO profiles VALUES
            (1, 'legacy', 'localhost', 5432, 'postgres', 'reader',
             'legacy-secret-marker', 'prefer', 1, 'created', 'updated')""")


def test_legacy_password_migrates_without_changing_profile(tmp_path: Path):
    path = tmp_path / "legacy.db"
    make_legacy_database(path)
    secrets = MemorySecrets()
    storage = ProfileStorage(path, credential_store=secrets)
    profile = storage.get_active_profile()
    assert profile is not None
    assert profile.id == 1
    assert profile.name == "legacy"
    assert profile.password == "legacy-secret-marker"
    assert profile.statement_timeout_ms == 30000
    assert profile.created_at == "created"
    assert list(secrets.passwords.values()) == ["legacy-secret-marker"]
    assert b"legacy-secret-marker" not in path.read_bytes()
    assert ProfileStorage(path, credential_store=secrets).get_profile(1) == profile
    assert len(secrets.passwords) == 1


def test_failed_migration_on_first_secret_write_preserves_original_password(tmp_path: Path):
    path = tmp_path / "legacy.db"
    make_legacy_database(path)
    secrets = MemorySecrets()
    secrets.fail = True
    with pytest.raises(CredentialStoreError):
        ProfileStorage(path, credential_store=secrets)
    secrets.fail = False
    migrated = ProfileStorage(path, credential_store=secrets).get_profile(1)
    assert migrated is not None
    assert migrated.password == "legacy-secret-marker"
    assert list(secrets.passwords.values()) == ["legacy-secret-marker"]
