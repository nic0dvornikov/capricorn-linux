#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Нужен Python 3.11 или новее (python3)."
  exit 1
fi

python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-linux.txt
.venv/bin/python tools/download_model.py
.venv/bin/python -m piper.download_voices --data-dir voices ru_RU-irina-medium

if ! command -v espeak-ng >/dev/null 2>&1 && ! command -v espeak >/dev/null 2>&1; then
  echo "Для локального голоса установи: sudo dnf install espeak-ng"
fi
if ! command -v wpctl >/dev/null 2>&1; then
  echo "Команды громкости требуют wpctl (обычно входит в PipeWire/WirePlumber)."
fi
if ! command -v pw-record >/dev/null 2>&1 && ! command -v arecord >/dev/null 2>&1; then
  echo "Для распознавания речи нужен PipeWire (pw-record) или ALSA (arecord)."
fi

echo
echo "Установка готова. Запусти ./run-linux.sh"
