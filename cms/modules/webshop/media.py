from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import hashlib

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_UPLOAD_BYTES = 280_000
MAX_SOURCE_PIXELS = 16_000_000
MAX_SOURCE_DIMENSION = 6000
MAX_OUTPUT_DIMENSION = 1600
MAX_OUTPUT_BYTES = 300_000
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS


@dataclass(frozen=True, slots=True)
class SanitizedImage:
    original_name: str
    mime_type: str
    content: bytes
    sha256: str
    width: int
    height: int


def _safe_original_name(name: str) -> str:
    # The original name is metadata only; never used as a filesystem path.
    normalized = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    normalized = "".join(ch for ch in normalized if ch.isprintable() and ch not in {'"', "'", "<", ">", "\x00"})
    return normalized[:180] or "product-image"


def sanitize_image(file_storage) -> SanitizedImage:
    """Decode and re-encode a product image into a safe canonical JPEG.

    Security properties:
    - hard byte limit before decoding;
    - real image decode, not extension/MIME trust;
    - format and pixel/dimension limits;
    - EXIF orientation applied, metadata stripped;
    - output canonicalized to RGB JPEG;
    - deterministic output size cap.
    """
    filename = _safe_original_name(getattr(file_storage, "filename", "") or "")
    raw = file_storage.read(MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise ValueError("Die ausgewählte Bilddatei ist leer. Bitte wähle eine gültige JPEG-, PNG- oder WebP-Datei aus.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError(f"Das Bild ist zu groß. Erlaubt sind maximal {MAX_UPLOAD_BYTES // 1000} KB pro Bild. Bitte verkleinere oder komprimiere die Datei und versuche es erneut.")

    try:
        with Image.open(BytesIO(raw)) as probe:
            fmt = (probe.format or "").upper()
            width, height = probe.size
            if fmt not in ALLOWED_FORMATS:
                raise ValueError("Ungültiger Bildtyp. Erlaubt sind ausschließlich JPEG, PNG und WebP. Bitte konvertiere die Datei in eines dieser Formate.")
            if width < 1 or height < 1:
                raise ValueError("Die Bildabmessungen sind ungültig. Bitte verwende ein Bild mit mindestens 1 × 1 Pixel.")
            if width > MAX_SOURCE_DIMENSION or height > MAX_SOURCE_DIMENSION or width * height > MAX_SOURCE_PIXELS:
                raise ValueError(f"Die Bildauflösung ist zu groß. Maximal erlaubt sind {MAX_SOURCE_DIMENSION} Pixel pro Seite und {MAX_SOURCE_PIXELS:,} Pixel insgesamt. Bitte verkleinere das Bild.")
            probe.verify()
        with Image.open(BytesIO(raw)) as decoded:
            if getattr(decoded, "n_frames", 1) != 1:
                raise ValueError("Animierte Bilder sind nicht erlaubt. Bitte lade ein einzelnes statisches JPEG-, PNG- oder WebP-Bild hoch.")
            decoded.load()
            decoded = ImageOps.exif_transpose(decoded)
            if decoded.mode in {"RGBA", "LA"} or (decoded.mode == "P" and "transparency" in decoded.info):
                rgba = decoded.convert("RGBA")
                background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                background.alpha_composite(rgba)
                decoded = background.convert("RGB")
            else:
                decoded = decoded.convert("RGB")
            decoded.thumbnail((MAX_OUTPUT_DIMENSION, MAX_OUTPUT_DIMENSION), Image.Resampling.LANCZOS)
            width, height = decoded.size

            encoded = b""
            for quality in (88, 82, 76, 70, 64):
                out = BytesIO()
                decoded.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
                encoded = out.getvalue()
                if len(encoded) <= MAX_OUTPUT_BYTES:
                    break
            if len(encoded) > MAX_OUTPUT_BYTES:
                raise ValueError(f"Das Bild kann nicht sicher auf maximal {MAX_OUTPUT_BYTES // 1000} KB normalisiert werden. Bitte verkleinere oder stärker komprimiere es.")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Die Datei konnte nicht als gültiges Bild gelesen werden. Bitte verwende eine unveränderte JPEG-, PNG- oder WebP-Datei.") from exc

    return SanitizedImage(
        original_name=filename,
        mime_type="image/jpeg",
        content=encoded,
        sha256=hashlib.sha256(encoded).hexdigest(),
        width=width,
        height=height,
    )


# Compatibility aliases for the product gallery API.
SanitizedProductImage = SanitizedImage
sanitize_product_image = sanitize_image
