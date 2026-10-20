from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

OUT = Path(__file__).resolve().parent / "katya.ico"

SS = 1024
FINAL = 256

BG_TOP = np.array([14, 18, 24], dtype=np.float32)
BG_BOT = np.array([7, 10, 14], dtype=np.float32)
CYAN = (34, 211, 238)
GREEN = (52, 211, 153)


def _font(size):
    for name in ("consolab.ttf", "consola.ttf", "arialbd.ttf", "segoeuib.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


# gradient background
grad = np.zeros((SS, SS, 3), dtype=np.float32)
for y in range(SS):
    t = y / (SS - 1)
    grad[y, :, :] = BG_TOP * (1 - t) + BG_BOT * t
base = Image.fromarray(grad.astype(np.uint8), "RGB").convert("RGBA")

radius = int(SS * 0.22)
mask = Image.new("L", (SS, SS), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, SS - 1, SS - 1], radius=radius, fill=255)
base.putalpha(mask)

img = base
d = ImageDraw.Draw(img)

# scan lines
lines = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
ld = ImageDraw.Draw(lines)
for y in range(0, SS, 36):
    ld.line([(0, y), (SS, y - SS)], fill=(255, 255, 255, 10), width=2)
lines.putalpha(Image.composite(lines.getchannel("A"), Image.new("L", (SS, SS), 0), mask))
img = Image.alpha_composite(img, lines)

# inner border
d = ImageDraw.Draw(img)
d.rounded_rectangle([SS * 0.055, SS * 0.055, SS * 0.945, SS * 0.945],
                    radius=int(radius * 0.8), outline=(30, 44, 56, 255), width=6)

# corner brackets
bw = 13
L = int(SS * 0.22)
for (cx, cy, sx, sy, col) in [
    (int(SS * 0.13), int(SS * 0.13), 1, 1, CYAN),
    (int(SS * 0.87), int(SS * 0.13), -1, 1, GREEN),
    (int(SS * 0.13), int(SS * 0.87), 1, -1, GREEN),
    (int(SS * 0.87), int(SS * 0.87), -1, -1, CYAN),
]:
    d.line([(cx, cy), (cx + sx * L, cy)], fill=col + (235,), width=bw)
    d.line([(cx, cy), (cx, cy + sy * L)], fill=col + (235,), width=bw)

# glyph mask
f = _font(int(SS * 0.58))
glyph = Image.new("L", (SS, SS), 0)
ImageDraw.Draw(glyph).text((SS // 2, int(SS * 0.52)), "K", font=f, fill=255, anchor="mm")

# glow behind glyph
glow = Image.new("RGBA", (SS, SS), CYAN + (0,))
glow.putalpha(glyph.point(lambda a: int(a * 0.85)))
glow = glow.filter(ImageFilter.GaussianBlur(30))
img = Image.alpha_composite(img, glow)

# vertical gradient fill for glyph
fill = np.zeros((SS, SS, 4), dtype=np.uint8)
for y in range(SS):
    t = y / (SS - 1)
    r = int(CYAN[0] * (1 - t) + GREEN[0] * t)
    g = int(CYAN[1] * (1 - t) + GREEN[1] * t)
    b = int(CYAN[2] * (1 - t) + GREEN[2] * t)
    fill[y, :, :] = (r, g, b, 255)
fill = Image.fromarray(fill, "RGBA")
glyph_rgba = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
glyph_rgba.paste(fill, (0, 0), glyph)
img = Image.alpha_composite(img, glyph_rgba)

# status dot with glow
d = ImageDraw.Draw(img)
dot_r = int(SS * 0.052)
dcx, dcy = int(SS * 0.78), int(SS * 0.22)
dg = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
ImageDraw.Draw(dg).ellipse([dcx - dot_r * 2, dcy - dot_r * 2, dcx + dot_r * 2, dcy + dot_r * 2],
                           fill=GREEN + (110,))
dg = dg.filter(ImageFilter.GaussianBlur(20))
img = Image.alpha_composite(img, dg)
d = ImageDraw.Draw(img)
d.ellipse([dcx - dot_r, dcy - dot_r, dcx + dot_r, dcy + dot_r], fill=GREEN + (255,))

master = img.resize((FINAL, FINAL), Image.LANCZOS)
sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
master.save(OUT, format="ICO", sizes=sizes)
print("saved", OUT, OUT.stat().st_size, "bytes")
