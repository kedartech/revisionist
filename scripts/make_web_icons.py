"""Draw the web client icons in web/icons from the Revisionist logo (bronze quill-dagger on black).

Usage, from the repo root: python scripts/make_web_icons.py <logo image>
The source is the square logo file (mark on black); it is kept as web/icons/logo-1024.png.
Near-black JPEG noise is flattened to pure black. The maskable icon shrinks the mark so it fits
Android's launcher crop (the safe zone is the central circle 80 percent of the width across).
"""

import sys
from pathlib import Path

from PIL import Image, ImageChops

OUT = Path("web/icons")
BLACK = (0, 0, 0)
SIZES = [  # file, pixels, share of the frame the logo fills
    ("logo-1024.png", 1024, 1.0),
    ("icon-192.png", 192, 1.0),
    ("icon-512.png", 512, 1.0),
    ("icon-maskable-512.png", 512, 0.68),
    ("apple-touch-icon.png", 180, 1.0),
    ("favicon-32.png", 32, 1.0),
]


def flatten(im: Image.Image) -> Image.Image:
    r, g, b = im.split()
    dark = ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda v: 255 if v < 28 else 0)
    im.paste(BLACK, (0, 0, im.width, im.height), dark)
    return im


def tight(logo: Image.Image, margin: float = 0.06) -> Image.Image:
    """The logo cropped square to the mark, for sizes too small to spare the border."""
    x0, y0, x1, y1 = logo.getbbox() or (0, 0, logo.width, logo.height)
    side = max(x1 - x0, y1 - y0) * (1 + 2 * margin)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return logo.crop(
        (round(cx - side / 2), round(cy - side / 2), round(cx + side / 2), round(cy + side / 2))
    )


def icon(logo: Image.Image, size: int, share: float) -> Image.Image:
    inner = round(size * share)
    out = Image.new("RGB", (size, size), BLACK)
    pad = (size - inner) // 2
    out.paste(logo.resize((inner, inner), Image.Resampling.LANCZOS), (pad, pad))
    return out


def main() -> None:
    logo = flatten(Image.open(sys.argv[1]).convert("RGB"))
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size, share in SIZES:
        source = tight(logo) if size <= 64 else logo
        icon(source, size, share).save(OUT / name, optimize=True)


if __name__ == "__main__":
    main()
