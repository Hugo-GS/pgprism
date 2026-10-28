"""Run only inside an isolated desktop secret-service session, never a real keychain."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from src.credentials import OSCredentialStore
from src.storage import ProfileCreate, ProfileStorage


def main():
    sandbox = Path(os.environ["PGPRISM_TEST_SANDBOX"]).resolve()
    assert Path(os.environ["HOME"]).resolve() == sandbox
    assert Path(os.environ["XDG_DATA_HOME"]).resolve().is_relative_to(sandbox)
    path = Path(os.environ["PGPRISM_DB_PATH"]).resolve()
    assert path.is_relative_to(sandbox)
    store = OSCredentialStore()
    reference = uuid4().hex
    password = "native-smoke-not-a-real-password"
    store.set(reference, password)
    assert store.get(reference) == password
    store.delete(reference)
    assert store.get(reference) is None

    profiles = ProfileStorage(path)
    profile = profiles.save_profile(
        ProfileCreate(name="native", username="reader", password=password)
    )
    assert password.encode() not in path.read_bytes()
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.storage import ProfileStorage; "
            "assert ProfileStorage().get_active_profile().password "
            "== 'native-smoke-not-a-real-password'",
        ],
        check=True,
    )
    updated = profiles.update_profile(
        profile.id, ProfileCreate(name="native", username="reader", password="native-rotated")
    )
    assert updated is not None
    assert updated.password == "native-rotated"
    stored = profiles.get_profile(profile.id)
    assert stored is not None
    assert stored.password == "native-rotated"
    assert profiles.delete_profile(profile.id)
    assert profiles.list_profiles() == []

    # Simulate a pre-upgrade row in the isolated database, never user data.
    legacy = profiles.save_profile(ProfileCreate(name="legacy", username="reader"))
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE profiles SET password = ? WHERE id = ?", ("native-legacy-marker", legacy.id)
        )
    migrated = ProfileStorage(path)
    migrated_profile = migrated.get_active_profile()
    assert migrated_profile is not None
    assert migrated_profile.password == "native-legacy-marker"
    assert b"native-legacy-marker" not in path.read_bytes()
    assert migrated.delete_profile(legacy.id)
    print(
        "PASS: native OS keyring CRUD, cross-process access, "
        "profile rotation, deletion and migration"
    )


if __name__ == "__main__":
    main()
