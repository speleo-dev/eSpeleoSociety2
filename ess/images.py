"""Validation and normalisation of uploaded images.

Every upload is decoded and re-encoded, so only real raster images are stored (no SVG/HTML)
and metadata such as EXIF (location, camera) is dropped.
"""

import io

from PIL import Image, ImageOps, UnidentifiedImageError

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


# --- portraits (eCP photo) ---------------------------------------------------------------------------------

PORTRAIT_RATIO = 220 / 300  # width / height, as on the card
PORTRAIT_SIZE = (440, 600)
PORTRAIT_MIN_SOURCE = 240  # shorter side of the uploaded photo
ORIGINAL_MAX_SIDE = 2000


def _jpeg(image: Image.Image, quality: int = 90) -> bytes:
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


def normalize_original(data: bytes) -> bytes:
    """Uploaded photo: rotated by EXIF, RGB, at most 2000 px, re-encoded as JPEG without metadata."""
    image = ImageOps.exif_transpose(_open(data)).convert("RGB")
    if min(image.size) < PORTRAIT_MIN_SOURCE:
        raise DomainError("photo_too_small")
    image.thumbnail((ORIGINAL_MAX_SIDE, ORIGINAL_MAX_SIDE))
    return _jpeg(image)


def portrait_box(size: tuple[int, int], crop: tuple[float, float, float, float] | None) -> tuple[int, int, int, int]:
    """Pixel box (left, top, right, bottom) with the card aspect ratio.

    `crop` is (x, y, width, height) as fractions of the image (from the browser); None = automatic
    (largest box, horizontally centred, slightly above the middle, where faces usually are).
    """
    width, height = size
    if crop is None:
        box_w = min(width, round(height * PORTRAIT_RATIO))
        box_h = round(box_w / PORTRAIT_RATIO)
        left = (width - box_w) // 2
        top = round((height - box_h) * 0.4)
        return left, top, left + box_w, top + box_h
    x, y, w, _h = (max(0.0, min(1.0, v)) for v in crop)
    box_w = max(1, round(w * width))
    box_h = round(box_w / PORTRAIT_RATIO)
    if box_h > height:  # keep the ratio inside the image
        box_h = height
        box_w = round(box_h * PORTRAIT_RATIO)
    left = min(max(0, round(x * width)), width - box_w)
    top = min(max(0, round(y * height)), height - box_h)
    return left, top, left + box_w, top + box_h


def crop_portrait(original_jpeg: bytes, crop: tuple[float, float, float, float] | None) -> bytes:
    """Portrait for the eCP: crop with the card ratio and scale to 440×600 px."""
    with Image.open(io.BytesIO(original_jpeg)) as image:
        image = image.convert("RGB")
        box = portrait_box(image.size, crop)
        if min(box[2] - box[0], box[3] - box[1]) < PORTRAIT_MIN_SOURCE // 2:
            raise DomainError("photo_crop_too_small")
        return _jpeg(image.crop(box).resize(PORTRAIT_SIZE, Image.Resampling.LANCZOS))
