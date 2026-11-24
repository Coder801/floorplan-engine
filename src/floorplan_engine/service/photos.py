"""Photos before storage: a phone photo (3–8 MB) shrinks to what is enough to check the work.

Task photos (db/work_records.py) and feedback photos (db/feedback.py) go through `shrink` before
`ObjectStore.put`. The bar is "not to zero": the long side down to LONG_SIDE px (a 12 MP photo
4000×3000 → 3000×2250: a label on a cable is still readable when zoomed), JPEG and WebP at
quality QUALITY. The format stays the same, so the content type and the key extension do not
change. EXIF orientation is applied to the pixels (the file shows upright everywhere), the date
and the camera stay, GPS is removed (where the client lives is not the business of the file).

The original is kept as is when the file is small and not too large in pixels, when it is not
an image Pillow can read (HEIC, PDF, a broken file), and when the result is not smaller.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from PIL import Image, ImageOps

LONG_SIDE = 3000  # px, the long side after shrinking
QUALITY = 85  # JPEG and WebP; below ~80 the plaster texture turns into blocks
SMALL = 1024 * 1024  # bytes: a file under it with the long side within LONG_SIDE stays as is
GPS_IFD = 0x8825

FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Shrunk:
    data: bytes
    shrunk: bool  # False — the original bytes


def shrink(data: bytes, content_type: str) -> Shrunk:
    """The photo for storage: smaller in pixels and bytes, same format; or the original."""
    fmt = FORMATS.get(content_type.split(";")[0].strip().lower())
    if fmt is None:
        return Shrunk(data, False)
    try:
        out = _shrink(data, fmt)
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        log.warning("фото не сжато, сохранён оригинал: %s", exc)
        return Shrunk(data, False)
    if out is None or len(out) >= len(data):
        return Shrunk(data, False)
    return Shrunk(out, True)


def _shrink(data: bytes, fmt: str) -> bytes | None:
    with Image.open(io.BytesIO(data)) as source:
        if source.format != fmt:  # the content type lies: do not convert behind the user's back
            return None
        rotated = _orientation(source) not in (None, 1)
        if len(data) <= SMALL and max(source.size) <= LONG_SIDE and not rotated:
            return None
        if fmt == "JPEG":
            source.draft("RGB", (LONG_SIDE, LONG_SIDE))  # decode at 1/2, 1/4… — faster, less memory
        image = ImageOps.exif_transpose(source)
        exif = image.getexif()
        exif.pop(0x0112, None)  # orientation is in the pixels now
        exif.get_ifd(GPS_IFD).clear()
        exif.pop(GPS_IFD, None)
        image.thumbnail((LONG_SIDE, LONG_SIDE), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        if fmt == "JPEG":
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            image.save(
                buffer,
                "JPEG",
                quality=QUALITY,
                optimize=True,
                progressive=True,
                exif=exif.tobytes(),
                icc_profile=source.info.get("icc_profile"),
            )
        elif fmt == "WEBP":
            image.save(
                buffer,
                "WEBP",
                quality=QUALITY,
                method=4,
                exif=exif.tobytes(),
                icc_profile=source.info.get("icc_profile"),
            )
        else:  # PNG is a screenshot or a drawing more often than a photo: lossless, only smaller
            image.save(buffer, "PNG", optimize=True)
        return buffer.getvalue()


def _orientation(image: Image.Image) -> int | None:
    value = image.getexif().get(0x0112)
    return value if isinstance(value, int) else None
