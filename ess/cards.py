"""PDF "Kartička SSS" – printable card for members without a smartphone (one calendar year).

The card is printed on A4 at the real ID-1 size (85.6 × 54 mm) with a cutting frame. Its QR code leads
to a page that shows only "Člen Slovenskej speleologickej spoločnosti" and "Členské zaplatené na rok XXXX".
"""

import io
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import qrcode
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
