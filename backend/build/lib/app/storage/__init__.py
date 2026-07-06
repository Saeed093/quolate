"""Storage seam. Import `storage` for the configured StorageService."""
from __future__ import annotations

from app.config import settings
from app.storage.base import StorageService
from app.storage.local import LocalDiskStorage

# TODO(cloud): swap for SupabaseStorage behind the same interface.
storage: StorageService = LocalDiskStorage(settings.storage_path)

__all__ = ["StorageService", "LocalDiskStorage", "storage"]
