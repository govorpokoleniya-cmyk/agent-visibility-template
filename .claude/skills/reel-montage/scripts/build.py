#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сборка рилса по plan.json: видеоряд, перебивки, плашки, субтитры, звук.

Порядок вызова:
    python3 build.py plan.json [--skip-cards] [--skip-audio]

Монтаж собирается в кадрах, а не в секундах: длительности сегментов заданы
числом кадров, поэтому склейка не «уезжает» относительно исходной звуковой
дорожки и липсинк сохраняется без ручной подгонки.
"""
import json, os, subprocess, sys, shutil

import cards
import subtitles
import sound

FPS = 30


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, check=True, text=True,
                          capture_output=True, **kw).stdout


def ffprobe(path, entries):
    return sh(f'ffprobe -v error -show_entries {entries} -of default=nk=1:nw=1 "{path}"').strip()


def main(plan_path):
    plan = json.load(open(plan_path))
    work = plan.get("work_dir", "work")
    os.makedirs(work, exist_ok=True)
    src = plan["source"]
    W, H = plan.get("width", 1080), plan.get("height", 1920)
    skip_cards = "--skip-cards" in sys.argv
    skip_audio = "--skip-audio" in sys.argv

    # ---- 1. раскладка таймлайна в кадрах ----
    tl, at = [], 0
    for item in plan["timeline"]:
        item = dict(item)
        item["t0"] = at / FPS
        at += item["frames"]
        item["t1"] = at / FPS
        tl.append(item)
    total = at
    print(f"таймлайн: {total} кадров = {total/FPS:.2f} c, сегментов {len(tl)}")

    cuts_in = [s["t0"] for i, s in enumerate(tl) if i and s["type"] == "card"]
    cuts_out = [s["t0"] for i, s in enumerate(tl) if i and s["type"] == "face"]

    # ---- 2. перебивки и плашки ----
    if not skip_cards:
        for s in tl:
            if s["type"] != "card":
                continue
            plate = f'{work}/plate_{s["id"]}.png'
            sh(f'ffmpeg -v error -ss {s["card"]["bg_at"]} -i "{src}" -frames:v 1 '
               f'-vf scale={W}:{H} "{plate}" -y')
            cards.render(s["card"], s["frames"], f'{work}/clips/{s["id"]}', plate)
            print(f'  перебивка {s["id"]}: {s["frames"]} кадров')
        for ov in plan.get("overlays", []):
            cards.render(ov["overlay"], ov["frames"], f'{work}/clips/{ov["id"]}')
            print(f'  плашка {ov["id"]}: {ov["frames"]} кадров')

    # ---- 3. сегменты с говорящей головой ----
    enc = "-c:v libx264 -preset veryfast -crf 14 -pix_fmt yuv420p -r 30 -an"
    os.makedirs(f"{work}/seg", exist_ok=True)
    for s in tl:
        out = f'{work}/seg/{s["id"]}.mp4'
        if s["type"] == "face":
            z0, z1 = s.get("zoom", [1.0, 1.05])
            cx, cy = s.get("center", [0.5, 0.45])
            dur = s["frames"] / FPS
            Z = f"({z0}+({z1}-{z0})*t/{dur})"
            sh(f'ffmpeg -v error -ss {s["src"]} -i "{src}" -frames:v {s["frames"]} '
               f'-vf "scale=w=\'{W}*{Z}\':h=\'{H}*{Z}\':eval=frame:flags=lanczos,'
               f'crop={W}:{H}:x=\'(in_w-{W})*{cx}\':y=\'(in_h-{H})*{cy}\',setsar=1" {enc} "{out}" -y')
        else:
            sh(f'ffmpeg -v error -framerate {FPS} -i "{work}/clips/{s["id"]}/%04d.png" '
               f'-vf "scale={W}:{H},setsar=1" {enc} "{out}" -y')
    with open(f"{work}/concat.txt", "w") as fh:
        for s in tl:
            fh.write(f'file \'seg/{s["id"]}.mp4\'\n')
    sh(f'ffmpeg -v error -f concat -safe 0 -i "{work}/concat.txt" -c copy "{work}/timeline.mp4" -y')

    # ---- 4. субтитры (можно выключить: "subtitles": {"enabled": false}) ----
    sub = plan.get("subtitles", {})
    subs_path = f"{work}/subs.ass"
    burn_subs = sub.get("enabled", True)
    if burn_subs:
        n_ch, n_ev = subtitles.build(plan["transcript"], subs_path, sub.get("style"),
                                     sub.get("hide_after"), (W, H))
        print(f"субтитры: {n_ch} групп, {n_ev} событий")
    else:
        print("субтитры: выключены планом")

    # ---- 5. композит: плашки + вспышки на склейках + субтитры ----
    inputs, fc, last = [f'-i "{work}/timeline.mp4"'], [], "0:v"
    for k, ov in enumerate(plan.get("overlays", []), start=1):
        inputs.append(f'-framerate {FPS} -i "{work}/clips/{ov["id"]}/%04d.png"')
        fc.append(f'[{k}:v]format=rgba,tpad=start_duration={ov["at"]:.3f}:start_mode=add:color=#00000000[ov{k}]')
        fc.append(f'[{last}][ov{k}]overlay=0:0:eof_action=pass:repeatlast=0[c{k}]')
        last = f"c{k}"
    flash = "+".join(f"{plan.get('flash', 0.30)}*exp(-pow((t-{c:.3f})/0.05,2))" for c in cuts_out) or "0"
    grade = plan.get("grade", "contrast=1.05:saturation=1.06")
    fc.append(f"[{last}]eq={grade}:brightness='{flash}':eval=frame" + ("[g]" if burn_subs else "[v]"))
    if burn_subs:
        fc.append(f"[g]subtitles={subs_path}:fontsdir={cards.FONT_DIR}[v]")
    sh(f'ffmpeg -v error {" ".join(inputs)} -filter_complex "{";".join(fc)}" -map "[v]" '
       f'-c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p -r {FPS} -an "{work}/video.mp4" -y')
    print("видеоряд собран")

    # ---- 6. звук ----
    audio = f"{work}/audio.wav"
    mode = plan.get("sound", {}).get("mode", "design")
    if not skip_audio and mode in ("raw", "raw+bed"):
        # Голос не обрабатывается: только статическое усиление до цели и лимитер
        # по пикам. Чистое усиление не меняет отношение шум/речь, поэтому
        # материал не начинает шуметь сильнее, чем шумел.
        snd = plan.get("sound", {})
        dur = total / FPS
        sh(f'ffmpeg -v error -i "{src}" -vn -c:a pcm_s24le "{work}/voice_src.wav" -y')
        lufs = measure_lufs(f"{work}/voice_src.wav")
        gain = round(snd.get("lufs", -14.0) - lufs, 2)
        print(f"оригинал: {lufs} LUFS -> усиление {gain} dB, без цепи обработки")
        sh(f'ffmpeg -v error -i "{work}/voice_src.wav" '
           f'-af "volume={gain}dB,alimiter=limit=0.891:attack=5:release=60:level=false,apad" '
           f'-t {dur:.3f} -ar 48000 -c:a pcm_s24le "{work}/voice_norm.wav" -y')
        if mode == "raw":
            shutil.copy(f"{work}/voice_norm.wav", audio)
        else:
            # Тональные акценты и тихая подложка ПОД нетронутый голос.
            # Микс не нормализуется заново — иначе уровень голоса уедет.
            energy = snd.get("energy") or auto_energy(tl)
            sound.write(f"{work}/music.wav", sound.music(dur, energy, snd.get("bpm", 84), tonal=True), 0.75)
            sound.write(f"{work}/sfx.wav", sound.sfx(dur, cuts_in, cuts_out, snd.get("ticks"),
                                                     snd.get("riser_at"), snd.get("accent_at"), tonal=True), 0.85)
            mv, ms = snd.get("music_gain", 0.16), snd.get("sfx_gain", 0.263)
            # порог сайдчейна выше шума комнаты, иначе дак дышит на шуме
            sh(f'ffmpeg -v error -i "{work}/voice_norm.wav" -i "{work}/music.wav" -i "{work}/sfx.wav" '
               f'-filter_complex "[0:a]asplit=2[v1][vsc];[1:a]volume={mv}[m0];'
               f'[m0][vsc]sidechaincompress=threshold=0.08:ratio=5:attack=20:release=350[md];'
               f'[2:a]volume={ms}[s];[v1][md][s]amix=inputs=3:normalize=0:duration=longest,'
               f'alimiter=limit=0.891:level=false[out]" -map "[out]" -ar 48000 -c:a pcm_s24le "{audio}" -y')
            print(f"подложка и акценты домикшированы (музыка x{mv}, SFX x{ms}), голос не пересчитан")
    elif not skip_audio:
        dur = total / FPS
        snd = plan.get("sound", {})
        energy = snd.get("energy") or auto_energy(tl)
        sound.write(f"{work}/music.wav", sound.music(dur, energy, snd.get("bpm", 84)), 0.75)
        sound.write(f"{work}/sfx.wav", sound.sfx(dur, cuts_in, cuts_out, snd.get("ticks"),
                                                 snd.get("riser_at"), snd.get("accent_at")), 0.85)
        sh(f'ffmpeg -v error -i "{src}" -vn -c:a pcm_s24le "{work}/voice_src.wav" -y')
        voice = snd.get("voice_chain",
                        "highpass=f=80,afftdn=nr=10:nf=-40,equalizer=f=220:t=q:w=1.0:g=-2.5,"
                        "equalizer=f=3300:t=q:w=1.2:g=3,treble=g=1.5:f=8000,deesser=i=0.4,"
                        "agate=threshold=0.012:ratio=1.8:attack=15:release=260,"
                        "acompressor=threshold=0.1:ratio=3.2:attack=6:release=140:makeup=2,"
                        "alimiter=limit=0.95")
        mv, ms = snd.get("music_gain", 0.20), snd.get("sfx_gain", 0.30)
        sh(f'ffmpeg -v error -i "{work}/voice_src.wav" -i "{work}/music.wav" -i "{work}/sfx.wav" '
           f'-filter_complex "[0:a]{voice},asplit=2[v1][vsc];[1:a]volume={mv}[m0];'
           f'[m0][vsc]sidechaincompress=threshold=0.035:ratio=7:attack=15:release=320[md];'
           f'[2:a]volume={ms}[s];[v1][md][s]amix=inputs=3:normalize=0:duration=longest[mix]" '
           f'-map "[mix]" -ac 2 -ar 48000 -c:a pcm_s24le "{work}/mix_raw.wav" -y')
        lufs = measure_lufs(f"{work}/mix_raw.wav")
        target = snd.get("lufs", -14.0)
        gain = round(target - lufs, 2)
        print(f"микс: {lufs} LUFS -> коррекция {gain} dB")
        sh(f'ffmpeg -v error -i "{work}/mix_raw.wav" -af "volume={gain}dB,alimiter=limit=0.891:level=false" '
           f'-ar 48000 -c:a pcm_s24le "{audio}" -y')

    # ---- 7. финал ----
    out = plan.get("out", "reel.mp4")
    sh(f'ffmpeg -v error -i "{work}/video.mp4" -i "{audio}" -map 0:v -map 1:a -c:v copy '
       f'-c:a aac -b:a 192k -ar 48000 -movflags +faststart -shortest "{out}" -y')
    print(f'готово: {out} — {ffprobe(out, "format=duration")} c, '
          f'{int(os.path.getsize(out)/1e6)} МБ, {measure_lufs(out)} LUFS')


def auto_energy(tl):
    """Энергия музыки: тише под лицом, громче на перебивках, максимум на финале."""
    pts = []
    for i, s in enumerate(tl):
        last = i == len(tl) - 1
        lvl = 0.85 if (last and s["type"] == "card") else (0.70 if s["type"] == "card" else 0.45)
        pts.append((s["t0"], lvl))
    pts.append((tl[-1]["t1"], 0.70))
    return pts


def measure_lufs(path):
    out = subprocess.run(f'ffmpeg -v info -i "{path}" -af ebur128=framelog=quiet -f null -',
                         shell=True, text=True, capture_output=True).stderr
    block = out.split("Integrated loudness")[-1]
    for line in block.splitlines():
        line = line.strip()
        if line.startswith("I:"):
            return float(line.split()[1])
    return -23.0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("использование: build.py plan.json [--skip-cards] [--skip-audio]")
    main(sys.argv[1])
