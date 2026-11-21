"""Draw the web client icons in web/icons (serif R, accent on --bg). Run from the repo root."""

from PIL import Image, ImageDraw, ImageFont

fonts = ["web/fonts/libre-caslon-text.woff2"]
BG = (11, 15, 20)
FG = (61, 220, 132)


def make(size, glyph_frac, name, ring=False):
    im = Image.new("RGB", (size, size), BG)
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(fonts[0], int(size * glyph_frac))
    if ring:
        m = size * (1 - glyph_frac * 1.25) / 2
        w = max(2, size // 40)
        d.ellipse([m, m, size - m, size - m], outline=FG, width=w)
    d.text((size / 2, size / 2), "R", font=f, fill=FG, anchor="mm")
    im.save(f"web/icons/{name}", optimize=True)


print("font", fonts[0])
make(192, 0.66, "icon-192.png")
make(512, 0.66, "icon-512.png")
make(512, 0.48, "icon-maskable-512.png")
make(180, 0.66, "apple-touch-icon.png")
make(32, 0.9, "favicon-32.png", ring=False)
