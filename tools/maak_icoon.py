"""Draws korad.ico from scratch, so the origin of the icon is known: this script is the source.

    py tools/maak_icoon.py

A dark tile with the ring of the meters, running from red through amber to green, and a lightning bolt in the middle.
Small sizes get a thicker ring and bolt, so they stay readable in the taskbar.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

MATEN = (16, 24, 32, 48, 64, 128, 256)
STOPS = ((0.0, (239, 68, 68)), (0.55, (245, 158, 11)), (1.0, (34, 197, 94)))
BLIKSEM = ((0.56, 0.21), (0.34, 0.54), (0.48, 0.54), (0.42, 0.79), (0.66, 0.43), (0.52, 0.43))
START, SWEEP = 135.0, 270.0


def kleur(f: float) -> tuple[int, int, int]:
    for (f1, k1), (f2, k2) in zip(STOPS, STOPS[1:]):
        if f <= f2:
            t = (f - f1) / (f2 - f1)
            return tuple(round(a + (b - a) * t) for a, b in zip(k1, k2))
    return STOPS[-1][1]


def teken(maat: int) -> Image.Image:
    ss = 8
    s = maat * ss
    klein = maat <= 32
    tegel = Image.new("L", (s, s), 0)
    ImageDraw.Draw(tegel).rounded_rectangle((0, 0, s - 1, s - 1), radius=s * 0.22, fill=255)
    beeld = Image.new("RGBA", (s, s), (23, 27, 33, 255))

    dikte = s * (0.13 if klein else 0.085)
    straal = s * (0.40 if klein else 0.375)
    midden = s / 2
    ring = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(ring)
    stappen = 240
    for n in range(stappen):
        a = START + SWEEP * n / stappen
        d.arc((midden - straal, midden - straal, midden + straal, midden + straal), a, a + SWEEP / stappen + 0.8,
              fill=kleur(n / stappen) + (255,), width=round(dikte))
    for f in (0.0, 1.0):      # ronde uiteinden
        a = math.radians(START + SWEEP * f)
        x, y = midden + (straal - dikte / 2) * math.cos(a), midden + (straal - dikte / 2) * math.sin(a)
        d.ellipse((x - dikte / 2, y - dikte / 2, x + dikte / 2, y + dikte / 2), fill=kleur(f) + (255,))
    beeld.alpha_composite(ring)

    vergroot = 1.2 if klein else 1.0
    punten = [(midden + (x - 0.5) * s * vergroot, midden + (y - 0.5) * s * vergroot) for x, y in BLIKSEM]
    ImageDraw.Draw(beeld).polygon(punten, fill=(248, 250, 252, 255))
    beeld.putalpha(ImageChops.multiply(beeld.getchannel("A"), tegel))
    return beeld.resize((maat, maat), Image.LANCZOS)


def main() -> None:
    uit = Path(__file__).resolve().parent.parent / "korad.ico"
    beelden = [teken(m) for m in MATEN]
    beelden[-1].save(uit, format="ICO", sizes=[(m, m) for m in MATEN], append_images=beelden[:-1])
    if len(sys.argv) > 1:      # voorbeeld op ware grootte en vergroot
        vel = Image.new("RGBA", (760, 300), (240, 240, 240, 255))
        vel.alpha_composite(beelden[-1], (22, 22))
        x = 300
        for m, b in zip(MATEN, beelden):
            if m <= 64:
                vel.alpha_composite(b, (x, 30))
                vel.alpha_composite(b.resize((m * 3, m * 3), Image.NEAREST) if m <= 32 else b, (x, 110))
                x += max(m, m * 3 if m <= 32 else m) + 18
        vel.save(sys.argv[1])


if __name__ == "__main__":
    main()
