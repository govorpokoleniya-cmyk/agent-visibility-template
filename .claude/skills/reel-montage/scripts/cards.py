#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Рендер перебивок и графических плашек по описанию из plan.json.

Каждый тип карточки — чистая функция кадра: (спецификация, номер кадра) -> PIL.Image.
Координаты заданы для холста 1080x1920; при другом размере всё масштабируется.
"""
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

W, H, FPS = 1080, 1920, 30

PALETTE = {
    "amber": (255, 196, 77),
    "red": (255, 90, 78),
    "mint": (74, 222, 168),
    "white": (247, 249, 252),
    "muted": (150, 160, 178),
    "ink": (10, 13, 18),
}
FONTS = {"black": "ReelSansBlack.ttf", "bold": "ReelSans.ttf"}
FONT_DIR = "fonts"


def col(name):
    return PALETTE.get(name, PALETTE["white"])


def F(weight, size):
    return ImageFont.truetype(os.path.join(FONT_DIR, FONTS[weight]), size)


# ---------- тайминг-функции ----------
def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def eo3(p): p = clamp(p); return 1 - (1 - p) ** 3
def eo5(p): p = clamp(p); return 1 - (1 - p) ** 5
def back(p):
    p = clamp(p); c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (p - 1) ** 3 + c1 * (p - 1) ** 2


# ---------- фон ----------
def make_plate(path, darkness=0.26, blur=42, desat=0.55):
    """Размытый кадр из самого видео как фон перебивки: связывает графику с материалом."""
    im = Image.open(path).convert("RGB").resize((W, H))
    im = im.filter(ImageFilter.GaussianBlur(blur))
    im = ImageEnhance.Color(im).enhance(desat)
    im = ImageEnhance.Brightness(im).enhance(darkness)
    im = Image.blend(im, Image.new("RGB", (W, H), (12, 18, 30)), 0.30)
    vig = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vig).ellipse([-W * .45, -H * .18, W * 1.45, H * 1.18], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(220))
    return Image.composite(im, Image.new("RGB", (W, H), (0, 0, 0)), vig)


def plate_frame(plate, p, z0=1.0, z1=1.07):
    z = z0 + (z1 - z0) * p
    w, h = int(W / z), int(H / z)
    x, y = (W - w) // 2, (H - h) // 2
    return plate.crop((x, y, x + w, y + h)).resize((W, H), Image.LANCZOS)


def punch(img, p, amount=0.08):
    """Вход перебивки: короткий зум-пуш + вспышка. Заменяет «переход» как таковой."""
    if p >= 1:
        return img
    z = 1 + amount * (1 - eo5(p))
    w, h = int(W / z), int(H / z)
    out = img.crop(((W - w) // 2, (H - h) // 2, (W - w) // 2 + w, (H - h) // 2 + h)).resize((W, H), Image.LANCZOS)
    fl = 0.45 * (1 - clamp(p / 0.5))
    return Image.blend(out, Image.new("RGB", (W, H), (255, 255, 255)), fl) if fl > 0.01 else out


def kicker(d, y, s, color, size=40, track=10):
    f = F("bold", size)
    ws = [d.textlength(c, font=f) for c in s]
    x = (W - (sum(ws) + track * (len(s) - 1))) / 2
    for c, w in zip(s, ws):
        d.text((x, y), c, font=f, fill=color, anchor="lm")
        x += w + track


def layer():
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    return lay, ImageDraw.Draw(lay)


def stamp(im, lay):
    return Image.alpha_composite(im, lay)


# =========================== типы перебивок ===========================
def card_year(spec, i, n, plate):
    """Большое число-счётчик + акцентная подпись. Для прогнозов, дат, сумм."""
    t, p = i / FPS, i / max(n - 1, 1)
    im = plate_frame(plate, p, 1.0, 1.08).convert("RGBA")
    d = ImageDraw.Draw(im)
    kicker(d, 640 - 30 * (1 - eo3(t / .35)), spec["kicker"], col(spec.get("kicker_color", "amber")))
    v0, v1 = spec["from"], spec["to"]
    val = v0 + round((v1 - v0) * eo5(clamp((t - .10) / .70)))
    fs = int(360 * (0.85 + 0.15 * back(clamp((t - .10) / .5))))
    d.text((W / 2, 892), str(val), font=F("black", fs), fill=(0, 0, 0, 170), anchor="mm")
    d.text((W / 2, 880), str(val), font=F("black", fs), fill=col("white"), anchor="mm")
    lw = eo3(clamp((t - .55) / .45)) * 620
    if lw > 2:
        d.rounded_rectangle([W / 2 - lw / 2, 1075, W / 2 + lw / 2, 1083], 4, fill=col("amber"))
    cap = spec.get("caption")
    if cap and t > cap["at"]:
        a = clamp((t - cap["at"]) / .40)
        lay, dl = layer()
        dl.text((W / 2, 1255 + int(40 * (1 - eo3(a)))), cap["text"], font=F("black", 96),
                fill=col(cap.get("color", "amber")) + (int(255 * clamp(a * 1.6)),), anchor="mm")
        im = stamp(im, lay)
    return punch(im.convert("RGB"), t / .25)


def card_compare(spec, i, n, plate):
    """Две полосы «было / стало». Любое сравнение двух величин."""
    t, p = i / FPS, i / max(n - 1, 1)
    im = plate_frame(plate, p, 1.0, 1.06).convert("RGBA")
    BX, BW, y1, y2 = 130, 660, 780, 1090
    bef, aft = spec["before"], spec["after"]
    lay, dl = layer()
    dl.rounded_rectangle([BX, y1 - 34, BX + BW, y1 + 34], 34, fill=(255, 255, 255, 30))
    if t > aft["at"]:
        dl.rounded_rectangle([BX, y2 - 34, BX + BW, y2 + 34], 34, fill=(255, 255, 255, 26))
    im = stamp(im, lay)
    d = ImageDraw.Draw(im)
    kicker(d, 560, spec["kicker"], col(spec.get("kicker_color", "muted")), 38, 9)

    d.text((BX, y1 - 84), bef["label"], font=F("bold", 44), fill=col("muted"), anchor="lm")
    g1 = eo3(clamp((t - bef["at"]) / .45)) * bef.get("fill", 1.0)
    if g1 > .01:
        d.rounded_rectangle([BX, y1 - 34, BX + BW * g1, y1 + 34], 34, fill=(236, 240, 248))
    if t > bef["at"] + .45:
        a = clamp((t - bef["at"] - .45) / .3)
        lay, dl = layer()
        dl.text((BX + BW + 34, y1), bef["value"], font=F("black", 80), fill=col("white") + (int(255 * a),), anchor="lm")
        im = stamp(im, lay); d = ImageDraw.Draw(im)

    if t > aft["at"]:
        d.text((BX, y2 - 84), aft["label"], font=F("bold", 44), fill=col("amber"), anchor="lm")
        w2 = BW * aft.get("fill", .25) * eo5(clamp((t - aft["at"] - .2) / .40))
        if w2 > 4:
            d.rounded_rectangle([BX, y2 - 34, BX + w2, y2 + 34], 34, fill=col("amber"))
    if t > aft["at"] + .6:
        a = clamp((t - aft["at"] - .6) / .25)
        lay, dl = layer()
        dl.text((BX + BW * aft.get("fill", .25) + 34, y2), aft["value"], font=F("black", 80),
                fill=col("amber") + (int(255 * a),), anchor="lm")
        im = stamp(im, lay)
    foot = spec.get("footer")
    if foot and t > foot["at"]:
        a = clamp((t - foot["at"]) / .3)
        lay, dl = layer()
        dl.text((W / 2, 1330 + int(26 * (1 - eo3(a)))), foot["text"], font=F("black", 64),
                fill=col("white") + (int(240 * a),), anchor="mm")
        im = stamp(im, lay)
    return punch(im.convert("RGB"), t / .22)


def card_tiles(spec, i, n, plate):
    """Плитки, появляющиеся по очереди внутри контейнера. Для «N штук за X»."""
    t, p = i / FPS, i / max(n - 1, 1)
    im = plate_frame(plate, p, 1.0, 1.07).convert("RGBA")
    d = ImageDraw.Draw(im)
    kicker(d, 600, spec["kicker"], col(spec.get("kicker_color", "amber")))
    bx0, by0, bx1, by1 = 150, 720, 930, 1220
    ca = eo3(clamp(t / .35))
    lay, dl = layer()
    dl.rounded_rectangle([bx0, by0, bx1, by1], 44, fill=(255, 255, 255, int(18 * ca)),
                         outline=(255, 255, 255, int(80 * ca)), width=3)
    im = stamp(im, lay); d = ImageDraw.Draw(im)
    d.text((bx0 + 28, by0 - 46), spec["container"], font=F("bold", 46), fill=col("white"), anchor="lm")
    tiles = spec["tiles"]; gap, pad = 26, 40
    tw = (bx1 - bx0 - 2 * pad - gap) / 2
    th = (by1 - by0 - 2 * pad - gap) / 2
    for k, label in enumerate(tiles):
        st = spec.get("start", .42) + k * spec.get("step", .26)
        a = back(clamp((t - st) / .34))
        if a <= .01:
            continue
        cx = bx0 + pad + (k % 2) * (tw + gap)
        cy = by0 + pad + (k // 2) * (th + gap)
        sx, sy = tw * (.86 + .14 * a), th * (.86 + .14 * a)
        ox, oy = cx + (tw - sx) / 2, cy + (th - sy) / 2
        al = int(255 * clamp((t - st) / .2))
        lay, dl = layer()
        dl.rounded_rectangle([ox, oy, ox + sx, oy + sy], 28, fill=col("amber") + (al,))
        dl.text((ox + sx / 2, oy + sy / 2), label, font=F("black", 40), fill=(18, 20, 26, al), anchor="mm")
        im = stamp(im, lay)
    return punch(im.convert("RGB"), t / .22)


def card_chart(spec, i, n, plate):
    """Растущая кривая + счётчик. Для роста, динамики, процентов."""
    t, p = i / FPS, i / max(n - 1, 1)
    im = plate_frame(plate, p, 1.0, 1.06).convert("RGBA")
    d = ImageDraw.Draw(im)
    accent = col(spec.get("accent", "mint"))
    kicker(d, 600, spec["kicker"], accent)
    gx0, gy0, gx1, gy1 = 170, 700, 910, 1150
    d.line([gx0, gy1, gx1, gy1], fill=(255, 255, 255, 70), width=4)
    d.line([gx0, gy0 - 20, gx0, gy1], fill=(255, 255, 255, 70), width=4)
    gp = eo3(clamp((t - .15) / 1.0))
    pts = []
    for k in range(61):
        q = k / 60
        if q > gp:
            break
        pts.append((gx0 + (gx1 - gx0) * q, gy1 - (gy1 - gy0) * q ** 1.9))
    if len(pts) > 1:
        lay, dl = layer()
        dl.polygon([(gx0, gy1)] + pts + [(pts[-1][0], gy1)], fill=accent + (55,))
        dl.line(pts, fill=accent, width=10, joint="curve")
        dl.ellipse([pts[-1][0] - 16, pts[-1][1] - 16, pts[-1][0] + 16, pts[-1][1] + 16], fill=col("white"))
        im = stamp(im, lay); d = ImageDraw.Draw(im)
    val = int(spec["value"] * eo3(clamp((t - .15) / 1.05)))
    s = f"{spec.get('prefix','')}{val}{spec.get('suffix','')}"
    d.text((W / 2, 1266), s, font=F("black", 120), fill=(0, 0, 0, 150), anchor="mm")
    d.text((W / 2, 1258), s, font=F("black", 120), fill=accent, anchor="mm")
    return punch(im.convert("RGB"), t / .22)


def card_question(spec, i, n, plate):
    """Финальная карточка: вопрос по словам + подпись + CTA."""
    t, p = i / FPS, i / max(n - 1, 1)
    im = plate_frame(plate, p, 1.0, 1.09).convert("RGBA")
    d = ImageDraw.Draw(im)
    kicker(d, 640, spec["kicker"], col(spec.get("kicker_color", "amber")))
    ys = [880, 1010, 1140]
    for k, (word, st) in enumerate(spec["words"]):
        a = clamp((t - st) / .28)
        if a <= 0:
            continue
        dy = int(46 * (1 - eo3(a)))
        color = col("amber") if k == len(spec["words"]) - 1 else col("white")
        lay, dl = layer()
        dl.text((W / 2 + 4, ys[k] + dy + 8), word, font=F("black", 116), fill=(0, 0, 0, int(140 * a)), anchor="mm")
        dl.text((W / 2, ys[k] + dy), word, font=F("black", 116), fill=color + (int(255 * a),), anchor="mm")
        im = stamp(im, lay)
    d = ImageDraw.Draw(im)
    sub = spec.get("sub")
    if sub and t > sub["at"]:
        a = clamp((t - sub["at"]) / .35)
        lw = eo3(a) * 560
        d.rounded_rectangle([W / 2 - lw / 2, 1268, W / 2 + lw / 2, 1274], 3, fill=(255, 255, 255, int(120 * a)))
        lay, dl = layer()
        dl.text((W / 2, 1380), sub["text"], font=F("bold", 52), fill=col("muted") + (int(255 * a),), anchor="mm")
        im = stamp(im, lay)
    cta = spec.get("cta")
    if cta and t > cta["at"]:
        a = clamp((t - cta["at"]) / .3)
        lay, dl = layer()
        dl.rounded_rectangle([W / 2 - 330, 1530, W / 2 + 330, 1650], 60, fill=col("amber") + (int(245 * a),))
        dl.text((W / 2, 1590), cta["text"], font=F("black", 44), fill=(16, 18, 24, int(255 * a)), anchor="mm")
        im = stamp(im, lay)
    return punch(im.convert("RGB"), t / .22)


# =========================== плашки поверх лица ===========================
def _inout(t, n, d_in=.35, d_out=.35):
    ein = eo3(clamp(t / d_in))
    eout = 1 - eo3(clamp((t - (n / FPS - d_out)) / d_out))
    return clamp(min(ein, eout)), ein, eout


def ov_plaque(spec, i, n, _plate=None):
    """Плашка-факт над линией глаз: слева метка+значение, справа контрзначение."""
    t = i / FPS
    im, _ = layer()
    a, ein, eout = _inout(t, n)
    if a <= .01:
        return im
    dx = int(-90 * (1 - ein) + 60 * (1 - eout))
    lay, d = layer()
    x0, y0, x1, y1 = 90 + dx, 150, 990 + dx, 410
    accent = col(spec.get("accent", "red"))
    d.rounded_rectangle([x0, y0, x1, y1], 36, fill=(10, 13, 18, int(220 * a)))
    d.rounded_rectangle([x0, y0, x0 + 12, y1], 6, fill=accent + (int(255 * a),))
    d.text((x0 + 50, y0 + 74), spec["label"], font=F("bold", 42), fill=col("muted") + (int(255 * a),), anchor="lm")
    d.text((x0 + 50, y0 + 170), spec["value"], font=F("black", 92), fill=col("white") + (int(255 * a),), anchor="lm")
    if spec.get("rvalue"):
        d.text((x1 - 50, y0 + 170), spec["rvalue"], font=F("black", 72), fill=accent + (int(255 * a),), anchor="rm")
    if spec.get("rlabel"):
        d.text((x1 - 50, y0 + 74), spec["rlabel"], font=F("bold", 34), fill=col("muted") + (int(255 * a),), anchor="rm")
    lw = eo3(clamp((t - .35) / .5))
    if lw > .02:
        d.line([x0 + 50, y0 + 232, x0 + 50 + (x1 - x0 - 100) * lw, y0 + 232], fill=accent + (int(200 * a),), width=6)
    return stamp(im, lay)


def ov_struck(spec, i, n, _plate=None):
    """Плашка с зачёркиванием: «не то» на экране, «то» — голосом."""
    t = i / FPS
    im, _ = layer()
    a, ein, _ = _inout(t, n, .3, .3)
    if a <= .01:
        return im
    dy = int(-50 * (1 - ein))
    lay, d = layer()
    x0, y0, x1, y1 = 70, 150 + dy, 1010, 410 + dy
    accent = col(spec.get("accent", "red"))
    d.rounded_rectangle([x0, y0, x1, y1], 36, fill=(10, 13, 18, int(215 * a)))
    d.text((W / 2, y0 + 62), spec["kicker"], font=F("bold", 38), fill=accent + (int(255 * a),), anchor="mm")
    f = F("black", 58)
    for k, line in enumerate(spec["lines"]):
        yy = y0 + 140 + k * 68
        d.text((W / 2, yy), line, font=f, fill=col("white") + (int(235 * a),), anchor="mm")
        st = spec["strike"][k]
        g = eo3(clamp((t - st) / .3))
        if g > .02:
            tw = d.textlength(line, font=f)
            d.line([W / 2 - tw / 2, yy + 4, W / 2 - tw / 2 + tw * g, yy + 4], fill=accent + (int(240 * a),), width=9)
    return stamp(im, lay)


RENDERERS = {
    "year": card_year, "compare": card_compare, "tiles": card_tiles,
    "chart": card_chart, "question": card_question,
    "plaque": ov_plaque, "struck": ov_struck,
}
ALPHA_KINDS = {"plaque", "struck"}


def render(spec, frames, out_dir, plate_path=None):
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(out_dir):
        os.remove(os.path.join(out_dir, f))
    fn = RENDERERS[spec["kind"]]
    plate = make_plate(plate_path, spec.get("darkness", 0.26), spec.get("blur", 42)) if plate_path else None
    alpha = spec["kind"] in ALPHA_KINDS
    for i in range(frames):
        im = fn(spec, i, frames, plate)
        (im if alpha else im.convert("RGB")).save(os.path.join(out_dir, f"{i:04d}.png"))
    return frames
