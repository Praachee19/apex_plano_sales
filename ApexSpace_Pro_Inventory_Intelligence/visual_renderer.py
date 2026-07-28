from __future__ import annotations

import re
import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from PIL import Image, ImageDraw, ImageFont, ImageOps

ACCENTS = {
    "APEX": "#E31E24",
    "VENTURINI": "#5B3A29",
    "NINO ROSSI": "#81A39A",
    "MOOCHIE": "#8B1E3F",
    "TWINKLER": "#6B4FA1",
}

ZONE_COLORS = {
    "Feature": "#E67E22",
    "Prime": "#2E7D32",
    "Secondary": "#2F6DA1",
    "Tertiary": "#777777",
}

SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def normalize_article_code(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def _safe_font(size: int, bold: bool = False):
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _load_image_bytes(raw: bytes) -> Image.Image | None:
    try:
        image = Image.open(BytesIO(raw)).convert("RGBA")
        return image
    except Exception:
        return None


def build_product_image_map(uploaded_files: Iterable[Any] | None = None, uploaded_zip: Any | None = None) -> dict[str, bytes]:
    """Map article-code file stems to raw image bytes.

    Accepted names: 91125.jpg, SKU-91125.png, or any file whose stem equals the
    article code after spaces, hyphens and punctuation are removed.
    """
    result: dict[str, bytes] = {}
    for uploaded in uploaded_files or []:
        name = getattr(uploaded, "name", "")
        suffix = Path(name).suffix.lower()
        if suffix not in SUPPORTED_IMAGE_EXTENSIONS:
            continue
        stem = normalize_article_code(Path(name).stem)
        if stem:
            result[stem] = uploaded.getvalue() if hasattr(uploaded, "getvalue") else uploaded.read()

    if uploaded_zip is not None:
        raw_zip = uploaded_zip.getvalue() if hasattr(uploaded_zip, "getvalue") else uploaded_zip.read()
        try:
            with zipfile.ZipFile(BytesIO(raw_zip)) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    suffix = Path(member.filename).suffix.lower()
                    if suffix not in SUPPORTED_IMAGE_EXTENSIONS:
                        continue
                    stem = normalize_article_code(Path(member.filename).stem)
                    if stem:
                        result[stem] = archive.read(member)
        except zipfile.BadZipFile:
            pass
    return result


def _make_white_transparent(image: Image.Image, threshold: int = 244) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = pixels[x, y]
            if r >= threshold and g >= threshold and b >= threshold:
                pixels[x, y] = (255, 255, 255, 0)
            elif a < 255:
                pixels[x, y] = (r, g, b, a)
    return rgba


def _fit_product_image(image: Image.Image, width: int, height: int) -> Image.Image:
    cleaned = _make_white_transparent(image)
    bbox = cleaned.getbbox()
    if bbox:
        cleaned = cleaned.crop(bbox)
    return ImageOps.contain(cleaned, (max(10, width), max(10, height)), method=Image.Resampling.LANCZOS)


def _label(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, accent: str, *, font_size: int) -> None:
    x, y, w, h = box
    font = _safe_font(font_size, bold=True)
    text_bbox = draw.textbbox((0, 0), text, font=font)
    tw = text_bbox[2] - text_bbox[0]
    th = text_bbox[3] - text_bbox[1]
    pad_x, pad_y = 4, 2
    lx = int(x + w / 2 - tw / 2 - pad_x)
    ly = int(y + h - th - 2 * pad_y)
    rx = int(x + w / 2 + tw / 2 + pad_x)
    by = int(y + h)
    draw.rounded_rectangle((lx, ly, rx, by), radius=4, fill=(255, 255, 255, 225), outline=accent, width=1)
    draw.text((lx + pad_x, ly + pad_y - 1), text, font=font, fill="#111111")


def render_visual_planogram(
    placements: pd.DataFrame,
    template: dict[str, Any],
    brand: str,
    store_name: str,
    product_images: dict[str, bytes] | None = None,
    *,
    show_article_codes: bool = True,
    show_scores: bool = False,
    show_zone_outlines: bool = False,
) -> tuple[Image.Image, dict[str, int]]:
    """Render allocations on top of the approved VM screenshot template."""
    asset = Path(template["asset_path"])
    if not asset.exists():
        raise FileNotFoundError(f"Visual template missing: {asset}")

    base = Image.open(asset).convert("RGBA")
    overlay = Image.new("RGBA", base.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    accent = ACCENTS.get(str(brand).upper(), "#E65A00")
    product_images = product_images or {}

    product_rows = placements[placements["position_type"] == "Product"].copy().reset_index(drop=True)
    product_rows["display_code"] = [f"A{i:03d}" for i in range(1, len(product_rows) + 1)]

    matched = 0
    missing = 0
    rendered = 0
    for _, row in product_rows.iterrows():
        box_value = row.get("box")
        if not isinstance(box_value, (list, tuple)) or len(box_value) != 4:
            continue
        x, y, w, h = [int(v) for v in box_value]
        if show_zone_outlines:
            draw.rounded_rectangle((x, y, x + w, y + h), radius=5, outline=ZONE_COLORS.get(str(row.get("zone")), accent), width=2)

        article_code = str(row.get("article_code", ""))
        key = normalize_article_code(article_code)
        raw = product_images.get(key)
        if raw:
            product = _load_image_bytes(raw)
            if product is not None:
                fitted = _fit_product_image(product, int(w * 0.95), int(h * 0.76))
                px = x + (w - fitted.width) // 2
                py = y + max(0, int(h * 0.03))
                overlay.alpha_composite(fitted, (px, py))
                matched += 1
            else:
                missing += 1
        else:
            missing += 1

        if show_article_codes:
            label = article_code
            if show_scores and pd.notna(row.get("commercial_score")):
                label = f"{article_code}  {float(row['commercial_score']):.0f}"
            max_chars = 15 if template.get("kind") == "wall" else 18
            _label(draw, (x, y, w, h), label[:max_chars], accent, font_size=8 if base.width < 900 else 11)
        rendered += 1

    # Fixture 1 repeats the four strongest articles on the front-view raisers.
    feature_positions = template.get("feature_positions", [])
    if feature_positions and not product_rows.empty:
        for (_, row), box in zip(product_rows.head(len(feature_positions)).iterrows(), feature_positions):
            x, y, w, h = [int(v) for v in box]
            key = normalize_article_code(row.get("article_code", ""))
            raw = product_images.get(key)
            if raw:
                product = _load_image_bytes(raw)
                if product is not None:
                    fitted = _fit_product_image(product, int(w * 0.95), int(h * 0.80))
                    overlay.alpha_composite(fitted, (x + (w - fitted.width) // 2, y + (h - fitted.height) // 2))
            if show_article_codes:
                _label(draw, (x, y, w, h), str(row.get("article_code", ""))[:15], accent, font_size=9)

    composite = Image.alpha_composite(base, overlay).convert("RGB")

    footer_h = 48 if composite.width < 1000 else 58
    canvas = Image.new("RGB", (composite.width, composite.height + footer_h), "white")
    canvas.paste(composite, (0, 0))
    footer_draw = ImageDraw.Draw(canvas)
    footer_draw.rectangle((0, composite.height, composite.width, composite.height + footer_h), fill="#F4F5F7")
    footer_font = _safe_font(11 if composite.width < 1000 else 15)
    footer_bold = _safe_font(12 if composite.width < 1000 else 16, bold=True)
    footer_draw.text((12, composite.height + 8), f"{template['name']}  |  {store_name}", font=footer_bold, fill="#222222")
    footer_draw.text(
        (12, composite.height + 27 if composite.width < 1000 else composite.height + 32),
        f"Generated {date.today().strftime('%d %b %Y')}  |  {len(product_rows)} selected articles  |  ApexSpace Pro",
        font=footer_font,
        fill="#555555",
    )

    return canvas, {"rendered": rendered, "images_matched": matched, "images_missing": missing}


def image_to_png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def image_to_pdf_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="PDF", resolution=150.0)
    return buffer.getvalue()
