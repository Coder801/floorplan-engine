from __future__ import annotations

import io
import random

from PIL import Image

from floorplan_engine.service.photos import GPS_IFD, LONG_SIDE, shrink


def _noise(width: int, height: int, mode: str = "RGB") -> Image.Image:
    """Noise does not compress: a stand-in for a phone photo of a rough wall."""
    return Image.frombytes(
        mode, (width, height), random.Random(7).randbytes(width * height * len(mode))
    )


def _encode(image: Image.Image, fmt: str, **kw: object) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, fmt, **kw)
    return buffer.getvalue()


def _open(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def test_large_jpeg_shrinks_to_long_side_keeps_format_and_date() -> None:
    exif = Image.Exif()
    exif[0x0132] = "2026:11:24 10:00:00"  # DateTime
    exif.get_ifd(GPS_IFD)[2] = (50.0, 27.0, 0.0)  # GPSLatitude
    data = _encode(_noise(4000, 1000), "JPEG", quality=98, exif=exif.tobytes())

    out = shrink(data, "image/jpeg")

    assert out.shrunk and len(out.data) < len(data)
    image = _open(out.data)
    assert image.format == "JPEG"
    assert image.size == (LONG_SIDE, 750)
    kept = image.getexif()
    assert kept.get(0x0132) == "2026:11:24 10:00:00"
    assert GPS_IFD not in kept and not kept.get_ifd(GPS_IFD)


def test_exif_orientation_goes_into_pixels() -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° CW to show
    data = _encode(_noise(1200, 800), "JPEG", quality=95, exif=exif.tobytes())

    out = shrink(data, "image/jpeg")

    image = _open(out.data)
    assert out.shrunk
    assert image.size == (800, 1200)
    assert image.getexif().get(0x0112) is None


def test_small_photo_stays_as_is() -> None:
    data = _encode(_noise(640, 480), "JPEG", quality=85)
    out = shrink(data, "image/jpeg")
    assert not out.shrunk and out.data == data


def test_webp_and_png_keep_their_format() -> None:
    webp = _encode(_noise(3600, 1200), "WEBP", quality=100)
    out = shrink(webp, "image/webp")
    assert (
        out.shrunk and _open(out.data).format == "WEBP" and max(_open(out.data).size) == LONG_SIDE
    )

    png = _encode(_noise(3600, 600, "RGBA"), "PNG")
    out = shrink(png, "image/png")
    image = _open(out.data)
    assert (
        out.shrunk
        and image.format == "PNG"
        and image.mode == "RGBA"
        and image.size == (LONG_SIDE, 500)
    )


def test_not_an_image_or_other_type_stays_as_is() -> None:
    assert shrink(b"%PDF-1.7 report", "application/pdf").data == b"%PDF-1.7 report"
    assert shrink(b"\xff\xd8 broken", "image/jpeg").data == b"\xff\xd8 broken"
    heic = b"\x00\x00\x00\x18ftypheic"
    assert shrink(heic, "image/heic").data == heic


def test_content_type_that_lies_is_not_converted() -> None:
    png = _encode(_noise(3600, 600), "PNG")
    out = shrink(png, "image/jpeg")
    assert not out.shrunk and out.data == png
