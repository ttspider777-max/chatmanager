"""Тёмная новогодняя карточка ограбления в стиле «стеклянных» панелей (Pillow, всё рисуется кодом).
Шапка с профилем грабителя, большая панель с суммой, 4 карточки с деталями, еловые лапки и шар в углах.
Свой фон: положи PNG/JPG в assets/ (bg*.png / bg*.jpg). Свой шрифт для цифр: assets/font.ttf."""
import io
import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

BASE = Path(__file__).parent
ASSETS = BASE / "assets"
W, H = 960, 800
S = 2  # суперсэмплинг

_WIN = Path("C:/Windows/Fonts")
_LIN = Path("/usr/share/fonts/truetype/dejavu")
FONTS = {
    "black": [ASSETS / "font.ttf", _WIN / "seguibl.ttf", _WIN / "ariblk.ttf", _WIN / "segoeuib.ttf",
              _LIN / "DejaVuSans-Bold.ttf"],
    "bold": [_WIN / "segoeuib.ttf", _WIN / "arialbd.ttf", _LIN / "DejaVuSans-Bold.ttf"],
    "reg": [_WIN / "segoeui.ttf", _WIN / "arial.ttf", _LIN / "DejaVuSans.ttf"],
    "hand": [_WIN / "segoepr.ttf", _WIN / "comic.ttf", _LIN / "DejaVuSans.ttf"],
}
WHITE, GREY, DIM = (255, 255, 255), (150, 152, 158), (118, 120, 128)
GOLD = (255, 200, 64)
PINK = (255, 150, 190)


def _font(role: str, size: float) -> ImageFont.FreeTypeFont:
    for p in FONTS[role]:
        if p.exists():
            return ImageFont.truetype(str(p), int(size * S))
    return ImageFont.load_default()


def _fit_font(role, text, max_w, size, min_size=16, stretch=1.0):
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    while size > min_size:
        f = _font(role, size)
        if d.textlength(text, font=f) * stretch <= max_w * S:
            return f
        size -= 2
    return _font(role, min_size)


# ---------- примитивы ----------
def _vgrad(size, top, bot) -> Image.Image:
    g = Image.linear_gradient("L").resize(size)
    return Image.composite(Image.new("RGB", size, bot), Image.new("RGB", size, top), g)


def _disc(size: int) -> Image.Image:
    big = Image.new("L", (size * 2, size * 2), 0)
    ImageDraw.Draw(big).ellipse([0, 0, size * 2 - 1, size * 2 - 1], fill=255)
    return big.resize((size, size), Image.LANCZOS)


def _rr_mask(size, radius, outline=0) -> Image.Image:
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    if outline:
        d.rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, outline=255, width=outline)
    else:
        d.rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return m


def _background(rng: random.Random) -> Image.Image:
    size = (W * S, H * S)
    custom = sorted([*ASSETS.glob("bg*.png"), *ASSETS.glob("bg*.jpg"), *ASSETS.glob("bg*.jpeg")]) if ASSETS.exists() else []
    if custom:
        try:
            img = ImageOps.fit(Image.open(rng.choice(custom)).convert("RGB"), size)
            return Image.blend(img, Image.new("RGB", size, (14, 14, 16)), 0.6)
        except Exception:
            pass
    img = _vgrad(size, (36, 36, 40), (16, 16, 18))
    glow = Image.new("RGBA", size, (120, 124, 140, 0))
    ImageDraw.Draw(glow).ellipse([size[0] * 0.15, -size[1] * 0.25, size[0] * 0.85, size[1] * 0.35], fill=(120, 124, 140, 60))
    glow = glow.filter(ImageFilter.GaussianBlur(110 * S))
    img.paste(glow, (0, 0), glow)
    return img


def _snow(img: Image.Image, rng: random.Random):
    for blur, count, rmin, rmax, amin, amax in ((3.0, 14, 5, 9, 25, 55), (1.0, 40, 2, 3.5, 60, 120), (0.3, 70, 1, 2, 90, 170)):
        layer = Image.new("RGBA", img.size, (255, 255, 255, 0))
        d = ImageDraw.Draw(layer)
        for _ in range(count):
            x, y = rng.uniform(0, W * S), rng.uniform(0, H * S)
            r = rng.uniform(rmin, rmax) * S / 2
            d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, rng.randint(amin, amax)))
        layer = layer.filter(ImageFilter.GaussianBlur(blur))
        img.paste(layer, (0, 0), layer)


def _flake(d: ImageDraw.ImageDraw, cx, cy, r, alpha=70):
    """Контурная снежинка (тонкие линии)."""
    col = (255, 255, 255, alpha)
    for k in range(6):
        a = k * math.pi / 3
        x, y = cx + r * math.cos(a) * S, cy + r * math.sin(a) * S
        d.line([(cx, cy), (x, y)], fill=col, width=S)
        for t in (0.55,):
            bx, by = cx + r * t * math.cos(a) * S, cy + r * t * math.sin(a) * S
            for da in (-0.6, 0.6):
                d.line([(bx, by), (bx + r * 0.28 * math.cos(a + da) * S, by + r * 0.28 * math.sin(a + da) * S)],
                       fill=col, width=S)


def _flakes(img: Image.Image):
    layer = Image.new("RGBA", img.size, (255, 255, 255, 0))
    d = ImageDraw.Draw(layer)
    for x, y, r in ((22, 318, 11), (40, 190, 8), (14, 436, 9), (936, 330, 10), (924, 440, 8), (900, 250, 7)):
        _flake(d, x * S, y * S, r)
    img.paste(layer, (0, 0), layer)


def _stretch(mask: Image.Image, k: float) -> Image.Image:
    return mask if k == 1.0 else mask.resize((int(mask.width * k), mask.height), Image.LANCZOS)


def _text(img, x, y, text, font, fill=WHITE, anchor="l", spacing=0.0, stretch=1.0, grad=None, glow=0.0, rot=0.0):
    """Текст. anchor: l — x это левый край, c — центр. y — вертикальный центр.
    grad=(top, bottom) — вертикальный градиент, glow — сила свечения (0..1), stretch — растяжение по ширине."""
    d = ImageDraw.Draw(img)
    sp = spacing * S
    widths = [d.textlength(ch, font=font) for ch in text]
    total = sum(widths) + sp * (len(text) - 1)
    asc, desc = font.getmetrics()
    pad = 18 * S
    mask = Image.new("L", (int(total) + pad * 2, asc + desc + pad * 2), 0)
    md = ImageDraw.Draw(mask)
    cx = pad
    for ch, w in zip(text, widths):
        md.text((cx, pad), ch, font=font, fill=255)
        cx += w + sp
    mask = _stretch(mask, stretch)
    if rot:
        mask = mask.rotate(rot, resample=Image.BICUBIC, expand=True)
    w_, h_ = mask.size
    ox = int(x * S - w_ / 2) if anchor == "c" else int(x * S - pad * stretch)
    oy = int(y * S - h_ / 2)
    if glow:
        g = mask.filter(ImageFilter.GaussianBlur(14 * S)).point(lambda v: int(v * glow))
        img.paste(Image.new("RGB", mask.size, (255, 255, 255)), (ox, oy), g)
    src = _vgrad(mask.size, *grad) if grad else Image.new("RGB", mask.size, fill)
    img.paste(src, (ox, oy), mask)
    return ox / S, oy / S, w_ / S, h_ / S


def _text_w(text, font, stretch=1.0) -> float:
    return ImageDraw.Draw(Image.new("L", (1, 1))).textlength(text, font=font) * stretch / S


def _glass(img: Image.Image, box, radius=26, veil=0.07, blur=16):
    """Стеклянная карточка: размытый фон, лёгкая белая вуаль, блик сверху, тонкая светлая рамка."""
    x0, y0, x1, y1 = [int(v * S) for v in box]
    size = (x1 - x0, y1 - y0)
    crop = img.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(blur * S))
    crop = Image.blend(crop, Image.new("RGB", size, (255, 255, 255)), veil)
    m = _rr_mask(size, radius * S)
    img.paste(crop, (x0, y0), m)
    sheen = Image.linear_gradient("L").resize(size).transpose(Image.FLIP_TOP_BOTTOM).point(lambda v: int(v * 0.10))
    sheen = ImageChops.multiply(sheen, m)
    img.paste(Image.new("RGB", size, (255, 255, 255)), (x0, y0), sheen)
    edge = _rr_mask(size, radius * S, outline=S).point(lambda v: int(v * 0.17))
    img.paste(Image.new("RGB", size, (255, 255, 255)), (x0, y0), edge)


def _avatar(img: Image.Image, ava: Image.Image | None, name: str, cx, cy, r):
    size = int(r * 2 * S)
    if ava is None:
        ava = _vgrad((size, size), (214, 214, 220), (140, 140, 148))
        ImageDraw.Draw(ava).text((size / 2, size / 2 + size * 0.02), (name.strip()[:1] or "?").lower(),
                                 font=_font("black", r * 1.05), fill=WHITE, anchor="mm")
    else:
        ava = ImageOps.fit(ava.convert("RGB"), (size, size))
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([cx * S - size / 2, cy * S - size / 2 + 8 * S, cx * S + size / 2, cy * S + size / 2 + 8 * S],
                               fill=(0, 0, 0, 120))
    sh = sh.filter(ImageFilter.GaussianBlur(10 * S))
    img.paste(sh, (0, 0), sh)
    img.paste(ava, (int(cx * S - size / 2), int(cy * S - size / 2)), _disc(size))


# ---------- новогодний декор ----------
def _branch(img: Image.Image, rng: random.Random, x, y, angle, length):
    """Еловая лапка: ствол, хвоя пучками, снег. Угол в градусах (0 — вправо, 90 — вниз)."""
    d = ImageDraw.Draw(img)
    a = math.radians(angle)
    dx, dy = math.cos(a), math.sin(a)
    px, py = -dy, dx
    greens = [(16, 44, 34), (24, 62, 46), (32, 80, 58), (12, 34, 28)]
    d.line([(x * S, y * S), ((x + dx * length) * S, (y + dy * length) * S)], fill=(40, 28, 22), width=3 * S)
    n = int(length / 3.2)
    for i in range(n):
        t = i / n
        bx, by = x + dx * length * t, y + dy * length * t
        nl = (1 - t * 0.62) * 46
        for side in (-1, 1):
            for k in range(4):
                ang = side * (0.42 + 0.26 * k) + rng.uniform(-0.12, 0.12)
                ca, sa = math.cos(ang), math.sin(ang)
                ex = bx + (dx * ca - dy * sa) * nl * (0.55 + 0.2 * k)
                ey = by + (dx * sa + dy * ca) * nl * (0.55 + 0.2 * k)
                d.line([(bx * S, by * S), (ex * S, ey * S)], fill=rng.choice(greens), width=int(3 * S))
                if rng.random() < 0.45:
                    sx, sy = bx + (ex - bx) * rng.uniform(0.35, 0.9), by + (ey - by) * rng.uniform(0.35, 0.9)
                    r = rng.uniform(1.4, 2.8) * S
                    d.ellipse([sx * S - r, sy * S - r, sx * S + r, sy * S + r], fill=(238, 244, 252))


def _lights(img: Image.Image, pts):
    layer = Image.new("RGBA", img.size, (255, 214, 150, 0))
    d = ImageDraw.Draw(layer)
    for x, y in pts:
        r = 22 * S
        d.ellipse([x * S - r, y * S - r, x * S + r, y * S + r], fill=(255, 214, 150, 120))
    layer = layer.filter(ImageFilter.GaussianBlur(10 * S))
    img.paste(layer, (0, 0), layer)
    d = ImageDraw.Draw(img)
    for x, y in pts:
        d.ellipse([x * S - 5 * S, y * S - 5 * S, x * S + 5 * S, y * S + 5 * S], fill=(255, 236, 200))
        d.ellipse([x * S - 2.5 * S, y * S - 2.5 * S, x * S + 2.5 * S, y * S + 2.5 * S], fill=(255, 255, 255))


def _ornament(img: Image.Image, cx, cy, r):
    d = ImageDraw.Draw(img)
    d.line([(cx * S, 0), (cx * S, (cy - r) * S)], fill=(190, 190, 196), width=S)
    size = int(r * 2 * S)
    ball = Image.new("RGB", (size, size), (120, 14, 24))
    bd = ImageDraw.Draw(ball)
    for i in range(14):
        t = i / 14
        rr = size / 2 * (1 - t * 0.7)
        c = (int(150 + 90 * t), int(18 + 40 * t), int(28 + 40 * t))
        ox, oy = size / 2 - size * 0.12 * t, size / 2 - size * 0.14 * t
        bd.ellipse([ox - rr, oy - rr, ox + rr, oy + rr], fill=c)
    img.paste(ball, (int(cx * S - size / 2), int(cy * S - size / 2)), _disc(size))
    d.rectangle([cx * S - 6 * S, (cy - r - 5) * S, cx * S + 6 * S, (cy - r + 2) * S], fill=(200, 190, 150))
    d.ellipse([cx * S - r * S * 0.55, (cy - r * 0.55) * S - r * S * 0.35, cx * S - r * S * 0.1, (cy - r * 0.55) * S],
              fill=(255, 255, 255))
    # снежная шапка
    d.chord([cx * S - r * S * 0.95, (cy - r) * S + 2 * S, cx * S + r * S * 0.95, (cy + r * 0.2) * S], 200, 340,
            fill=(240, 246, 252))


def _decor_top(img, rng):
    _branch(img, rng, 990, 8, 170, 250)
    _branch(img, rng, 964, -8, 116, 150)
    _ornament(img, 884, 62, 31)
    _lights(img, [(930, 52), (868, 20), (800, 14)])


def _decor_bottom(img, rng):
    _branch(img, rng, -26, 808, -14, 230)
    _branch(img, rng, 986, 808, 194, 230)
    _branch(img, rng, 24, 834, -56, 140)
    _lights(img, [(80, 760), (58, 786), (886, 770)])


def _cat(img: Image.Image, cx, cy, size):
    """Серый полосатый кот в шапке Деда Мороза (рисуется кодом). size — высота в px, cx/cy — центр."""
    K = 4
    c = Image.new("RGBA", (200 * K, 200 * K), (255, 255, 255, 0))
    d = ImageDraw.Draw(c)

    def P(*pts):
        return [(x * K, y * K) for x, y in pts]

    def E(x0, y0, x1, y1):
        return [x0 * K, y0 * K, x1 * K, y1 * K]

    fur, dark, line = (132, 132, 140), (74, 74, 82), (36, 36, 42)
    for ear in (((36, 96), (44, 34), (92, 74)), ((164, 96), (156, 34), (108, 74))):
        d.polygon(P(*ear), fill=fur, outline=line, width=3 * K)
    d.polygon(P((46, 88), (50, 50), (80, 76)), fill=(206, 146, 158))
    d.polygon(P((154, 88), (150, 50), (120, 76)), fill=(206, 146, 158))
    d.ellipse(E(26, 66, 174, 176), fill=fur, outline=line, width=3 * K)
    for x0, y0, x1, y1 in ((100, 72, 100, 94), (82, 76, 85, 93), (118, 76, 115, 93), (34, 118, 52, 122), (166, 118, 148, 122)):
        d.line(P((x0, y0), (x1, y1)), fill=dark, width=5 * K)
    d.ellipse(E(66, 124, 134, 172), fill=(238, 238, 242))
    for ex in (56, 114):
        d.ellipse(E(ex, 100, ex + 32, 138), fill=(24, 24, 30))
        d.ellipse(E(ex + 7, 106, ex + 17, 116), fill=(255, 255, 255))
        d.ellipse(E(ex + 20, 124, ex + 25, 129), fill=(255, 255, 255))
    d.polygon(P((93, 130), (107, 130), (100, 139)), fill=(232, 130, 150))
    d.line(P((100, 139), (100, 146)), fill=line, width=3 * K)
    d.arc(E(86, 140, 100, 154), 0, 180, fill=line, width=3 * K)
    d.arc(E(100, 140, 114, 154), 0, 180, fill=line, width=3 * K)
    for y0, y1 in ((136, 130), (142, 142), (148, 154)):
        d.line(P((70, y0), (22, y1)), fill=(225, 225, 230), width=2 * K)
        d.line(P((130, y0), (178, y1)), fill=(225, 225, 230), width=2 * K)
    # шапка
    d.polygon(P((44, 86), (156, 86), (140, 46), (172, 34), (150, 20), (104, 8), (66, 40)), fill=(200, 28, 40))
    d.polygon(P((104, 8), (150, 20), (172, 34), (140, 46), (122, 30)), fill=(226, 50, 60))
    d.rounded_rectangle(E(36, 76, 164, 98), radius=11 * K, fill=(250, 250, 252))
    d.ellipse(E(158, 20, 186, 48), fill=(252, 252, 254))
    px = int(size * S)
    c = c.resize((px, px), Image.LANCZOS)
    sh = Image.new("RGBA", c.size, (0, 0, 0, 0))
    sh.putalpha(c.getchannel("A").filter(ImageFilter.GaussianBlur(5 * S)).point(lambda v: int(v * 0.5)))
    img.paste(sh, (int(cx * S - px / 2), int(cy * S - px / 2 + 5 * S)), sh)
    img.paste(c, (int(cx * S - px / 2), int(cy * S - px / 2)), c)


def _finish(img: Image.Image) -> Image.Image:
    vig = Image.radial_gradient("L").resize(img.size).point(lambda v: int(max(0, v - 100) * 0.55))
    img = Image.composite(Image.new("RGB", img.size, (0, 0, 0)), img, vig)
    noise = Image.effect_noise(img.size, 30).convert("RGB")
    return ImageChops.soft_light(img, Image.blend(Image.new("RGB", img.size, (128, 128, 128)), noise, 0.25))


def _card(img, box, label, value, value_fill=WHITE, ava=None, name=""):
    _glass(img, box, radius=22, veil=0.06, blur=14)
    x0, y0, x1, y1 = box
    tx = x0 + 28
    if ava is not None or name:
        _avatar(img, ava, name, x0 + 28 + 24, y0 + 72, 24)
        tx = x0 + 28 + 60
    _text(img, x0 + 28, y0 + 30, label, _font("reg", 20), fill=GREY)
    f = _fit_font("bold", value, x1 - tx - 20, 34, 18)
    _text(img, tx, y0 + 74, value, f, fill=value_fill)


# ---------- главная функция ----------
def render(thief_name: str, victim_name: str, amount_text: str, cur: str,
           thief_ava: Image.Image | None = None, victim_ava: Image.Image | None = None,
           seed: int | None = None, thief_username: str = "", pct: str = "—",
           victim_before: str = "—", thief_balance: str = "—") -> bytes:
    rng = random.Random(seed)
    img = _background(rng)
    _snow(img, rng)
    _flakes(img)

    # шапка: профиль грабителя
    _avatar(img, thief_ava, thief_name, 96, 92, 50)
    nf = _fit_font("black", thief_name, 600, 44, 24)
    _text(img, 170, 64, thief_name, nf, fill=WHITE)
    _text(img, 170, 108, ("@" + thief_username) if thief_username else "грабитель", _font("reg", 22), fill=DIM)
    pill = "Ограбление"
    pf = _font("reg", 19)
    pw = _text_w(pill, pf) + 36
    _glass(img, (170, 134, 170 + pw, 170), radius=18, veil=0.04, blur=6)
    _text(img, 188, 152, pill, pf, fill=(225, 226, 230))

    # большая панель с суммой
    _glass(img, (36, 200, 924, 452), radius=30, veil=0.07, blur=18)
    full = f"{amount_text} {cur}"
    af = _fit_font("black", full, 800, 100, 36, stretch=1.14)
    _text(img, 480, 304, full, af, anchor="c", stretch=1.14, grad=((255, 255, 255), (150, 152, 160)), glow=0.28)
    _text(img, 480, 392, "ушло грабителю", _font("hand", 38), fill=PINK, anchor="c", rot=3)
    d = ImageDraw.Draw(img)
    pts = [(342 * S + i * 3 * S, (418 - 3 * math.sin(i / 9)) * S + i * -0.03 * S) for i in range(0, 90)]
    d.line(pts, fill=PINK, width=int(2.4 * S), joint="curve")

    # четыре карточки
    _card(img, (36, 478, 474, 590), "Жертва", victim_name, ava=victim_ava, name=victim_name)
    _card(img, (486, 478, 924, 590), "Доля от кошелька", pct)
    _card(img, (36, 604, 474, 716), "Было у жертвы", f"{victim_before} {cur}")
    _card(img, (486, 604, 924, 716), "Твой баланс", f"{thief_balance} {cur}", value_fill=GOLD)

    ff = _font("black", 28)
    tw = _text_w("курсед)", ff)
    size, gap = 86, 2
    x0 = 480 - (size + gap + tw) / 2
    _cat(img, x0 + size / 2, 757, size)
    _text(img, x0 + size + gap, 764, "курсед)", ff, fill=(236, 238, 242))

    _decor_top(img, rng)
    _decor_bottom(img, rng)

    out = _finish(img).resize((W, H), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def load_avatar(data: bytes | None) -> Image.Image | None:
    if not data:
        return None
    try:
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None


if __name__ == "__main__":
    Path("preview.png").write_bytes(render("Тестовый Грабитель", "Бедный Игрок", "6 000", "cur коинов", seed=7,
                                           thief_username="thief", pct="12%", victim_before="50 000",
                                           thief_balance="23 604 912"))
