"""Keep collection, profile tests, and keyring calls off real user data."""

import pytest

_environment = pytest.MonkeyPatch()


def pytest_configure(config):
    sandbox = config.cache.mkdir("credential-tests")
    _environment.setenv("PGPRISM_DB_PATH", str(sandbox / "import-only.db"))
    _environment.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.fail.Keyring")
    for name in (
        "DATABASE_URL",
        "POSTGRES_URL",
        "PGHOST",
        "PGPORT",
        "PGDATABASE",
        "PGUSER",
        "PGPASSWORD",
        "PGSSLMODE",
        "MCP_POSTGRES_DB_PATH",
    ):
        _environment.delenv(name, raising=False)


def pytest_unconfigure(config):
    _environment.undo()


class MemoryKeyring:
    def __init__(self):
        self.passwords = {}

    def get_password(self, service, username):
        return self.passwords.get((service, username))

    def set_password(self, service, username, password):
        self.passwords[service, username] = password

    def delete_password(self, service, username):
        self.passwords.pop((service, username), None)


@pytest.fixture
def memory_keyring():
    return MemoryKeyring()


@pytest.fixture(autouse=True)
def isolated_keychain(monkeypatch, memory_keyring):
    from src.credentials import OSCredentialStore

    monkeypatch.setattr(OSCredentialStore, "_get_backend", lambda self: memory_keyring)
