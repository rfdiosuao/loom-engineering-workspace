"""Generate dark, branded BMP art for the NSIS Modern UI installer.

Outputs (24-bit BMP, the format MUI wants) into scripts/dist/assets/:
  welcome.bmp  164x314  left panel of the welcome/finish pages
  header.bmp   150x57   top-right header strip of inner pages
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
ASSETS = os.path.join(HERE, "assets")
os.makedirs(ASSETS, exist_ok=True)

LOGO = os.path.join(ROOT, "logo_256.png")
YAHEI = r"C:\Windows\Fonts\msyh.ttc"


def font(size):
    try:
        return ImageFont.truetype(YAHEI, size)
    except Exception:
        return ImageFont.load_default()


def vgradient(w, h, top, bottom):
    img = Image.new("RGB", (w, h), top)
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px_row = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(w):
            px[x, y] = px_row
    return img


def load_logo():
    if os.path.exists(LOGO):
        return Image.open(LOGO).convert("RGBA")
    return None


def centered(draw, text, fnt, cx, y, fill):
    box = draw.textbbox((0, 0), text, font=fnt)
    draw.text((cx - (box[2] - box[0]) / 2, y), text, font=fnt, fill=fill)


def make_welcome():
    w, h = 164, 314
    img = vgradient(w, h, (13, 17, 23), (22, 27, 34))
    d = ImageDraw.Draw(img)
    # accent bar along the left edge
    d.rectangle([0, 0, 3, h], fill=(88, 166, 255))
    logo = load_logo()
    if logo:
        s = 96
        logo = logo.resize((s, s), Image.LANCZOS)
        img.paste(logo, ((w - s) // 2, 46), logo)
    centered(d, "LumiClaw", font(26), w / 2, 156, (230, 237, 243))
    centered(d, "满舱清梦压星河", font(13), w / 2, 192, (139, 148, 158))
    centered(d, "AI 自动化启动器", font(12), w / 2, 270, (110, 118, 129))
    img.save(os.path.join(ASSETS, "welcome.bmp"))
    print("welcome.bmp written")


def make_header():
    w, h = 150, 57
    img = vgradient(w, h, (17, 21, 31), (13, 17, 23))
    d = ImageDraw.Draw(img)
    logo = load_logo()
    x = 12
    if logo:
        s = 34
        logo = logo.resize((s, s), Image.LANCZOS)
        img.paste(logo, (x, (h - s) // 2), logo)
        x += s + 8
    d.text((x, h / 2 - 11), "LumiClaw", font=font(16), fill=(230, 237, 243))
    img.save(os.path.join(ASSETS, "header.bmp"))
    print("header.bmp written")


if __name__ == "__main__":
    make_welcome()
    make_header()
