from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from PIL import Image

from services import image_service
from services.image_service import ImageProcessingError, normalize_uploaded_image, normalize_uploaded_images


def uploaded(name: str, data: bytes, size: int | None = None):
    return SimpleNamespace(name=name, size=len(data) if size is None else size, getvalue=lambda: data)


def make_image_bytes(format_name: str = "JPEG", size: tuple[int, int] = (64, 32), **save_kwargs) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (220, 120, 80)).save(buffer, format=format_name, **save_kwargs)
    return buffer.getvalue()


def test_normalizes_jpeg_to_metadata_free_jpeg():
    result = normalize_uploaded_image(uploaded("palm.jpg", make_image_bytes("JPEG")))

    assert result.mime_type == "image/jpeg"
    assert result.source_format == "JPEG"
    assert result.width == 64
    assert result.height == 32
    with Image.open(io.BytesIO(result.jpeg_bytes)) as image:
        assert image.format == "JPEG"
        assert image.getexif() == {}


def test_normalizes_png_to_rgb_jpeg():
    result = normalize_uploaded_image(uploaded("palm.png", make_image_bytes("PNG")))

    assert result.mime_type == "image/jpeg"
    assert result.source_format == "PNG"
    with Image.open(io.BytesIO(result.jpeg_bytes)) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"


def test_transparent_rgba_png_composites_on_white_background():
    image = Image.new("RGBA", (32, 16), (0, 0, 0, 0))
    for x in range(16, 32):
        for y in range(16):
            image.putpixel((x, y), (255, 0, 0, 128))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    result = normalize_uploaded_image(uploaded("transparent.png", buffer.getvalue()))

    with Image.open(io.BytesIO(result.jpeg_bytes)) as normalized:
        assert normalized.format == "JPEG"
        assert normalized.mode == "RGB"
        assert normalized.getpixel((4, 8)) == (255, 255, 255)
        red_on_white = normalized.getpixel((24, 8))
        assert red_on_white[0] > red_on_white[1] > 100


def test_transparent_la_png_composites_on_white_background():
    image = Image.new("LA", (1, 1), (0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    result = normalize_uploaded_image(uploaded("transparent_la.png", buffer.getvalue()))

    with Image.open(io.BytesIO(result.jpeg_bytes)) as normalized:
        assert normalized.mode == "RGB"
        assert normalized.getpixel((0, 0)) == (255, 255, 255)


def test_palette_png_transparency_composites_on_white_background():
    image = Image.new("P", (1, 1))
    image.putpalette([0, 0, 0] * 256)
    image.info["transparency"] = 0
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", transparency=0)

    result = normalize_uploaded_image(uploaded("palette.png", buffer.getvalue()))

    with Image.open(io.BytesIO(result.jpeg_bytes)) as normalized:
        assert normalized.mode == "RGB"
        assert normalized.getpixel((0, 0)) == (255, 255, 255)


def test_applies_exif_orientation_before_resizing():
    exif = Image.Exif()
    exif[274] = 6
    original = make_image_bytes("JPEG", size=(40, 80), exif=exif)

    result = normalize_uploaded_image(uploaded("portrait.jpg", original))

    assert (result.width, result.height) == (80, 40)


def test_removes_exif_metadata():
    image = Image.new("RGB", (24, 24), (20, 90, 150))
    exif = Image.Exif()
    exif[271] = "Synthetic Camera"
    exif[306] = "2026:08:31 00:00:00"
    buffer = io.BytesIO()
    image.save(
        buffer,
        format="JPEG",
        exif=exif,
        icc_profile=b"synthetic-icc",
        comment=b"synthetic-comment",
        xmp=b"<x:xmpmeta>synthetic</x:xmpmeta>",
        dpi=(300, 300),
    )

    result = normalize_uploaded_image(uploaded("gps_filename_should_not_leak.jpeg", buffer.getvalue()))

    with Image.open(io.BytesIO(result.jpeg_bytes)) as normalized:
        assert normalized.getexif() == {}
        assert 34853 not in normalized.getexif()
        for metadata_key in ("exif", "icc_profile", "xmp", "comment", "dpi"):
            assert metadata_key not in normalized.info
    assert b"gps_filename_should_not_leak" not in result.jpeg_bytes


def test_large_image_is_resized_with_aspect_ratio(monkeypatch):
    monkeypatch.setattr(image_service, "NORMALIZED_IMAGE_MAX_EDGE_PX", 128)
    result = normalize_uploaded_image(uploaded("large.png", make_image_bytes("PNG", size=(512, 256))))

    assert result.width == 128
    assert result.height == 64


def test_rejects_file_size_over_limit():
    too_large = image_service.MAX_IMAGE_SIZE_MB * 1024 * 1024 + 1

    with pytest.raises(ImageProcessingError) as excinfo:
        normalize_uploaded_image(uploaded("palm.jpg", b"not-read", size=too_large))

    assert excinfo.value.code == "file_too_large"


def test_rejects_corrupt_image():
    with pytest.raises(ImageProcessingError) as excinfo:
        normalize_uploaded_image(uploaded("palm.jpg", b"not an image"))

    assert excinfo.value.code == "unreadable"


def test_rejects_extension_mismatch():
    with pytest.raises(ImageProcessingError) as excinfo:
        normalize_uploaded_image(uploaded("fake.jpg", make_image_bytes("PNG")))

    assert excinfo.value.code == "format_mismatch"


def test_rejects_non_image_file():
    with pytest.raises(ImageProcessingError) as excinfo:
        normalize_uploaded_image(uploaded("note.txt", b"hello"))

    assert excinfo.value.code == "unreadable"


def test_rejects_pixel_limit(monkeypatch):
    monkeypatch.setattr(image_service, "MAX_IMAGE_PIXELS", 100)

    with pytest.raises(ImageProcessingError) as excinfo:
        normalize_uploaded_image(uploaded("large.png", make_image_bytes("PNG", size=(20, 20))))

    assert excinfo.value.code == "pixel_limit_exceeded"


def test_rejects_pixel_limit_before_image_load(monkeypatch):
    load_called = False

    class FakeImage:
        format = "JPEG"
        size = (20, 20)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def load(self):
            nonlocal load_called
            load_called = True

    monkeypatch.setattr(image_service, "MAX_IMAGE_PIXELS", 100)
    monkeypatch.setattr(image_service.Image, "open", lambda *args, **kwargs: FakeImage())

    with pytest.raises(ImageProcessingError) as excinfo:
        normalize_uploaded_image(uploaded("large.jpg", b"fake-jpeg"))

    assert excinfo.value.code == "pixel_limit_exceeded"
    assert load_called is False


def test_decompression_bomb_warning_is_user_pixel_limit_error(monkeypatch):
    def raise_warning(*args, **kwargs):
        raise Image.DecompressionBombWarning("too large")

    monkeypatch.setattr(image_service.Image, "open", raise_warning)

    with pytest.raises(ImageProcessingError) as excinfo:
        normalize_uploaded_image(uploaded("large.jpg", b"fake-jpeg"))

    assert excinfo.value.code == "pixel_limit_exceeded"


def test_decompression_bomb_error_is_user_pixel_limit_error(monkeypatch):
    def raise_error(*args, **kwargs):
        raise Image.DecompressionBombError("too large")

    monkeypatch.setattr(image_service.Image, "open", raise_error)

    with pytest.raises(ImageProcessingError) as excinfo:
        normalize_uploaded_image(uploaded("large.jpg", b"fake-jpeg"))

    assert excinfo.value.code == "pixel_limit_exceeded"


def test_too_many_files_does_not_normalize_any_image(monkeypatch):
    calls = []
    files = [uploaded(f"palm_{index}.jpg", b"fake") for index in range(image_service.MAX_IMAGE_FILES + 1)]
    monkeypatch.setattr(image_service, "normalize_uploaded_image", lambda file: calls.append(file))

    with pytest.raises(ImageProcessingError) as excinfo:
        normalize_uploaded_images(files)

    assert excinfo.value.code == "too_many_files"
    assert calls == []


@pytest.mark.parametrize("filename", ["palm.avif", "palm.heic", "palm.heif"])
def test_rejects_avif_content_regardless_of_extension(monkeypatch, filename):
    class FakeAvifImage:
        format = "AVIF"
        size = (10, 10)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(image_service.Image, "open", lambda *args, **kwargs: FakeAvifImage())

    with pytest.raises(ImageProcessingError) as excinfo:
        normalize_uploaded_image(uploaded(filename, b"fake-avif"))

    assert excinfo.value.code == "unsupported_format"


@pytest.mark.skipif(not image_service.HEIF_SUPPORT_AVAILABLE, reason="pillow-heif is not installed")
def test_normalizes_heic_fixture_generated_from_synthetic_image():
    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), (10, 20, 30)).save(buffer, format="HEIF", quality=90)

    result = normalize_uploaded_image(uploaded("synthetic.heic", buffer.getvalue()))

    assert result.mime_type == "image/jpeg"
    assert result.source_format == "HEIF"


@pytest.mark.skipif(not image_service.HEIF_SUPPORT_AVAILABLE, reason="pillow-heif is not installed")
def test_normalizes_heif_fixture_generated_from_synthetic_image():
    buffer = io.BytesIO()
    Image.new("RGB", (28, 20), (30, 20, 10)).save(buffer, format="HEIF", quality=90)

    result = normalize_uploaded_image(uploaded("synthetic.heif", buffer.getvalue()))

    assert result.mime_type == "image/jpeg"
    assert result.source_format == "HEIF"


def test_image_processing_error_message_mentions_purchase_is_not_used():
    with pytest.raises(ImageProcessingError) as excinfo:
        normalize_uploaded_image(uploaded("palm.jpg", b"not an image"))

    assert "この段階では購入権は使用されていません" in excinfo.value.user_message
