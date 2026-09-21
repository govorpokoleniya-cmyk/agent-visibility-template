#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ASS-субтитры с пословной подсветкой из word-level таймкодов Whisper."""
import json, re

# служебные слова, на которых нельзя обрывать строку
TAIL = {"на", "в", "за", "по", "и", "а", "но", "что", "не", "из", "к", "с", "у", "о",
        "от", "до", "мы", "ты", "я", "же", "это", "для", "то", "как", "при", "об"}

HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{font},{size},&H00FCF9F7,&H00FCF9F7,&H00101418,&H96000000,0,0,0,0,100,100,0,0,1,{outline},{shadow},2,90,90,{marginv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ts(x):
    x = max(0, x)
    return f"{int(x//3600)}:{int(x%3600//60):02d}:{x%60:05.2f}"


def load_words(path):
    ws = []
    for seg in json.load(open(path)):
        for w in seg["words"]:
            t = w["w"].strip().replace("«", "").replace("»", "")
            if not t:
                continue
            if not re.search(r"[\w\d]", t):                 # чистая пунктуация -> к предыдущему
                if ws:
                    ws[-1]["w"] = re.sub(r"([,.!?])[,.!?]+$", r"\1", ws[-1]["w"] + t)
                    ws[-1]["e"] = w["e"]
                continue
            ws.append({"w": t, "s": w["s"], "e": w["e"]})
    return ws


def chunk(ws, maxw=4, maxch=26):
    out, cur = [], []
    for w in ws:
        cand = cur + [w]
        if len(cand) > maxw or len(" ".join(x["w"] for x in cand)) > maxch:
            out.append(cur); cur = [w]
        else:
            cur = cand
        if re.search(r"[,.!?;:]$", cur[-1]["w"]):
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    out = [c for c in out if c]

    fixed = []
    for c in out:                                            # не обрывать на предлоге/цифре
        last = c[-1]["w"].lower().strip(".,!?;:")
        if len(c) > 1 and (last in TAIL or last.isdigit()):
            fixed += [c[:-1], [c[-1]]]
        else:
            fixed.append(c)
    merged = []
    for c in fixed:                                          # приклеить висячее слово к следующей группе
        if merged and len(merged[-1]) == 1:
            tl = merged[-1][-1]["w"].lower().strip(".,!?;:")
            cand = merged[-1] + c
            if (tl in TAIL or tl.isdigit()) and len(cand) <= maxw + 1 and len(" ".join(x["w"] for x in cand)) <= maxch:
                merged[-1] = cand
                continue
        merged.append(c)
    return merged


def build(transcript, out_path, style=None, hide_after=None, size=(1080, 1920)):
    st = {"font": "ReelSans", "size": 80, "outline": 8, "shadow": 4, "marginv": 430,
          "active": "&H4DC4FF&", "idle": "&HFCF9F7&"}
    st.update(style or {})
    hide = hide_after if hide_after is not None else 1e9
    chunks = chunk(load_words(transcript))
    lines = []
    for ci, ch in enumerate(chunks):
        if ch[0]["s"] >= hide - 0.5:
            continue
        nxt = chunks[ci + 1][0]["s"] if ci + 1 < len(chunks) else 1e9
        tail = min(ch[-1]["e"] + 0.30, nxt - 0.02, hide)
        for wi, w in enumerate(ch):
            start = w["s"] if wi else ch[0]["s"]
            end = ch[wi + 1]["s"] if wi + 1 < len(ch) else tail
            if end <= start:
                continue
            body = " ".join((("{\\c%s}" % (st["active"] if k == wi else st["idle"])) + x["w"])
                            for k, x in enumerate(ch))
            fade = r"{\fad(60,0)}" if wi == 0 else ""
            lines.append(f"Dialogue: 0,{ts(start)},{ts(end)},Main,,0,0,0,,{fade}{body}")
    head = HEAD.format(w=size[0], h=size[1], **{k: st[k] for k in ("font", "size", "outline", "shadow", "marginv")})
    open(out_path, "w").write(head + "\n".join(lines) + "\n")
    return len(chunks), len(lines)
