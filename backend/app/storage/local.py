"""Local disk implementation of StorageService."""
from __future__ import annotations

from pathlib import Path

from app.storage.base import StorageService


class LocalDiskStorage(StorageService):
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Normalise and prevent path traversal outside the root.
        safe = key.replace("\\", "/").lstrip("/")
        path = (self.root / safe).resolve()
        if not str(path).startswith(str(self.root.resolve())):
            raise ValueError(f"Illegal storage key: {key}")
        return path

    def save(self, key: str, data: bytes, content_type: str | None = None) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise FileNotFoundError(key)
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def url(self, key: str) -> str:
        # Served by the API document routes; frontend never touches disk.
        return f"/files/{key}"

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()

    def delete_prefix(self, prefix: str) -> None:
        """Remove a key prefix tree from disk (e.g. projects/{id}/)."""
        import shutil

        safe = prefix.replace("\\", "/").strip("/")
        if not safe:
            return
        root = self._path(safe)
        if root.exists():
            shutil.rmtree(root)
