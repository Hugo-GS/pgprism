from pathlib import Path
import pytest
from src.storage import ProfileCreate, ProfileStorage


@pytest.fixture
def temp_storage(tmp_path: Path) -> ProfileStorage:
    db_file = tmp_path / "test_profiles.db"
    return ProfileStorage(db_path=db_file)


def test_initial_state_empty(temp_storage: ProfileStorage):
    assert temp_storage.list_profiles() == []
    assert temp_storage.get_active_profile() is None


def test_create_and_get_profile(temp_storage: ProfileStorage):
    new_profile = ProfileCreate(
        name="local-db",
        host="localhost",
        port=5432,
        database="test_db",
        username="postgres",
        password="secretpassword",
        sslmode="disable",
    )
    saved = temp_storage.save_profile(new_profile)
    assert saved.id is not None
    assert saved.name == "local-db"
    assert saved.database == "test_db"
    assert saved.is_active is True  # First profile becomes active automatically

    retrieved = temp_storage.get_profile(saved.id)
    assert retrieved is not None
    assert retrieved.name == "local-db"
    assert retrieved.password == "secretpassword"


def test_set_active_profile(temp_storage: ProfileStorage):
    p1 = temp_storage.save_profile(
        ProfileCreate(name="db-one", database="db1", username="user1")
    )
    p2 = temp_storage.save_profile(
        ProfileCreate(name="db-two", database="db2", username="user2")
    )

    # p1 was initially active
    assert temp_storage.get_active_profile().id == p1.id

    # Switch active to p2
    temp_storage.set_active_profile(p2.id)
    active = temp_storage.get_active_profile()
    assert active is not None
    assert active.id == p2.id
    assert active.name == "db-two"

    # Verify p1 is no longer active
    p1_refreshed = temp_storage.get_profile(p1.id)
    assert p1_refreshed.is_active is False


def test_delete_profile(temp_storage: ProfileStorage):
    p1 = temp_storage.save_profile(
        ProfileCreate(name="to-delete", database="db", username="u")
    )
    assert temp_storage.delete_profile(p1.id) is True
    assert temp_storage.get_profile(p1.id) is None
    assert temp_storage.delete_profile(9999) is False


def test_update_existing_profile(temp_storage: ProfileStorage):
    p = temp_storage.save_profile(
        ProfileCreate(name="prod-replica", database="prod", username="reader")
    )
    update_data = ProfileCreate(
        name="prod-replica",
        host="replica.internal",
        port=5433,
        database="prod",
        username="reader_v2",
        password="newpassword",
    )
    updated = temp_storage.update_profile(p.id, update_data)
    assert updated is not None
    assert updated.host == "replica.internal"
    assert updated.port == 5433
    assert updated.username == "reader_v2"
    assert updated.password == "newpassword"


def test_database_field_optional_defaults_to_postgres(temp_storage: ProfileStorage):
    # Omitted database
    p1 = temp_storage.save_profile(
        ProfileCreate(name="no-db", username="postgres")
    )
    assert p1.database == "postgres"

    # Empty string database
    p2 = temp_storage.save_profile(
        ProfileCreate(name="empty-db", database="", username="postgres")
    )
    assert p2.database == "postgres"

