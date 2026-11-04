"""Home-screen icon, light: flat white tile, black house-over-server glyph at ~60% of the tile (like Apple's own icons). No gradient."""
import sys
from PIL import Image, ImageDraw
def make(size, path, frac=0.70):
    S = size * 4
    img = Image.new("RGB", (S, S), "white"); d = ImageDraw.Draw(img)
    k = frac * S / 1600; off = (S - 1600 * k) / 2  # glyph spans 200..1800 of a 2000 grid
    P = lambda x, y: (off + (x - 200) * k, off + (y - 200) * k)
    box = lambda x0, y0, x1, y1: [*P(x0, y0), *P(x1, y1)]
    circ = lambda cx, cy, r: box(cx - r, cy - r, cx + r, cy + r)
    d.polygon([P(*p) for p in [(1000, 200), (1800, 880), (1640, 880), (1640, 1140), (360, 1140), (360, 880), (200, 880)]], fill="black")
    d.ellipse(circ(1000, 760, 70), fill="white")
    for y in (1220, 1550):
        d.rounded_rectangle(box(360, y, 1640, y + 250), radius=40 * k, fill="black")
        d.ellipse(circ(520, y + 125, 50), fill="white")
        d.rounded_rectangle(box(1160, y + 97, 1480, y + 153), radius=28 * k, fill="white")
    img.resize((size, size), Image.LANCZOS).save(path)
out = sys.argv[1]
make(180, f"{out}/icon-180.png"); make(512, f"{out}/icon-512.png")
make(32, f"{out}/favicon-32.png", 0.80)
