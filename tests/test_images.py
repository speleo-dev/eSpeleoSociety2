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
