"""Small preview images of the eCP and the SSS card for the application page (fictional data only).

Run after a design change: `.venv/bin/python -m ess.tools.make_previews` – writes static/preview-*.png.
"""

import io
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont

from ess.cards import CardContent, render_card_png
from ess.stickers import default_template, generate_sticker

STATIC = Path(__file__).resolve().parent.parent / "static"
WIDTH = 240  # px; shown at half size for sharp screens
SAMPLE = "https://ess.example/sample"


def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(str(STATIC / "fonts" / name), size)


def card_preview() -> bytes:
    png = render_card_png(CardContent("Ján Vzorový", "JS Vzorová", "1234", 2027, SAMPLE))
    with Image.open(io.BytesIO(png)) as image:
        small = image.convert("RGB").resize((WIDTH * 2, round(image.height * WIDTH * 2 / image.width)), Image.LANCZOS)
    return _png(small)


def ecp_preview() -> bytes:
    """A simplified Google Wallet pass: header, sticker, a few fields and the QR code."""
    w, h, pad = WIDTH * 2, 760, 28
    image = Image.new("RGB", (w, h), (11, 74, 70))
    draw = ImageDraw.Draw(image)
    with Image.open(STATIC / "logo-sss.png") as logo:
        logo = logo.convert("RGBA").resize((56, 56))
        image.paste(logo, (pad, pad), logo)
    draw.text((pad + 70, pad + 14), "Slovenská speleologická spol.", font=_font(False, 20), fill="white")
    draw.text((pad, 110), "Ján Vzorový", font=_font(True, 36), fill="white")
    y = 175
    for label, value in (("Klub", "JS Vzorová"), ("Platný do", "31.12.2027")):
        draw.text((pad, y), label, font=_font(False, 18), fill=(190, 215, 210))
        draw.text((pad, y + 24), value, font=_font(True, 24), fill="white")
        y += 70
    qr = qrcode.make(SAMPLE, box_size=8, border=2).convert("RGB").resize((200, 200), Image.NEAREST)
    image.paste(qr, ((w - 200) // 2, 330))
    with Image.open(io.BytesIO(generate_sticker(default_template(), 2027, "#FFFFFF", "#D5A93F", seed=7))) as sticker:
        sticker = sticker.convert("RGBA").resize((w, round(sticker.height * w / sticker.width)))
        top = h - sticker.height
        image.paste(sticker, (0, top), sticker)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=36, fill=255)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(image, (0, 0), mask)
    return _png(out)


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def main() -> None:
    (STATIC / "preview-card.png").write_bytes(card_preview())
    (STATIC / "preview-ecp.png").write_bytes(ecp_preview())
    print("static/preview-card.png, static/preview-ecp.png")


if __name__ == "__main__":
    main()
