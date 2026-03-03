#!/usr/bin/env python3
"""Generate a transparent PNG of the ccui pixel-art logo."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

LOGO_LINES = [
    "                  \u2580\u2580",
    "\u2584\u2588\u2588\u2588\u2588 \u2584\u2588\u2588\u2588\u2588 \u2588\u2588 \u2588\u2588 \u2588\u2588",
    "\u2588\u2588    \u2588\u2588    \u2588\u2588 \u2588\u2588 \u2588\u2588",
    "\u2580\u2588\u2588\u2588\u2588 \u2580\u2588\u2588\u2588\u2588 \u2580\u2588\u2588\u2588\u2580 \u2588\u2588",
]

FONT_SIZE = 48
FG = (217, 119, 87)  # Claude brand color #D97757

FONT_PATHS = [
    "/System/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "DejaVuSansMono.ttf",
]

OUT = Path(__file__).resolve().parent.parent / "assets" / "logo.png"


def load_font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, FONT_SIZE)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> None:
    font = load_font()

    # Render at large size, then measure
    tmp = Image.new("RGBA", (2000, 600), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tmp)

    line_height = FONT_SIZE + 4
    for i, line in enumerate(LOGO_LINES):
        draw.text((0, i * line_height), line, fill=(*FG, 255), font=font)

    bbox = tmp.getbbox()
    if not bbox:
        print("Error: nothing rendered")
        return

    pad = 8
    crop = (
        max(0, bbox[0] - pad),
        max(0, bbox[1] - pad),
        bbox[2] + pad,
        bbox[3] + pad,
    )
    img = tmp.crop(crop)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, "PNG")
    print(f"Saved {OUT}  ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
