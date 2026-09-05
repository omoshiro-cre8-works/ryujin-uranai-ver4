from __future__ import annotations

import io
import logging
import warnings
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

try:
    from PIL import ImageFile

    ImageFile.LOAD_TRUNCATED_IMAGES = False
except Exception:  # pragma: no cover - defensive only
    pass

from config import MAX_IMAGE_FILES, MAX_IMAGE_SIZE_MB

logger = logging.getLogger(__name__)

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF_SUPPORT_AVAILABLE = True
except Exception:  # pragma: no cover - exercised when optional dependency is missing
    HEIF_SUPPORT_AVAILABLE = False


NORMALIZED_IMAGE_MIME_TYPE = "image/jpeg"
NORMALIZED_IMAGE_MAX_EDGE_PX = 2048
NORMALIZED_IMAGE_JPEG_QUALITY = 88
MAX_IMAGE_PIXELS = 24_000_000
JPEG_OUTPUT_MAX_BYTES = MAX_IMAGE_SIZE_MB * 1024 * 1024
JPEG_BACKGROUND_COLOR = (255, 255, 255)
SUPPORTED_IMAGE_FORMATS = {"JPEG", "PNG", "HEIF"}
USER_ACTION_SUFFIX = "別の画像を選ぶか、もう一度撮影してください。この段階では購入権は使用されていません。"


@dataclass(frozen=True)
class NormalizedPalmImage:
    original_name: str
    jpeg_bytes: bytes
    mime_type: str
    width: int
    height: int
    source_format: str
    original_size_bytes: int
    normalized_size_bytes: int


class ImageProcessingError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.user_message = message


def _user_message(prefix: str) -> str:
    return f"{prefix}{USER_ACTION_SUFFIX}"


def _read_uploaded_file(uploaded_file: Any) -> bytes:
    try:
        data = uploaded_file.getvalue()
    except Exception as exc:
        raise ImageProcessingError(
            "unreadable",
            _user_message("画像を読み込めませんでした。"),
        ) from exc

    if not data:
        raise ImageProcessingError(
            "unreadable",
            _user_message("画像を読み込めませんでした。"),
        )
    if isinstance(data, bytes):
        return data
    return bytes(data)


def _normalize_format(format_name: str | None) -> str:
    normalized = (format_name or "").upper()
    if normalized in {"MPO", "JPG"}:
        return "JPEG"
    if normalized in {"HEIC", "HEIF"}:
        return "HEIF"
    return normalized


def _extension_family(filename: str) -> str | None:
    lower = filename.lower()
    if lower.endswith((".jpg", ".jpeg")):
        return "JPEG"
    if lower.endswith(".png"):
        return "PNG"
    if lower.endswith((".heic", ".heif")):
        return "HEIF"
    return None


def _validate_extension_matches_format(filename: str, source_format: str) -> None:
    expected_family = _extension_family(filename)
    if expected_family is None:
        raise ImageProcessingError(
            "unsupported_format",
            _user_message("対応していない画像形式です。JPEG、PNG、HEIC、HEIF の画像を選んでください。"),
        )
    if expected_family != source_format:
        raise ImageProcessingError(
            "format_mismatch",
            _user_message("画像のファイル形式を確認できませんでした。"),
        )


def validate_uploaded_images_lightweight(uploaded_files: list[Any], require_files: bool = True) -> None:
    if not uploaded_files:
        if require_files:
            raise ImageProcessingError(
                "missing_image",
                _user_message("手相画像をアップロードしてください。"),
            )
        return
    if len(uploaded_files) > MAX_IMAGE_FILES:
        raise ImageProcessingError(
            "too_many_files",
            _user_message(f"手相画像は {MAX_IMAGE_FILES} 枚までにしてください。"),
        )

    for uploaded_file in uploaded_files:
        filename = str(getattr(uploaded_file, "name", "") or "")
        if not filename:
            raise ImageProcessingError(
                "missing_image",
                _user_message("手相画像をアップロードしてください。"),
            )
        if _extension_family(filename) is None:
            raise ImageProcessingError(
                "unsupported_format",
                _user_message("対応していない画像形式です。JPEG、PNG、HEIC、HEIF の画像を選んでください。"),
            )
        declared_size = int(getattr(uploaded_file, "size", 0) or 0)
        if declared_size > MAX_IMAGE_SIZE_MB * 1024 * 1024:
            raise ImageProcessingError(
                "file_too_large",
                _user_message(f"画像サイズが大きすぎます。1枚あたり{MAX_IMAGE_SIZE_MB}MB以下の画像を選んでください。"),
            )


def _to_rgb_on_white(image: Image.Image) -> Image.Image:
    image.load()
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, JPEG_BACKGROUND_COLOR + (255,))
        background.alpha_composite(rgba)
        rgba.close()
        return background.convert("RGB")
    if image.mode != "RGB":
        return image.convert("RGB")
    return image.copy()


def normalize_uploaded_image(uploaded_file: Any) -> NormalizedPalmImage:
    original_name = str(getattr(uploaded_file, "name", "") or "image")
    original_size = int(getattr(uploaded_file, "size", 0) or 0)
    if original_size > MAX_IMAGE_SIZE_MB * 1024 * 1024:
        raise ImageProcessingError(
            "file_too_large",
            _user_message(f"画像サイズが大きすぎます。1枚あたり{MAX_IMAGE_SIZE_MB}MB以下の画像を選んでください。"),
        )

    data = _read_uploaded_file(uploaded_file)
    if original_size == 0:
        original_size = len(data)
    if len(data) > MAX_IMAGE_SIZE_MB * 1024 * 1024:
        raise ImageProcessingError(
            "file_too_large",
            _user_message(f"画像サイズが大きすぎます。1枚あたり{MAX_IMAGE_SIZE_MB}MB以下の画像を選んでください。"),
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image_file = Image.open(io.BytesIO(data))
        with image_file as image:
            source_format = _normalize_format(image.format)
            if source_format not in SUPPORTED_IMAGE_FORMATS:
                raise ImageProcessingError(
                    "unsupported_format",
                    _user_message("対応していない画像形式です。JPEG、PNG、HEIC、HEIF の画像を選んでください。"),
                )
            if source_format == "HEIF" and not HEIF_SUPPORT_AVAILABLE:
                raise ImageProcessingError(
                    "heif_conversion_failed",
                    _user_message("HEIC／HEIF画像を変換できませんでした。"),
                )

            width, height = image.size
            if width * height > MAX_IMAGE_PIXELS:
                raise ImageProcessingError(
                    "pixel_limit_exceeded",
                    _user_message("画像の画素数が大きすぎます。少し小さい画像を選んでください。"),
                )

            _validate_extension_matches_format(original_name, source_format)
            image.load()
            normalized = ImageOps.exif_transpose(image)
            try:
                rgb_image = _to_rgb_on_white(normalized)
                rgb_image.thumbnail(
                    (NORMALIZED_IMAGE_MAX_EDGE_PX, NORMALIZED_IMAGE_MAX_EDGE_PX),
                    Image.Resampling.LANCZOS,
                )
                rgb_image.info.clear()

                with io.BytesIO() as output:
                    rgb_image.save(
                        output,
                        format="JPEG",
                        quality=NORMALIZED_IMAGE_JPEG_QUALITY,
                        optimize=True,
                    )
                    jpeg_bytes = output.getvalue()
                width = rgb_image.width
                height = rgb_image.height
            finally:
                if normalized is not image:
                    normalized.close()
                try:
                    rgb_image.close()
                except UnboundLocalError:
                    pass
            if len(jpeg_bytes) > JPEG_OUTPUT_MAX_BYTES:
                raise ImageProcessingError(
                    "normalized_file_too_large",
                    _user_message("変換後の画像サイズが大きすぎます。少し小さい画像を選んでください。"),
                )
    except ImageProcessingError:
        raise
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ImageProcessingError(
            "pixel_limit_exceeded",
            _user_message("画像の画素数が大きすぎます。少し小さい画像を選んでください。"),
        ) from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        code = "heif_conversion_failed" if _extension_family(original_name) == "HEIF" else "unreadable"
        message = "HEIC／HEIF画像を変換できませんでした。" if code == "heif_conversion_failed" else "画像を読み込めませんでした。"
        raise ImageProcessingError(code, _user_message(message)) from exc
    except Exception as exc:
        logger.warning("image_processing_unexpected", extra={"stage": "normalize", "error_type": type(exc).__name__})
        raise ImageProcessingError(
            "unexpected",
            _user_message("画像処理中に予期しないエラーが発生しました。"),
        ) from exc

    logger.info(
        "image_normalized",
        extra={
            "stage": "normalize",
            "source_format": source_format,
            "original_size_bytes": original_size,
            "normalized_size_bytes": len(jpeg_bytes),
            "width": width,
            "height": height,
        },
    )
    return NormalizedPalmImage(
        original_name=original_name,
        jpeg_bytes=jpeg_bytes,
        mime_type=NORMALIZED_IMAGE_MIME_TYPE,
        width=width,
        height=height,
        source_format=source_format,
        original_size_bytes=original_size,
        normalized_size_bytes=len(jpeg_bytes),
    )


def normalize_uploaded_images(uploaded_files: list[Any]) -> list[NormalizedPalmImage]:
    validate_uploaded_images_lightweight(uploaded_files)
    normalized_images: list[NormalizedPalmImage] = []
    for uploaded_file in uploaded_files:
        normalized_images.append(normalize_uploaded_image(uploaded_file))
    return normalized_images
