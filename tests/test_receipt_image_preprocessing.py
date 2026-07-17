from io import BytesIO

import pytest

from app.services.receipt_image_preprocessing import (
    ReceiptImagePixelLimitError,
    preprocess_receipt_image,
)


def _jpeg(size=(800, 1200), *, colors=(30, 230), exif_orientation=None) -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", size, (colors[1],) * 3)
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], 40):
        tone = colors[y // 40 % 2]
        draw.rectangle(
            (20, y, max(21, size[0] - 20), min(size[1], y + 12)),
            fill=(tone,) * 3,
        )
    output = BytesIO()
    exif = Image.Exif()
    if exif_orientation is not None:
        exif[274] = exif_orientation
    image.save(output, format="JPEG", quality=92, exif=exif)
    return output.getvalue()


def test_normal_image_keeps_original_without_derivative():
    result = preprocess_receipt_image(_jpeg(), "image/jpeg")

    assert result.derivative_content is None
    assert result.metadata["status"] == "ready"
    assert result.metadata["selected_variant"] == "original"
    assert result.metadata["width"] == 800
    assert result.metadata["height"] == 1200
    assert result.metadata["quality_flags"] == []


def test_exif_orientation_creates_normalized_derivative():
    result = preprocess_receipt_image(
        _jpeg((60, 100), exif_orientation=6),
        "image/jpeg",
    )

    assert result.derivative_content is not None
    assert result.metadata["selected_variant"] == "normalized"
    assert result.metadata["width"] == 100
    assert result.metadata["height"] == 60
    assert "orientation_corrected" in result.metadata["operations"]


def test_oversized_image_is_resized_proportionally(monkeypatch):
    monkeypatch.setenv("SPLITIK_IMAGE_MAX_SIDE", "1000")

    result = preprocess_receipt_image(_jpeg((2500, 1000)), "image/jpeg")

    assert result.derivative_content is not None
    assert (result.metadata["width"], result.metadata["height"]) == (1000, 400)
    assert result.metadata["selected_variant"] == "normalized"
    assert "resized" in result.metadata["operations"]


def test_low_contrast_image_gets_conservative_enhancement():
    result = preprocess_receipt_image(
        _jpeg(colors=(118, 132)),
        "image/jpeg",
    )

    assert result.derivative_content is not None
    assert result.derivative_content_type == "image/jpeg"
    assert result.metadata["selected_variant"] == "enhanced"
    assert "low_contrast" in result.metadata["quality_flags"]
    assert "autocontrast" in result.metadata["operations"]


def test_pixel_limit_rejects_decompression_bomb(monkeypatch):
    monkeypatch.setenv("SPLITIK_IMAGE_MAX_PIXELS", "1000")

    with pytest.raises(ReceiptImagePixelLimitError):
        preprocess_receipt_image(_jpeg((50, 50)), "image/jpeg")


def test_pillow_decompression_bomb_is_reported_as_pixel_limit(monkeypatch):
    from PIL import Image

    def reject_image(_stream):
        raise Image.DecompressionBombError("too many pixels")

    monkeypatch.setattr(Image, "open", reject_image)

    with pytest.raises(ReceiptImagePixelLimitError):
        preprocess_receipt_image(_jpeg(), "image/jpeg")


def test_malformed_image_falls_back_without_private_details():
    result = preprocess_receipt_image(b"not-an-image", "image/jpeg")

    assert result.derivative_content is None
    assert result.metadata == {
        "status": "failed",
        "selected_variant": "original",
        "quality_flags": ["decode_failed"],
        "operations": [],
    }
    assert "content" not in str(result.metadata)
    assert "key" not in str(result.metadata)
