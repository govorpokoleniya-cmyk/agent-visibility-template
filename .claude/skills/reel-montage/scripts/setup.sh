#!/bin/bash
# Окружение для монтажа: ffmpeg с libass, python-библиотеки и шрифт с кириллицей.
set -e
cd "$(dirname "$0")/.."

if ! command -v ffmpeg >/dev/null; then
  apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ffmpeg
fi
ffmpeg -hide_banner -filters 2>/dev/null | grep -q " subtitles " || { echo "ffmpeg без libass"; exit 1; }

pip3 install -q faster-whisper pillow numpy scipy fonttools

# Montserrat (кириллица) -> переименованный ReelSans, чтобы libass находил его однозначно
mkdir -p fonts
if [ ! -f fonts/ReelSans.ttf ]; then
  curl -sS -A "Mozilla/4.0" "https://fonts.googleapis.com/css?family=Montserrat:400,700,900&subset=cyrillic,latin" -o /tmp/m.css
  python3 - <<'PY'
import re, urllib.request
from fontTools.ttLib import TTFont
css = open('/tmp/m.css').read()
src = dict((w, u) for w, u in re.findall(r"font-weight: (\d+);\s*src: url\((https://[^)]+\.ttf)\)", css))
for weight, fam in (("700", "ReelSans"), ("900", "ReelSansBlack")):
    tmp = "/tmp/%s.src.ttf" % fam
    urllib.request.urlretrieve(src[weight], tmp)
    f = TTFont(tmp)
    for rec in f["name"].names:
        if rec.nameID in (1, 3, 4, 6, 16):
            v = fam if rec.nameID in (1, 4, 16) else fam + "-Regular"
            rec.string = v.encode("utf-16-be") if rec.platformID == 3 else v.encode("ascii")
    f["OS/2"].usWeightClass = 700
    f["head"].macStyle = 0
    f.save("fonts/%s.ttf" % fam)
    print("fonts/%s.ttf" % fam)
PY
fi
mkdir -p ~/.fonts && cp fonts/ReelSans*.ttf ~/.fonts/ && fc-cache -f >/dev/null 2>&1
echo "окружение готово"
