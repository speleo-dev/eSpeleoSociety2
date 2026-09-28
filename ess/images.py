"""Validation and normalisation of uploaded images.

Every upload is decoded and re-encoded, so only real raster images are stored (no SVG/HTML)
and metadata such as EXIF (location, camera) is dropped.
"""

import io

from PIL import Image, UnidentifiedImageError

from ess.services.access import DomainError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_SOURCE_PIXELS = 40_000_000  # decompression bomb guard
LOGO_MAX_SIZE = 512
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}


def _open(data: bytes) -> Image.Image:
    if not data:
        raise DomainError("image_missing")
    if len(data) > MAX_UPLOAD_BYTES:
        raise DomainError("image_too_large")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            if probe.format not in ALLOWED_FORMATS:
                raise DomainError("invalid_image")
            if probe.width * probe.height > MAX_SOURCE_PIXELS:
                raise DomainError("image_too_large")
            probe.verify()
        image = Image.open(io.BytesIO(data))
        image.load()
    except DomainError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise DomainError("invalid_image") from None
    return image


def normalize_logo(data: bytes) -> bytes:
    """Club logo: PNG with transparency, at most 512×512 px, aspect ratio kept."""
    image = _open(data)
    image = image.convert("RGBA")
    image.thumbnail((LOGO_MAX_SIZE, LOGO_MAX_SIZE))
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()
