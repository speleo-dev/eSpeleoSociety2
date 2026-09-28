"""Media storage (Google Cloud Storage): club logos and, later, face photos.

Objects are readable by anyone who knows the exact name, but the bucket cannot be listed (R24).
Names are therefore random; they never contain personal data.
"""

import uuid
from functools import lru_cache
from typing import Protocol

from ess.config import get_settings

GCS_PUBLIC_BASE = "https://storage.googleapis.com"


class MediaStore(Protocol):
    def put(self, name: str, data: bytes, content_type: str) -> str:
        """Store an object and return its public URL."""

    def delete(self, name: str) -> None:
        """Delete an object; a missing object is not an error."""

    def name_from_url(self, url: str | None) -> str | None:
        """Object name if the URL points into this store, otherwise None (e.g. the old bucket)."""


def random_name(prefix: str, extension: str) -> str:
    return f"{prefix}/{uuid.uuid4().hex}.{extension}"


class _UrlMixin:
    base_url: str

    def url(self, name: str) -> str:
        return f"{self.base_url}/{name}"

    def name_from_url(self, url: str | None) -> str | None:
        prefix = self.base_url + "/"
        if url and url.startswith(prefix) and len(url) > len(prefix):
            return url[len(prefix):]
        return None


class GcsMediaStore(_UrlMixin):
    def __init__(self, bucket: str):
        from google.cloud import storage  # imported lazily: not needed in tests

        self._bucket = storage.Client().bucket(bucket)
        self.base_url = f"{GCS_PUBLIC_BASE}/{bucket}"

    def put(self, name: str, data: bytes, content_type: str) -> str:
        blob = self._bucket.blob(name)
        # Names are never reused, so the object can be cached for a long time.
        blob.cache_control = "public, max-age=31536000, immutable"
        blob.upload_from_string(data, content_type=content_type)
        return self.url(name)

    def delete(self, name: str) -> None:
        from google.api_core.exceptions import NotFound

        try:
            self._bucket.blob(name).delete()
        except NotFound:
            pass


class MemoryMediaStore(_UrlMixin):
    """In-memory store for tests and local development without Google Cloud."""

    def __init__(self, bucket: str = "test-bucket"):
        self.base_url = f"{GCS_PUBLIC_BASE}/{bucket}"
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, name: str, data: bytes, content_type: str) -> str:
        self.objects[name] = (data, content_type)
        return self.url(name)

    def delete(self, name: str) -> None:
        self.objects.pop(name, None)


@lru_cache
def _gcs_store(bucket: str) -> GcsMediaStore:
    return GcsMediaStore(bucket)


def get_media_store() -> MediaStore | None:
    """Configured store, or None when ESS_MEDIA_BUCKET is not set (FastAPI dependency)."""
    bucket = get_settings().media_bucket
    return _gcs_store(bucket) if bucket else None
