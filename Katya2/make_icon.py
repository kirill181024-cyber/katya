from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "katya.ico"
SIZE = 256

BG = (11, 14, 18, 255)
ACCENT = (34, 211, 238, 255)
ACCENT2 = (52, 211, 153, 255)


def font(size):
    for name in ("consola.ttf", "arialbd.ttf", "segoeuib.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

d.rounded_rectangle([6, 6, SIZE - 6, SIZE - 6], radius=52, fill=BG,
                    outline=(30, 40, 51, 255), width=3)

for i in range(SIZE):
    a = int(28 * (i / SIZE))
    d.line([(6, i), (SIZE - 6, i)], fill=(0, 229, 255, a))

glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
gd.ellipse([150, 150, 250, 250], fill=(34, 211, 238, 70))
img = Image.alpha_composite(img, glow)
d = ImageDraw.Draw(img)

d.rounded_rectangle([26, 60, 42, 196], radius=8, fill=ACCENT)
d.line([(42, 128), (150, 60)], fill=ACCENT, width=20)
d.line([(42, 128), (150, 196)], fill=ACCENT, width=20)

f = font(120)
d.text((150, 128), "К", font=f, fill=ACCENT2, anchor="mm")

dot = (34, 211, 238, 255)
d.ellipse([186, 44, 214, 72], fill=dot)

glow2 = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
ImageDraw.Draw(glow2).ellipse([30, 116, 78, 140], fill=(52, 211, 153, 90))
img = Image.alpha_composite(img, glow2)

sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save(OUT, format="ICO", sizes=sizes)
print("saved", OUT, OUT.stat().st_size, "bytes")
