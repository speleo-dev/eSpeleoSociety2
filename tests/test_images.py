"""Uploaded image validation and the in-memory media store."""

import io

import pytest
from PIL import Image

from ess.images import MAX_UPLOAD_BYTES, normalize_logo
from ess.services.access import DomainError
from ess.storage import MemoryMediaStore, random_name


def image_bytes(fmt="PNG", size=(40, 20), mode="RGB") -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, "red").save(out, format=fmt)
    return out.getvalue()


def test_logo_is_png_and_keeps_aspect_ratio():
    png = normalize_logo(image_bytes("JPEG", (2000, 1000)))
    with Image.open(io.BytesIO(png)) as img:
        assert img.format == "PNG" and img.size == (512, 256) and img.mode == "RGBA"


def test_small_logo_is_not_enlarged():
    with Image.open(io.BytesIO(normalize_logo(image_bytes("WEBP", (50, 30))))) as img:
        assert img.size == (50, 30)


@pytest.mark.parametrize("data, code", [
    (b"", "image_missing"),
    (b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "invalid_image"),
    (b"not an image at all", "invalid_image"),
    (image_bytes("BMP"), "invalid_image"),
    (image_bytes()[:30], "invalid_image"),
    (b"x" * (MAX_UPLOAD_BYTES + 1), "image_too_large"),
])
def test_invalid_images_are_rejected(data, code):
    with pytest.raises(DomainError) as exc:
        normalize_logo(data)
    assert exc.value.code == code


def test_exif_metadata_is_dropped():
    out = io.BytesIO()
    exif = Image.Exif()
    exif[0x010F] = "SecretCamera"
    Image.new("RGB", (10, 10)).save(out, format="JPEG", exif=exif)
    assert b"SecretCamera" in out.getvalue()
    assert b"SecretCamera" not in normalize_logo(out.getvalue())


def test_memory_store_urls_and_random_names():
    store = MemoryMediaStore("bucket-x")
    name = random_name("clubs", "png")
    assert name.startswith("clubs/") and len(name) == len("clubs/") + 32 + len(".png")
    url = store.put(name, b"data", "image/png")
    assert url == f"https://storage.googleapis.com/bucket-x/{name}"
    assert store.name_from_url(url) == name
    assert store.name_from_url("https://storage.googleapis.com/sss_sk_bucket/Logo.png") is None
    assert store.name_from_url(None) is None
    store.delete(name)
    store.delete(name)  # missing object is not an error
    assert store.objects == {}


def test_portrait_box_keeps_ratio_and_stays_inside():
    from ess.images import PORTRAIT_RATIO, portrait_box

    for size, crop in (((1000, 800), None), ((400, 1200), None), ((1000, 800), (0.9, 0.9, 0.5, 0.5)),
                       ((1000, 800), (0.1, 0.2, 1.0, 1.0)), ((1000, 800), (-1, 2, 0.3, 0.3))):
        left, top, right, bottom = portrait_box(size, crop)
        assert 0 <= left < right <= size[0] and 0 <= top < bottom <= size[1]
        assert abs((right - left) / (bottom - top) - PORTRAIT_RATIO) < 0.01


def test_portrait_is_rotated_by_exif_and_sized():
    from ess.images import PORTRAIT_SIZE, crop_portrait, normalize_original

    out = io.BytesIO()
    exif = Image.Exif()
    exif[0x0112] = 6  # rotated 90° - the photo is really portrait
    exif[0x010F] = "SecretCamera"
    Image.new("RGB", (1200, 800), "red").save(out, format="JPEG", exif=exif)
    original = normalize_original(out.getvalue())
    with Image.open(io.BytesIO(original)) as img:
        assert img.size == (800, 1200)
    assert b"SecretCamera" not in original
    with Image.open(io.BytesIO(crop_portrait(original, (0.1, 0.1, 0.5, 0.5)))) as img:
        assert img.size == PORTRAIT_SIZE and img.format == "JPEG"


def test_small_photo_and_tiny_crop_are_rejected():
    from ess.images import crop_portrait, normalize_original

    with pytest.raises(DomainError) as exc:
        normalize_original(image_bytes("PNG", (200, 300)))
    assert exc.value.code == "photo_too_small"
    original = normalize_original(image_bytes("PNG", (300, 400)))
    with pytest.raises(DomainError) as exc:
        crop_portrait(original, (0, 0, 0.1, 0.1))
    assert exc.value.code == "photo_crop_too_small"
