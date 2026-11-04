#!/usr/bin/env python3
"""Render assets/icon_1024.png — an arc-reactor style orb on a dark squircle."""
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 1024
OUT = Path(__file__).resolve().parent.parent / "assets" / "icon_1024.png"
CYAN = (63, 210, 255)


def squircle_mask(size, inset, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([inset, inset, size - inset, size - inset], radius=radius, fill=255)
    return m


def main():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # background gradient
    bg = Image.new("RGBA", (S, S))
    d = ImageDraw.Draw(bg)
    for y in range(S):
        t = y / S
        d.line([(0, y), (S, y)], fill=(int(8 + 6 * t), int(14 + 8 * t), int(22 + 10 * t), 255))
    img.paste(bg, (0, 0), squircle_mask(S, 100, 185))

    c = S // 2
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse([c - 300, c - 300, c + 300, c + 300], fill=(*CYAN, 60))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    img.alpha_composite(glow)

    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    L = ImageDraw.Draw(layer)
    # outer tick ring
    for i in range(72):
        a = i / 72 * 2 * math.pi
        r1, r2 = 330, 350 if i % 6 else 365
        L.line([(c + r1 * math.cos(a), c + r1 * math.sin(a)), (c + r2 * math.cos(a), c + r2 * math.sin(a))],
               fill=(*CYAN, 150), width=5)
    # segmented arcs
    for r, w, segs, gap, alpha in [(285, 22, 3, 22, 230), (225, 10, 10, 12, 170), (175, 6, 24, 6, 140)]:
        span = 360 / segs
        for k in range(segs):
            L.arc([c - r, c - r, c + r, c + r], start=k * span + gap / 2, end=(k + 1) * span - gap / 2,
                  fill=(*CYAN, alpha), width=w)
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(1.2)))
    bloom = layer.filter(ImageFilter.GaussianBlur(14))
    img.alpha_composite(bloom)

    core = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    k = ImageDraw.Draw(core)
    for r, col in [(130, (*CYAN, 70)), (95, (*CYAN, 160)), (62, (170, 236, 255, 235)), (34, (255, 255, 255, 255))]:
        k.ellipse([c - r, c - r, c + r, c + r], fill=col)
    img.alpha_composite(core.filter(ImageFilter.GaussianBlur(10)))

    # clip everything (glow included) to the squircle tile
    from PIL import ImageChops
    mask = squircle_mask(S, 100, 185)
    img.putalpha(ImageChops.multiply(img.getchannel("A"), mask))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT)
    print(OUT)


if __name__ == "__main__":
    sys.exit(main())
