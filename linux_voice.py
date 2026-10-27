"""Offline microphone listener for Linux, using PipeWire's pw-record CLI."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from external_process import external_env
import threading
import time
from pathlib import Path

log = logging.getLogger("capri")
RATE = 16_000
BLOCK_BYTES = 8_000  # 250 ms of mono 16-bit audio


class LinuxListener(threading.Thread):
    def __init__(self, model_path, on_final, on_partial, on_error):
        super().__init__(daemon=True, name="capri-microphone")
        self.model_path = Path(model_path)
        self.on_final = on_final
        self.on_partial = on_partial
        self.on_error = on_error
        self.muted = threading.Event()
        self.reset_req = threading.Event()
        self.stop_req = threading.Event()
        self.process = None

    @staticmethod
    def _command():
        if shutil.which("pw-record"):
            return ["pw-record", "--raw", "--rate", str(RATE), "--channels", "1", "--format", "s16", "-"]
        if shutil.which("arecord"):
            return ["arecord", "-q", "-t", "raw", "-D", "default", "-f", "S16_LE", "-r", str(RATE),
                    "-c", "1", "-"]
        return None

    def stop(self):
        self.stop_req.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()

    def run(self):
        try:
            import vosk
            vosk.SetLogLevel(-1)
            if not (self.model_path / "am/final.mdl").is_file():
                raise FileNotFoundError("Vosk-модель не найдена; запусти ./setup-linux.sh")
            command = self._command()
            if not command:
                raise RuntimeError("Не найден pw-record или arecord для микрофона")
            model = vosk.Model(str(self.model_path))
            recognizer = vosk.KaldiRecognizer(model, RATE)
            self.process = subprocess.Popen(command, env=external_env(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                            bufsize=0)
            log.info("Микрофон подключён через %s", command[0])
            while not self.stop_req.is_set():
                if self.reset_req.is_set():
                    recognizer.Reset()
                    self.reset_req.clear()
                was_muted = self.muted.is_set()
                data = self.process.stdout.read(BLOCK_BYTES)
                if not data:
                    if self.process.poll() is not None:
                        raise RuntimeError("PipeWire остановил запись с микрофона")
                    continue
                if was_muted or self.muted.is_set() or self.reset_req.is_set():
                    recognizer.Reset()
                    self.reset_req.clear()
                    continue
                if recognizer.AcceptWaveform(data):
                    text = json.loads(recognizer.Result()).get("text", "").strip()
                    if text:
                        self.on_final(text, data)
                else:
                    partial = json.loads(recognizer.PartialResult()).get("partial", "").strip()
                    if partial:
                        self.on_partial(partial)
        except Exception as e:
            if not self.stop_req.is_set():
                log.exception("Не удалось запустить распознавание речи")
                self.on_error(str(e))
        finally:
            if self.process and self.process.poll() is None:
                self.process.terminate()
