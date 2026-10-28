"""OS-backed credential storage. Never fall back to file or null keyrings."""

from typing import ClassVar, Protocol

import keyring
from keyring.backend import KeyringBackend
from keyring.backends.chainer import ChainerBackend


class CredentialStoreError(RuntimeError):
    """A credential cannot be securely stored, retrieved, or removed."""


class CredentialStore(Protocol):
    def get(self, reference: str) -> str | None: ...
    def set(self, reference: str, password: str) -> None: ...
    def delete(self, reference: str) -> None: ...


class OSCredentialStore:
    """Use one native OS keyring for this store's lifetime, without fallback."""

    SERVICE = "pgprism"
    _OS_MODULES: ClassVar[set[str]] = {
        "keyring.backends.SecretService",
        "keyring.backends.kwallet",
        "keyring.backends.macOS",
        "keyring.backends.Windows",
    }
    _UNAVAILABLE = (
        "OS credential store is unavailable or locked. "
        "Unlock your system keychain and run PgPrism in the same desktop session."
    )

    def __init__(self) -> None:
        self._backend: KeyringBackend | None = None

    @classmethod
    def _select_backend(cls, backend: KeyringBackend) -> KeyringBackend:
        candidates = backend.backends if type(backend) is ChainerBackend else [backend]
        for candidate in candidates:
            if type(candidate).__module__ in cls._OS_MODULES:
                return candidate
        raise CredentialStoreError(cls._UNAVAILABLE)

    def _get_backend(self) -> KeyringBackend:
        if self._backend is None:
            self._backend = self._select_backend(keyring.get_keyring())
        return self._backend

    def get(self, reference: str) -> str | None:
        try:
            return self._get_backend().get_password(self.SERVICE, reference)
        except Exception:
            # Backend exception strings may contain credentials or other sensitive data.
            raise CredentialStoreError(self._UNAVAILABLE) from None

    def set(self, reference: str, password: str) -> None:
        try:
            backend = self._get_backend()
            backend.set_password(self.SERVICE, reference, password)
            if backend.get_password(self.SERVICE, reference) != password:
                raise CredentialStoreError(self._UNAVAILABLE)
        except Exception:
            raise CredentialStoreError(self._UNAVAILABLE) from None

    def delete(self, reference: str) -> None:
        try:
            backend = self._get_backend()
            if backend.get_password(self.SERVICE, reference) is not None:
                backend.delete_password(self.SERVICE, reference)
        except Exception:
            raise CredentialStoreError(self._UNAVAILABLE) from None
