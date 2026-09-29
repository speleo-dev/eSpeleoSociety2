"""Yearly sticker ("ročná známka") for the eCP – the hero image of the Google Wallet pass.

Ported from the original application: a 256×256 grayscale template (transparent background,
#000000 border, #606060 light and #404040 dark background) is coloured with a random hue and soft wave
patterns, so every year looks different; the year is split around the patch (e.g. "20" patch "26").
The random choices come from `seed`, so a preview and the deployed sticker are identical.
"""

import colorsys
import io
import math
import random

from PIL import Image, ImageDraw, ImageFont, ImageOps

from ess.cards import STATIC
from ess.services.access import DomainError

SIZE = (500, 120)
PATCH = 100
TEMPLATE_SIZE = (256, 256)
_BORDER, _LIGHT, _DARK = (0, 0, 0), (96, 96, 96), (64, 64, 64)


def default_template() -> bytes:
    return (STATIC / "sticker-template.png").read_bytes()


def check_template(data: bytes) -> bytes:
    """An uploaded template must be a 256×256 PNG with the three template greys."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG" or image.size != TEMPLATE_SIZE:
                raise DomainError("invalid_sticker_template")
            rgba = image.convert("RGBA")
    except DomainError:
        raise
    except Exception:
        raise DomainError("invalid_sticker_template") from None
    colours = {c[:3] for _count, c in rgba.getcolors(maxcolors=256 * 256) or [] if c[3] > 0}
    if not ({_BORDER, _LIGHT, _DARK} & colours):
        raise DomainError("invalid_sticker_template")
    out = io.BytesIO()
    rgba.save(out, format="PNG")  # re-encoded: no metadata, no foreign chunks
    return out.getvalue()


def _hex(colour: str) -> tuple[int, int, int]:
    colour = colour.lstrip("#")
    return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))


def _patch(template: bytes, rng: random.Random) -> Image.Image:
    image = Image.open(io.BytesIO(template)).convert("RGBA")
    width, height = image.size
    border_hue = rng.random()
    bg_hue = (border_hue + 0.5) % 1.0
    hls = {_BORDER: (border_hue, 0.5, 1.0), _LIGHT: (bg_hue, 0.7, 0.45), _DARK: (bg_hue, 0.4, 0.35)}
    a1, p1, f1 = rng.uniform(0, math.pi), rng.uniform(0, 2 * math.pi), rng.uniform(2.5, 4)
    a2, p2, f2 = rng.uniform(0, math.pi), rng.uniform(0, 2 * math.pi), rng.uniform(1.0, 1.5)
    src, out = image.load(), Image.new("RGBA", image.size, (0, 0, 0, 0))
    dst = out.load()
    for j in range(height):
        yy = -math.pi + 2 * math.pi * j / (height - 1)
        for i in range(width):
            r, g, b, a = src[i, j]
            if a == 0 or (r, g, b) not in hls:
                continue
            xx = -math.pi + 2 * math.pi * i / (width - 1)
            h, lum, s = hls[(r, g, b)]
            if (r, g, b) == _BORDER:
                lum += math.sin((xx * math.cos(a1) + yy * math.sin(a1)) * f1 + p1) * 0.15
            else:
                lum += (math.sin((xx * math.cos(a2) + yy * math.sin(a2)) * f2 + p2) + 1) / 2 * 0.25
            rr, gg, bb = colorsys.hls_to_rgb(h, min(max(lum, 0.1), 0.9), s)
            dst[i, j] = (round(rr * 255), round(gg * 255), round(bb * 255), 255)
    return out


def generate_sticker(template: bytes, year: int, text_colour: str = "#FFFFFF", background: str = "transparent",
                     seed: int = 0) -> bytes:
    rng = random.Random(seed)
    patch = ImageOps.contain(_patch(template, rng), (PATCH, PATCH))
    fill = (0, 0, 0, 0) if background == "transparent" else (*_hex(background), 255)
    sticker = Image.new("RGBA", SIZE, fill)
    px, py = (SIZE[0] - patch.width) // 2, (SIZE[1] - patch.height) // 2
    sticker.alpha_composite(patch, (px, py))
    draw = ImageDraw.Draw(sticker)
    font = ImageFont.truetype(str(STATIC / "fonts" / "DejaVuSans-Bold.ttf"), 72)
    text = _hex(text_colour)
    h, lum, _s = colorsys.rgb_to_hls(*(255 - c for c in text))  # contrasting outline, as in the original
    outline = tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, lum * 0.2, 1.0))
    year_text = str(year)
    left, right = year_text[: len(year_text) // 2], year_text[len(year_text) // 2:]
    left_w = draw.textlength(left, font=font)
    draw.text((px - 10 - left_w, SIZE[1] // 2), left, font=font, fill=text, anchor="lm", stroke_width=3,
              stroke_fill=outline)
    draw.text((px + patch.width + 10, SIZE[1] // 2), right, font=font, fill=text, anchor="lm", stroke_width=3,
              stroke_fill=outline)
    out = io.BytesIO()
    sticker.save(out, format="PNG", optimize=True)
    return out.getvalue()
