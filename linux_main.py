"""Linux desktop entry point for the Capri fan assistant."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QPen, QColor
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QMessageBox, QSystemTrayIcon

from avatar import Avatar
from linux_actions import LinuxActions
from local_ai import LocalAI
from speech_queue import SpeechQueue

ROOT = Path(__file__).resolve().parent
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "capricorn"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "capricorn"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "capricorn"
MODEL_DIR = DATA_DIR / "models" / "vosk-model-small-ru-0.22"
VOICE_DIR = DATA_DIR / "voices"
CONFIG_PATH = CONFIG_DIR / "config.json"
LOG_PATH = STATE_DIR / "capri.log"
DEFAULTS = {
    "local_ai": True,
    "local_model": "qwen3.5:9b",
    "wake_words": ["капри", "каприз", "капре", "кепри", "капли"],
    "greet_on_start": True,
    "hide_after_seconds": 18,
    "chatter": False,
    "tts_preset": "piper_irina",
    "think_mode": False,
}

VOICE_PRESETS = {
    "piper_irina": {"label": "Нейроголос Ирина (Piper)", "engine": "piper",
                    "voice": "ru+f2", "rate": 150, "pitch": 44, "volume": 62},
    "soft_female": {"label": "Мягкий женский", "voice": "ru+f2", "rate": 150, "pitch": 44, "volume": 62},
    "clear_female": {"label": "Женский повыше", "voice": "ru+f3", "rate": 155, "pitch": 50, "volume": 65},
    "calm_male": {"label": "Спокойный низкий", "voice": "ru+m2", "rate": 150, "pitch": 38, "volume": 62},
    "classic": {"label": "Обычный голос", "voice": "ru", "rate": 155, "pitch": 46, "volume": 62},
}

STATE_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(filename=LOG_PATH, level=logging.INFO, encoding="utf-8",
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("capri")


class Bridge(QObject):
    final_text = Signal(str)
    partial_text = Signal(str)
    listener_error = Signal(str)
    answer = Signal(str)
    speech_finished = Signal(int)
    model_answer = Signal(str, int)


class LocalSpeaker:
    """Offline speech synthesis using Piper, with espeak-ng fallback voices."""
    def __init__(self, cfg):
        self.process = None
        self.temp_audio = None
        self._piper_voice = None
        self._piper_model = None
        self.apply_preset(cfg.get("tts_preset", "piper_irina"))

    def apply_preset(self, preset):
        self.preset = preset if preset in VOICE_PRESETS else "piper_irina"
        self.voice = VOICE_PRESETS[self.preset]

    def stop_playback(self):
        process = self.process
        if process and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            except ProcessLookupError:
                pass

    def stop(self):
        self.stop_playback()
        if self.temp_audio:
            try:
                os.unlink(self.temp_audio)
            except FileNotFoundError:
                pass
            self.temp_audio = None

    def _play(self, command, timeout, cancel):
        if cancel.is_set():
            return
        self.process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + timeout
        while self.process.poll() is None:
            if cancel.wait(0.05) or time.monotonic() >= deadline:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
                break

    def say(self, text: str, cancel):
        self.stop()
        if cancel.is_set():
            return
        voice = self.voice.copy()
        if voice.get("engine") == "piper":
            model = VOICE_DIR / "ru_RU-irina-medium.onnx"
            if not model.is_file():
                model = ROOT / "voices" / "ru_RU-irina-medium.onnx"
            player = shutil.which("pw-play") or shutil.which("paplay")
            if model.is_file() and player:
                try:
                    from piper import PiperVoice, SynthesisConfig
                    if self._piper_voice is None or self._piper_model != model:
                        self._piper_voice = PiperVoice.load(str(model))
                        self._piper_model = model
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as audio:
                        self.temp_audio = audio.name
                    with wave.open(self.temp_audio, "wb") as wav_file:
                        self._piper_voice.synthesize_wav(
                            text, wav_file, syn_config=SynthesisConfig(volume=0.72))
                    self._play([player, self.temp_audio], max(20, len(text) / 3), cancel)
                    self.stop()
                    return
                except Exception:
                    self.stop()
        binary = shutil.which("espeak-ng") or shutil.which("espeak")
        if not binary:
            return
        self.stop()
        try:
            self._play([binary, "-v", voice["voice"], "-s", str(voice["rate"]),
                        "-p", str(voice["pitch"]), "-a", str(voice["volume"]),
                        "-P", "34", text], max(8, len(text) / 8), cancel)
        except (OSError, subprocess.TimeoutExpired):
            self.stop()


class CapriLinux(QObject):
    def __init__(self, cfg, avatar, app):
        super().__init__()
        self.cfg, self.avatar, self.app = cfg, avatar, app
        self.local = LocalAI(cfg)
        self.actions = LinuxActions()
        self.speaker = LocalSpeaker(cfg)
        self.bridge = Bridge()
        self.bridge.final_text.connect(self.on_final)
        self.bridge.partial_text.connect(self.on_partial)
        self.bridge.listener_error.connect(self.on_listener_error)
        self.bridge.answer.connect(self.on_answer)
        self.bridge.model_answer.connect(self.on_model_answer)
        self.app.aboutToQuit.connect(self.shutdown)
        self.awake_until = 0.0
        self.busy = False
        self.listener = None
        self.speech = SpeechQueue(self.speaker, self._mute, self.bridge.speech_finished.emit)
        self.bridge.speech_finished.connect(self._speech_finished)
        self.wake = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in cfg["wake_words"]) + r")\b", re.I)

    def start(self):
        threading.Thread(target=self.local.start_server, name="ollama-warmup", daemon=True).start()
        try:
            from linux_voice import LinuxListener
            model = MODEL_DIR
            if not (model / "am/final.mdl").is_file():
                log.warning("Vosk model is missing; run bash setup-linux.sh")
                self.avatar.set_subtitle("МИКРОФОН: ЗАПУСТИ bash setup-linux.sh")
                return
            self.listener = LinuxListener(str(model),
                                          lambda text, _audio: self.bridge.final_text.emit(text),
                                          lambda text: self.bridge.partial_text.emit(text),
                                          lambda error: self.bridge.listener_error.emit(str(error)))
            self.listener.start()
        except Exception:
            log.exception("Unable to start offline speech recognition")
            self.avatar.set_subtitle("НЕ УДАЛОСЬ ЗАПУСТИТЬ МИКРОФОН")

    def on_partial(self, text):
        if self.wake.search(text):
            self.awake_until = time.time() + 10
            self.avatar.summon()
            self.avatar.set_mode("listening")
            self.avatar.set_subtitle("СЛУШАЮ ТЕБЯ")

    def on_final(self, text):
        match = self.wake.search(text)
        if match:
            text = (text[:match.start()] + " " + text[match.end():]).strip(" ,.!?")
            self.awake_until = time.time() + 10
        elif time.time() > self.awake_until:
            return
        if not text:
            self.avatar.summon()
            self.avatar.set_mode("listening")
            self.avatar.set_subtitle("ДА?")
            self.awake_until = time.time() + 10
            return
        self.handle_text(text)

    def ask_text(self):
        text, ok = QInputDialog.getText(None, "Капри", "Скажи или напиши вопрос:")
        if ok and text.strip():
            self.avatar.summon()
            self.handle_text(text.strip())

    def set_voice_preset(self, preset):
        self.cfg["tts_preset"] = preset
        self.speaker.apply_preset(preset)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(self.cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        self.avatar.summon()
        self.avatar.set_mode("speaking", 4)
        self.avatar.set_subtitle(VOICE_PRESETS[preset]["label"].upper())
        self.speech.submit("Привет. Я Капри. Так звучит мягче?")

    def set_think_mode(self, enabled):
        self.local.think_mode = bool(enabled)
        self.cfg["think_mode"] = self.local.think_mode
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(self.cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    def show_memory(self):
        QMessageBox.information(self.avatar, "Память Capri", self.local.memory_summary())

    def clear_memory(self):
        choice = QMessageBox.question(
            self.avatar, "Очистить память Capri?",
            "Будут удалены сохранённые заметки и история диалогов с этого компьютера.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if choice == QMessageBox.StandardButton.Yes:
            self.local.clear_memory()
            self.speech.cancel()
            self.after_speech()
            QMessageBox.information(self.avatar, "Память Capri", "Сохранённые заметки и история удалены.")

    def handle_text(self, text):
        if self.busy:
            return
        if self.local.is_clear_memory_request(text):
            self.clear_memory()
            return
        plan = self.actions.confirmation_plan(text)
        if plan and plan.get("kind") == "error":
            self.bridge.answer.emit(plan["message"])
            return
        if plan:
            choice = QMessageBox.question(
                self.avatar, "Подтвердить действие", plan["description"],
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if choice != QMessageBox.StandardButton.Yes:
                self.bridge.answer.emit("Отменила. Ничего не меняла.")
                return
        elif self.actions.is_destructive_request(text):
            self.bridge.answer.emit(
                "Команда не выполнена. Для удаления назови точный путь к одному файлу; "
                "выключение компьютера и очистка корзины пока не подключены.")
            return
        if self.listener:
            self.listener.reset_req.set()
        self.speech.cancel()
        self.busy = True
        self.avatar.summon()
        self.avatar.set_mode("thinking")
        self.avatar.set_subtitle(text[:58])
        threading.Thread(target=self._answer, args=(text, plan), daemon=True).start()

    def _answer(self, text, confirmed_plan=None):
        try:
            result = (self.actions.execute_confirmed(confirmed_plan) if confirmed_plan
                      else self.actions.handle(text))
            if result == "__HIDE__":
                self.bridge.answer.emit("__HIDE__")
                return
            if result == "__QUIT__":
                self.bridge.answer.emit("__QUIT__")
                return
            if result is None:
                generation = self.local.memory_generation()
                result = self.local.ask(text)
                self.bridge.model_answer.emit(result or "Не смогла уверенно ответить. Скажи иначе или попроси поиск.", generation)
                return
            self.bridge.answer.emit(result or "Не смогла уверенно ответить. Скажи иначе или попроси поиск.")
        except Exception as e:
            log.exception("Command failed: %s", text)
            self.bridge.answer.emit("Не получилось выполнить эту команду.")

    def _mute(self, muted):
        if self.listener:
            if muted:
                self.listener.muted.set()
            else:
                self.listener.reset_req.set()
                self.listener.muted.clear()

    def _speech_finished(self, generation):
        if generation == self.speech.generation and not self.busy:
            self.after_speech()

    def on_listener_error(self, error):
        log.error("Speech recognition: %s", error)
        self.avatar.set_mode("idle")
        self.avatar.set_subtitle("МИКРОФОН НЕ РАБОТАЕТ")

    def after_speech(self):
        self.avatar.set_mode("idle")
        self.avatar.set_subtitle("")

    def shutdown(self):
        self.speech.close()
        if self.listener:
            self.listener.stop()

    def on_model_answer(self, text, generation):
        if generation != self.local.memory_generation():
            self.busy = False
            return
        self.on_answer(text)

    def on_answer(self, text):
        if text == "__IDLE__":
            self.after_speech()
            return
        self.busy = False
        if text == "__HIDE__":
            self.avatar.vanish()
            return
        if text == "__QUIT__":
            self.app.quit()
            return
        self.avatar.set_subtitle(text)
        self.avatar.set_mode("speaking", min(45, max(3, len(text) / 12)))
        self.awake_until = time.time() + 7
        self.speech.submit(text)


def load_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cfg = DEFAULTS.copy()
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            log.exception("Could not read config; using defaults")
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


def tray_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(255, 34, 96))
    p.setPen(QPen(QColor(150, 70, 255), 4))
    p.drawEllipse(4, 4, 56, 56)
    p.setBrush(QColor(6, 24, 20))
    p.setPen(QPen(QColor(40, 255, 150), 4))
    p.drawEllipse(14, 22, 36, 20)
    p.setBrush(QColor(40, 255, 150))
    p.drawEllipse(27, 27, 10, 10)
    p.end()
    return QIcon(pixmap)


def main():
    # Package files are read-only; extract the bundled offline model into the
    # user's XDG data directory on first launch.
    model_file = MODEL_DIR / "am" / "final.mdl"
    if not model_file.is_file():
        archive = ROOT / "bundled" / "vosk-model-small-ru-0.22.zip"
        if archive.is_file():
            import zipfile
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(MODEL_DIR.parent)

    app = QApplication(sys.argv)
    app.setApplicationName("Capricorn")
    app.setQuitOnLastWindowClosed(False)
    cfg = load_config()
    avatar = Avatar(str(ROOT / "assets"))
    avatar.hide_after = float(cfg.get("hide_after_seconds", 18))
    assistant = CapriLinux(cfg, avatar, app)

    menu = QMenu()
    for label, callback in (("Позвать Капри", avatar.summon),
                            ("Написать вопрос…", assistant.ask_text),
                            ("Спрятать", avatar.vanish),
                            ("Выход", app.quit)):
        action = QAction(label, menu)
        action.triggered.connect(lambda _checked=False, fn=callback: fn())
        menu.addAction(action)
    voice_menu = menu.addMenu("Голос Капри")
    for key, preset in VOICE_PRESETS.items():
        action = QAction(preset["label"], voice_menu)
        action.setCheckable(True)
        action.setChecked(key == assistant.speaker.preset)
        action.triggered.connect(lambda _checked=False, name=key: assistant.set_voice_preset(name))
        voice_menu.addAction(action)
    think_action = QAction("Режим сложных вопросов (дольше)", menu)
    think_action.setCheckable(True)
    think_action.setChecked(assistant.local.think_mode)
    think_action.toggled.connect(assistant.set_think_mode)
    menu.addAction(think_action)
    memory_menu = menu.addMenu("Память Capri")
    show_memory_action = QAction("Показать сохранённое", memory_menu)
    show_memory_action.triggered.connect(assistant.show_memory)
    memory_menu.addAction(show_memory_action)
    clear_memory_action = QAction("Очистить заметки и историю…", memory_menu)
    clear_memory_action.triggered.connect(assistant.clear_memory)
    memory_menu.addAction(clear_memory_action)
    tray = QSystemTrayIcon(tray_icon(), app)
    tray.setToolTip("Капри — локальный помощник")
    tray.setContextMenu(menu)
    tray.show()
    avatar.menu_requested.connect(lambda pos: menu.popup(pos))
    avatar.clicked.connect(assistant.ask_text)
    assistant.start()
    if cfg.get("greet_on_start"):
        avatar.summon()
        avatar.set_subtitle("НА СВЯЗИ")
        avatar.set_mode("idle")
    return app.exec()


def check_render():
    """Exercise the packaged Qt bindings without microphone, AI or user settings."""
    app = QApplication([sys.argv[0]])
    avatar = Avatar(str(ROOT / "assets"))
    avatar.timer.stop()
    avatar.state = "visible"
    for frame in range(1200):
        avatar.t = frame
        avatar.set_mode(("idle", "thinking", "speaking")[(frame // 400) % 3])
        avatar.render()
        app.processEvents()
    avatar.close()
    print("Avatar rendering check passed", flush=True)
    return 0


if __name__ == "__main__":
    if "--check-render" in sys.argv:
        raise SystemExit(check_render())
    try:
        raise SystemExit(main())
    except Exception:
        log.exception("Capri Linux exited with an error")
        raise
