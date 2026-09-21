#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Расшифровка дорожки с пословными таймкодами (faster-whisper, CPU).

    python3 transcribe.py src.mov transcript.json [ru] [large-v3]

Модель меньше large-v3 экономит минуты, но регулярно путает короткие служебные
слова («не», «себе»), а они меняют смысл фразы. Для монтажа берите large-v3.
"""
import json, subprocess, sys, tempfile, os

def main(src, out, lang="ru", model_size="large-v3"):
    from faster_whisper import WhisperModel
    wav = tempfile.mktemp(suffix=".wav")
    subprocess.run(f'ffmpeg -v error -i "{src}" -vn -ac 1 -ar 16000 -c:a pcm_s16le "{wav}" -y',
                   shell=True, check=True)
    m = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
    segs, _ = m.transcribe(wav, language=lang, word_timestamps=True, beam_size=5,
                           vad_filter=True, vad_parameters=dict(min_silence_duration_ms=250))
    data = []
    for s in segs:
        data.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
                     "words": [{"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2)}
                               for w in (s.words or [])]})
        print(f"[{s.start:6.2f}-{s.end:6.2f}] {s.text.strip()}", flush=True)
    json.dump(data, open(out, "w"), ensure_ascii=False, indent=1)
    os.remove(wav)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("использование: transcribe.py <видео> <transcript.json> [язык] [модель]")
    main(*sys.argv[1:5])
