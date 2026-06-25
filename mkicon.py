#!/usr/bin/env python3
"""Draw the Skill Factory launcher icon -> assets/icon.png (1024). Attached to the .command
by setup-launcher.sh (sips + Rez + SetFile). Stdlib + PIL only."""
import math
import os

from PIL import Image, ImageDraw

S = 1024
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def gradient(size, top, bot):
    img = Image.new("RGB", (1, size))
    px = img.load()
    for y in range(size):
        t = y / (size - 1)
        px[0, y] = tuple(round(top[i] + (bot[i] - top[i]) * t) for i in range(3))
    return img.resize((size, size))


def rounded_mask(size, rad):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], rad, fill=255)
    return m


def gear(layer, cx, cy, R, r, hole, teeth, fill):
    d = ImageDraw.Draw(layer)
    pts = []
    for i in range(teeth):
        for frac, rad in ((0.0, r), (0.30, R), (0.50, R), (0.80, r)):
            a = 2 * math.pi * (i + frac) / teeth
            pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
    d.polygon(pts, fill=fill)
    d.ellipse([cx - hole, cy - hole, cx + hole, cy + hole], fill=(0, 0, 0, 0))


def sparkle(layer, cx, cy, R, fill):
    d = ImageDraw.Draw(layer)
    w = R * 0.16
    d.polygon([(cx, cy - R), (cx + w, cy), (cx, cy + R), (cx - w, cy)], fill=fill)  # vertical
    d.polygon([(cx - R, cy), (cx, cy + w), (cx + R, cy), (cx, cy - w)], fill=fill)  # horizontal


def main():
    os.makedirs(OUT, exist_ok=True)
    bg = gradient(S, (124, 92, 255), (44, 28, 96))          # violet -> deep indigo
    bg.putalpha(rounded_mask(S, int(S * 0.225)))            # squircle-ish tile

    fg = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gear(fg, S * 0.46, S * 0.54, S * 0.30, S * 0.235, S * 0.105, 9, (255, 255, 255, 255))
    sparkle(fg, S * 0.74, S * 0.30, S * 0.11, (255, 255, 255, 235))
    sparkle(fg, S * 0.84, S * 0.45, S * 0.05, (255, 255, 255, 190))

    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(bg, (0, 0), bg)
    out = Image.alpha_composite(out, fg)
    path = os.path.join(OUT, "icon.png")
    out.save(path)
    print("wrote", path)


if __name__ == "__main__":
    main()
