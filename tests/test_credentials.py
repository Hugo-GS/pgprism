"""OS keyring policy and sanitized error behavior."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def test_rejects_non_os_backends():
    from src.credentials import CredentialStoreError, OSCredentialStore
    for module, name in [
        ("keyring.backends.null", "Keyring"),
        ("keyring.backends.fail", "Keyring"),
        ("keyrings.alt.file", "PlaintextKeyring"),
        ("keyrings.alt.file", "EncryptedKeyring"),
        ("custom.backend", "Keyring"),
    ]:
        backend = type(name, (), {"__module__": module})()
        with pytest.raises(CredentialStoreError, match="OS credential store"):
            OSCredentialStore._select_backend(backend)


def test_chainer_selects_os_backend_without_plaintext_fallback(monkeypatch):
    from keyring.backends.chainer import ChainerBackend
    from src.credentials import CredentialStoreError, OSCredentialStore
    unsafe = SimpleNamespace()
    secure = type("Keyring", (), {"__module__": "keyring.backends.SecretService"})()
    monkeypatch.setattr(ChainerBackend, "backends", [unsafe, secure])
    assert OSCredentialStore._select_backend(ChainerBackend()) is secure
    monkeypatch.setattr(ChainerBackend, "backends", [unsafe])
    with pytest.raises(CredentialStoreError):
        OSCredentialStore._select_backend(ChainerBackend())


def test_password_write_errors_never_include_secret(monkeypatch):
    from src.credentials import CredentialStoreError, OSCredentialStore
    store = OSCredentialStore()
    backend = Mock()
    backend.set_password.side_effect = RuntimeError("sensitive-secret-in-backend-error")
    monkeypatch.setattr(store, "_get_backend", lambda: backend)
    with pytest.raises(CredentialStoreError) as error:
        store.set("reference", "sensitive-secret-in-backend-error")
    assert "sensitive-secret" not in str(error.value)
    assert error.value.__suppress_context__ is True


def test_silent_backend_write_is_rejected(monkeypatch):
    from src.credentials import CredentialStoreError, OSCredentialStore
    backend = Mock()
    backend.get_password.return_value = None
    store = OSCredentialStore()
    monkeypatch.setattr(store, "_get_backend", lambda: backend)
    with pytest.raises(CredentialStoreError):
        store.set("reference", "secret")
