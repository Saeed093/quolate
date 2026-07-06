"""StorageService interface (the single file-access seam)."""
from __future__ import annotations

from abc import ABC, abstractmethod


class StorageService(ABC):
    @abstractmethod
    def save(self, key: str, data: bytes, content_type: str | None = None) -> str:
        """Persist bytes under `key`; return the stored key."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Read bytes for `key`. Raises FileNotFoundError if absent."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        ...

    @abstractmethod
    def url(self, key: str) -> str:
        """A URL/path the API can serve or redirect to for `key`."""

    @abstractmethod
    def delete(self, key: str) -> None:
        ...
