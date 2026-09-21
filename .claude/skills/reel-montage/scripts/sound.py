#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Саунд-дизайн без стоковой библиотеки: подложка и SFX синтезируются под монтаж.

Музыка привязана к кривой энергии (энергия растёт на перебивках), вуши и импакты —
к точкам склейки. Всё, что тут генерируется, свободно от лицензий.
"""
import numpy as np
from scipy import signal
from scipy.io import wavfile

SR = 44100
rng = np.random.default_rng(7)


def env_adsr(n, a, d, r, sus=0.7):
    a, d, r = int(a * SR), int(d * SR), int(r * SR)
    s_len = max(0, n - a - d - r)
    return np.concatenate([
        np.linspace(0, 1, a, endpoint=False) ** 1.5,
        np.linspace(1, sus, d, endpoint=False),
        np.full(s_len, sus),
        np.linspace(sus, 0, max(n - a - d - s_len, 0)) ** 1.5,
    ])[:n]


def reverb(x, decay=1.4, wet=0.32, pre=0.02):
    L = int(SR * decay)
    ir = rng.normal(0, 1, L) * np.exp(-np.linspace(0, 6, L))
    ir[: int(SR * pre)] = 0
    ir /= np.abs(ir).sum() / 12
    return (1 - wet) * x + wet * signal.fftconvolve(x, ir)[: len(x)]


def _filt(x, btype, freqs, order=2):
    nyq = SR / 2
    if btype == "band":
        wn = [max(freqs[0] / nyq, 1e-4), min(freqs[1] / nyq, 0.99)]
    else:
        wn = min(max(freqs / nyq, 1e-4), 0.99)
    b, a = signal.butter(order, wn, btype)
    return signal.lfilter(b, a, x)


def lp(x, fc): return _filt(x, "low", fc)
def hp(x, fc): return _filt(x, "high", fc)
def bp(x, f1, f2): return _filt(x, "band", (f1, f2))


def place(buf, x, at, gain=1.0):
    i = int(at * SR)
    if i < 0:
        x = x[-i:]; i = 0
    n = min(len(x), len(buf) - i)
    if n > 0:
        buf[i:i + n] += x[:n] * gain


def sweep(dur, f0, f1, q=2.0, up=True):
    """Вуш: белый шум сквозь скользящий полосовой фильтр."""
    n = int(dur * SR)
    noise = rng.normal(0, 1, n)
    out = np.zeros(n)
    step = int(SR * 0.008)
    for i in range(0, n, step):
        p = i / n
        f = f0 * (f1 / f0) ** (p if up else 1 - p)
        seg = bp(noise[max(0, i - step):i + step], f / q, min(f * q, SR / 2 * 0.98))
        s0 = step if i >= step else 0
        out[i:i + step] = seg[s0:s0 + min(step, n - i)]
    return out * np.sin(np.pi * np.linspace(0, 1, n)) ** 1.4


def tonal_whoosh(dur, f0, f1, noise_mix=0.22):
    """Глиссандо вместо шумового вуша: слышно как движение, но без шипения.
    Шумовая доля зажата в 250-1400 Гц и не попадает в полосу шума комнаты."""
    n = int(dur * SR); tt = np.arange(n) / SR
    fr = f0 * (f1 / f0) ** (tt / tt[-1])
    ph = 2 * np.pi * np.cumsum(fr) / SR
    tone = np.sin(ph) + .35 * np.sin(2 * ph) + .12 * np.sin(3 * ph)
    col = bp(rng.normal(0, 1, n), 250, 1400)
    return ((1 - noise_mix) * tone / 1.5 + noise_mix * col) * np.sin(np.pi * np.linspace(0, 1, n)) ** 1.5


def _note(f, dur, amp=1.0, detune=0.003, harm=(1.0, .32, .14, .06)):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    x = np.zeros(n)
    for k, h in enumerate(harm, start=1):
        for d in (-detune, detune):
            x += h * np.sin(2 * np.pi * f * k * (1 + d) * tt + rng.random() * 6.28)
    return x * amp / (len(harm) * 2)


def music(duration, energy_points, bpm=84, tonal=False, root=220.0,
          chords=((0, 3, 7), (-4, 0, 5), (-9, -5, 0), (-2, 2, 7))):
    N = int(SR * duration)
    t = np.arange(N) / SR
    def f(semi): return root * 2 ** (semi / 12)
    prog = list(chords) * 2
    slot = duration / len(prog)

    pad, bass, pulse, arp = (np.zeros(N) for _ in range(4))
    for i, ch in enumerate(prog):
        at = i * slot
        n = int((slot + 1.2) * SR)
        e = env_adsr(n, .7, .5, 1.0, .75)
        v = np.zeros(n)
        for semi in ch:
            v += _note(f(semi), n / SR, .5) + _note(f(semi) * 2, n / SR, .18)
        place(pad, lp(v * e, 1200 if tonal else 1900), at)
        bn = _note(f(ch[0]) / 2, slot + .4, .9, detune=.001, harm=(1.0, .25))
        place(bass, lp(bn * env_adsr(len(bn), .35, .6, .6, .6), 320), at)

    beat = 60 / bpm
    k = 0
    while 3.0 + k * beat * 2 < duration:
        at = 3.0 + k * beat * 2
        n = int(.42 * SR); tt = np.arange(n) / SR
        fdrop = 78 * np.exp(-tt * 16) + 44
        body = np.sin(2 * np.pi * np.cumsum(fdrop) / SR) * np.exp(-tt * 9)
        click = lp(rng.normal(0, 1, n) * np.exp(-tt * 200), 2500) * .25
        place(pulse, body * .9 + click, at)
        k += 1

    i = 0
    while i * beat / 2 < duration:
        at = i * beat / 2
        ch = prog[min(int(at / slot), len(prog) - 1)]
        semi = ch[[0, 2, 1, 2][i % 4]] + 12
        n = int(.32 * SR); tt = np.arange(n) / SR
        v = (np.sin(2 * np.pi * f(semi) * tt) * np.exp(-tt * 11) * .5
             + np.sin(2 * np.pi * f(semi) * 2 * tt) * np.exp(-tt * 16) * .15)
        place(arp, v, at)
        i += 1

    air = np.zeros(N) if tonal else hp(rng.normal(0, 1, N), 6000) * .02
    e = np.interp(t, [p[0] for p in energy_points], [p[1] for p in energy_points])
    w = int(SR * .6)
    e = np.convolve(e, np.ones(w) / w, mode="same")
    e[:w] = e[w]; e[-w:] = e[-w]

    mix = (reverb(pad, 1.6, .34) * .55 + bass * .5 + pulse * (.30 + .35 * e)
           + reverb(arp, 1.0, .40) * .22 * np.clip(e - .35, 0, 1) * 2.2 + air)
    mix = mix * (.55 + .9 * e)
    return lp(mix, 1600) if tonal else mix


def sfx(duration, cuts_in, cuts_out, ticks=None, riser_at=None, accent_at=None, tonal=False):
    N = int(SR * duration)
    buf = np.zeros(N)
    for c in cuts_in:
        if tonal:
            place(buf, tonal_whoosh(.38, 220, 1100), c - .28, .30)
        else:
            place(buf, sweep(.42, 400, 5200, 2.2, True), c - .30, .42)
        n = int(.45 * SR); tt = np.arange(n) / SR
        fdrop = 120 * np.exp(-tt * 14) + 48
        imp = np.sin(2 * np.pi * np.cumsum(fdrop) / SR) * np.exp(-tt * 7.5)
        imp += lp(rng.normal(0, 1, n) * np.exp(-tt * (120 if tonal else 90)), 700 if tonal else 1800) * (.22 if tonal else .3)
        place(buf, imp, c, .48 if tonal else .55)
    for c in cuts_out:
        if tonal:
            place(buf, tonal_whoosh(.28, 900, 260, noise_mix=.18), c - .18, .22)
        else:
            place(buf, sweep(.30, 5200, 700, 2.0, False), c - .20, .30)
        n = int(.28 * SR); tt = np.arange(n) / SR
        place(buf, np.sin(2 * np.pi * 62 * tt) * np.exp(-tt * 12), c, .32)
    if ticks:
        for k in range(ticks.get("count", 6)):
            at = ticks["from"] + k * ticks.get("step", .5)
            n = int(.05 * SR); tt = np.arange(n) / SR
            if tonal:
                tick = np.sin(2 * np.pi * 1800 * tt) * np.exp(-tt * 170)
                place(buf, tick, at, .10 if k % 2 else .14)
            else:
                tick = (np.sin(2 * np.pi * 2300 * tt) * np.exp(-tt * 180)
                        + lp(rng.normal(0, 1, n), 5000) * np.exp(-tt * 260) * .6)
                place(buf, tick, at, .22 if k % 2 else .3)
    if riser_at is not None:
        n = int(1.25 * SR); tt = np.arange(n) / SR
        if tonal:                                            # нота ползёт вверх на октаву
            fr = 165 * 2 ** (tt / tt[-1])
            ph = 2 * np.pi * np.cumsum(fr) / SR
            ris = (np.sin(ph) + .3 * np.sin(2 * ph) + .12 * np.sin(3 * ph)) / 1.4
            ris *= np.linspace(0, 1, n) ** 2 * (1 + .12 * np.sin(2 * np.pi * 7 * tt))
            place(buf, lp(ris, 1800), riser_at - 1.25, .26)
        else:
            ris = sweep(1.25, 600, 7000, 1.8, True) * np.linspace(0, 1, n) ** 2
            ris += np.sin(2 * np.pi * (200 + 500 * (tt / tt[-1]) ** 2) * tt) * np.linspace(0, .25, n)
            place(buf, ris, riser_at - 1.25, .34)
    if accent_at is not None:
        n = int(.6 * SR); tt = np.arange(n) / SR
        acc = (np.sin(2 * np.pi * 330 * tt) * np.exp(-tt * 9) * .25
               + np.sin(2 * np.pi * 495 * tt) * np.exp(-tt * 11) * .18)
        place(buf, reverb(acc, 1.2, .5), accent_at, .5)
    return buf


def write(path, mono, peak=0.85):
    x = np.stack([mono, np.roll(mono, 90)], axis=1)          # лёгкий стерео-спред
    x = x / (np.abs(x).max() + 1e-9) * peak
    wavfile.write(path, SR, (x * 32767).astype(np.int16))
