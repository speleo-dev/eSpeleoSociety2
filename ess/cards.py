"""The SSS card ("Kartička SSS") – card for members without a smartphone (one calendar year), as PDF or PNG.

PDF: printed on A4 at the real ID-1 size (85.6 × 54 mm) with a cutting frame. PNG: the card alone
(1011 × 638 px, the same layout), e.g. to keep in a phone. Its QR code leads
to a page that shows only "Člen Slovenskej speleologickej spoločnosti" and "Členské zaplatené na rok XXXX".
"""

import io
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

STATIC = Path(__file__).parent / "static"
CARD_W, CARD_H = 85.6 * mm, 54 * mm
DARK = (0x0B / 255, 0x4A / 255, 0x46 / 255)  # colours of the original design
GOLD = (0xD5 / 255, 0xA9 / 255, 0x3F / 255)


@dataclass
class CardContent:
    full_name: str
    club_name: str
    card_number: str | None
    year: int
    verify_url: str


@lru_cache
def _fonts() -> None:
    # DejaVu covers Slovak diacritics (the built-in PDF fonts do not).
    pdfmetrics.registerFont(TTFont("DejaVu", str(STATIC / "fonts" / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(STATIC / "fonts" / "DejaVuSans-Bold.ttf")))


def _qr(url: str) -> ImageReader:
    image = qrcode.make(url, box_size=8, border=1)
    out = io.BytesIO()
    image.save(out, format="PNG")
    out.seek(0)
    return ImageReader(out)


def _fit(c: canvas.Canvas, text: str, font: str, size: float, width: float) -> float:
    """Largest font size (down to 5 pt) at which the text fits the width."""
    while size > 5 and c.stringWidth(text, font, size) > width:
        size -= 0.25
    return size


def render_card_pdf(card: CardContent) -> bytes:
    _fonts()
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4)
    c.setTitle(f"Kartička SSS {card.year}")
    page_w, page_h = A4
    x, y = (page_w - CARD_W) / 2, page_h - 40 * mm - CARD_H

    c.setStrokeColorRGB(0.6, 0.6, 0.6)
    c.setDash(2, 2)
    c.roundRect(x, y, CARD_W, CARD_H, 3 * mm)  # cutting frame
    c.setDash()

    c.setFillColorRGB(*DARK)
    c.roundRect(x, y + CARD_H - 13 * mm, CARD_W, 13 * mm, 3 * mm, stroke=0, fill=1)
    c.rect(x, y + CARD_H - 13 * mm, CARD_W, 4 * mm, stroke=0, fill=1)
    c.drawImage(ImageReader(str(STATIC / "logo-sss.png")), x + 2.5 * mm, y + CARD_H - 11.5 * mm,
                10 * mm, 10 * mm, mask="auto")
    c.setFillColorRGB(1, 1, 1)
    c.setFont("DejaVu-Bold", 7.5)
    c.drawString(x + 14 * mm, y + CARD_H - 6 * mm, "Slovenská speleologická spoločnosť")
    c.setFillColorRGB(*GOLD)
    c.setFont("DejaVu-Bold", 7)
    c.drawString(x + 14 * mm, y + CARD_H - 10 * mm, f"Členská kartička {card.year}")

    qr_size = 30 * mm
    c.drawImage(_qr(card.verify_url), x + CARD_W - qr_size - 3 * mm, y + 5 * mm, qr_size, qr_size)

    text_w = CARD_W - qr_size - 9 * mm
    c.setFillColorRGB(0.1, 0.1, 0.1)
    size = _fit(c, card.full_name, "DejaVu-Bold", 10, text_w)
    c.setFont("DejaVu-Bold", size)
    c.drawString(x + 4 * mm, y + CARD_H - 20 * mm, card.full_name)
    c.setFont("DejaVu", _fit(c, card.club_name, "DejaVu", 7, text_w))
    c.drawString(x + 4 * mm, y + CARD_H - 25 * mm, card.club_name)
    c.setFont("DejaVu", 7)
    if card.card_number:
        c.drawString(x + 4 * mm, y + CARD_H - 30 * mm, f"Číslo preukazu: {card.card_number}")
    c.drawString(x + 4 * mm, y + 9 * mm, f"Platí na rok {card.year}")
    c.setFont("DejaVu", 5.5)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawString(x + 4 * mm, y + 5 * mm, "Overenie: naskenujte QR kód")

    c.setFont("DejaVu", 8)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    c.drawCentredString(page_w / 2, y - 8 * mm, "Kartičku vystrihnite po prerušovanej čiare.")
    c.showPage()
    c.save()
    return out.getvalue()


# --- PNG -------------------------------------------------------------------------------------------------

PNG_SIZE = (1011, 638)  # ID-1 ratio, ~300 dpi
_PX = PNG_SIZE[0] / 85.6  # pixels per millimetre


def _font(bold: bool, size_mm: float) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(str(STATIC / "fonts" / name), max(8, round(size_mm * _PX)))


def _fit_font(draw: ImageDraw.ImageDraw, text: str, bold: bool, size_mm: float, width_px: float):
    while size_mm > 1.8:
        font = _font(bold, size_mm)
        if draw.textlength(text, font=font) <= width_px:
            return font
        size_mm -= 0.1
    return _font(bold, size_mm)


def render_card_png(card: CardContent) -> bytes:
    """The same card as an image (no page, no cutting frame)."""
    w, h = PNG_SIZE
    mm_ = lambda v: round(v * _PX)  # noqa: E731
    dark = tuple(round(c * 255) for c in DARK)
    gold = tuple(round(c * 255) for c in GOLD)
    image = Image.new("RGB", PNG_SIZE, "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, w, mm_(13)), fill=dark)
    with Image.open(STATIC / "logo-sss.png") as logo:
        logo = logo.convert("RGBA").resize((mm_(10), mm_(10)))
        image.paste(logo, (mm_(2.5), mm_(1.5)), logo)
    draw.text((mm_(14), mm_(2.2)), "Slovenská speleologická spoločnosť", font=_font(True, 2.7), fill="white")
    draw.text((mm_(14), mm_(6.8)), f"Členská kartička {card.year}", font=_font(True, 2.5), fill=gold)

    qr_size = mm_(30)
    qr = qrcode.make(card.verify_url, box_size=10, border=1).convert("RGB").resize((qr_size, qr_size), Image.NEAREST)
    image.paste(qr, (w - qr_size - mm_(3), h - qr_size - mm_(5)))

    text_w = w - qr_size - mm_(9)
    x = mm_(4)
    draw.text((x, mm_(16.5)), card.full_name, font=_fit_font(draw, card.full_name, True, 3.5, text_w), fill=(25, 25, 25))
    draw.text((x, mm_(22.5)), card.club_name, font=_fit_font(draw, card.club_name, False, 2.5, text_w), fill=(25, 25, 25))
    if card.card_number:
        draw.text((x, mm_(27.5)), f"Číslo preukazu: {card.card_number}", font=_font(False, 2.5), fill=(25, 25, 25))
    draw.text((x, h - mm_(12)), f"Platí na rok {card.year}", font=_font(False, 2.5), fill=(25, 25, 25))
    draw.text((x, h - mm_(7)), "Overenie: naskenujte QR kód", font=_font(False, 1.9), fill=(100, 100, 100))
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def render_card(card: CardContent, card_format: str) -> tuple[bytes, str, str]:
    """(data, MIME type, file name) in the requested format."""
    if card_format == "png":
        return render_card_png(card), "image/png", f"karticka-sss-{card.year}.png"
    return render_card_pdf(card), "application/pdf", f"karticka-sss-{card.year}.pdf"
