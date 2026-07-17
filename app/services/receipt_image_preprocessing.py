import os
import time
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError


@dataclass(frozen=True)
class ReceiptImagePreprocessingResult:
    derivative_content: bytes | None
    derivative_content_type: str | None
    metadata: dict


class ReceiptImagePixelLimitError(ValueError):
    pass


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _quality_signals(image: Image.Image) -> tuple[float, float, float]:
    grayscale = ImageOps.grayscale(image)
    statistics = ImageStat.Stat(grayscale)
    brightness = float(statistics.mean[0])
    contrast = float(statistics.stddev[0])
    edge_image = grayscale.filter(ImageFilter.FIND_EDGES)
    if edge_image.width > 4 and edge_image.height > 4:
        edge_image = edge_image.crop((2, 2, edge_image.width - 2, edge_image.height - 2))
    sharpness = float(ImageStat.Stat(edge_image).var[0])
    return brightness, contrast, sharpness


def _encode_derivative(image: Image.Image, content_type: str) -> tuple[bytes, str]:
    has_transparency = image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    )
    output = BytesIO()
    if has_transparency and content_type in {"image/png", "image/webp"}:
        image.save(output, format="PNG", compress_level=6)
        return output.getvalue(), "image/png"

    if image.mode != "RGB":
        image = image.convert("RGB")
    image.save(output, format="JPEG", quality=88, progressive=True)
    return output.getvalue(), "image/jpeg"


def preprocess_receipt_image(content: bytes, content_type: str) -> ReceiptImagePreprocessingResult:
    started = time.monotonic()
    max_side = _env_int("SPLITIK_IMAGE_MAX_SIDE", 2200)
    try:
        with Image.open(BytesIO(content)) as source:
            source_width, source_height = source.size
            if source_width * source_height > _env_int("SPLITIK_IMAGE_MAX_PIXELS", 40_000_000):
                raise ReceiptImagePixelLimitError("Receipt image pixel limit exceeded.")

            exif_orientation = source.getexif().get(274)
            needs_resize = max(source.size) > max_side
            if needs_resize and source.format == "JPEG":
                source.draft("RGB", (max_side, max_side))
            source.load()
            image = ImageOps.exif_transpose(source)

        operations: list[str] = []
        if exif_orientation not in {None, 1}:
            operations.append("orientation_corrected")

        if needs_resize:
            if max(image.size) > max_side:
                image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            operations.append("resized")

        brightness, contrast, sharpness = _quality_signals(image)
        quality_flags: list[str] = []
        if brightness < 65:
            quality_flags.append("dark")
        if contrast < 20:
            quality_flags.append("low_contrast")
        if sharpness < 18:
            quality_flags.append("blurred")

        should_enhance = bool({"dark", "low_contrast"}.intersection(quality_flags))
        if should_enhance:
            if "dark" in quality_flags:
                factor = min(1.6, max(1.05, 105 / max(brightness, 1)))
                image = ImageEnhance.Brightness(image).enhance(factor)
                operations.append("brightness_corrected")
            image = ImageOps.autocontrast(image, cutoff=1)
            operations.append("autocontrast")

        derivative_content = None
        derivative_content_type = None
        if operations:
            derivative_content, derivative_content_type = _encode_derivative(image, content_type)

        selected_variant = (
            "enhanced" if should_enhance else "normalized" if operations else "original"
        )
        return ReceiptImagePreprocessingResult(
            derivative_content=derivative_content,
            derivative_content_type=derivative_content_type,
            metadata={
                "status": "ready",
                "selected_variant": selected_variant,
                "source_width": source_width,
                "source_height": source_height,
                "width": image.width,
                "height": image.height,
                "quality_flags": quality_flags,
                "operations": operations,
                "brightness": round(brightness, 2),
                "contrast": round(contrast, 2),
                "sharpness": round(sharpness, 2),
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
            },
        )
    except ReceiptImagePixelLimitError:
        raise
    except Image.DecompressionBombError as exc:
        raise ReceiptImagePixelLimitError("Receipt image pixel limit exceeded.") from exc
    except (OSError, UnidentifiedImageError, ValueError):
        return ReceiptImagePreprocessingResult(
            derivative_content=None,
            derivative_content_type=None,
            metadata={
                "status": "failed",
                "selected_variant": "original",
                "quality_flags": ["decode_failed"],
                "operations": [],
            },
        )
