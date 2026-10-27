"""Small, explicit desktop actions for the Linux edition of Capri.

This intentionally avoids shell=True and arbitrary command execution. The
Windows implementation in actions.py is retained for the upstream project.
"""
from __future__ import annotations

import datetime
import os
import re
import shutil
import subprocess
import urllib.parse
import webbrowser
from pathlib import Path


class LinuxActions:
    def __init__(self):
        self.home = Path.home()

    @staticmethod
    def _run(args: list[str]) -> bool:
        try:
            return subprocess.run(args, check=False, timeout=8).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def confirmation_plan(self, raw: str) -> dict | None:
        """Build a narrowly-scoped plan for changes that always need user approval."""
        text = re.sub(r"\s+", " ", raw).strip()
        create = re.match(r"(?:создай|сделай)\s+(?:новую\s+)?папку\s+(.+)", text, re.I)
        if create:
            name = re.sub(r"[^\w .()-]", "", create.group(1), flags=re.UNICODE).strip(" .")
            if not name or name in {".", ".."}:
                return {"kind": "error", "message": "Не получилось разобрать имя папки. Ничего не меняла."}
            root = (self.home / "Documents" / "Capri").resolve()
            target = (root / name).resolve()
            if root not in target.parents:
                return {"kind": "error", "message": "Такой путь создавать нельзя. Ничего не меняла."}
            if target.exists():
                return {"kind": "error", "message": f"Папка «{name}» уже существует. Ничего не меняла."}
            return {"kind": "create_folder", "name": name, "target": str(target),
                    "description": f"Создать папку «{name}» в Документы/Capri?"}

        delete = re.match(r"(?:пожалуйста,?\s+)?(?:удали|удалить|сотри|стереть)\s+(?:файл\s+)?(.+)", text, re.I)
        if delete:
            raw_path = delete.group(1).strip().strip(" .,!?:;\"'")
            if not raw_path:
                return {"kind": "error", "message": "Назови точный путь к файлу. Ничего не удаляла."}
            candidate = Path(raw_path).expanduser()
            if not candidate.is_absolute():
                candidate = self.home / candidate
            try:
                if candidate.is_symlink():
                    return {"kind": "error", "message": "Символические ссылки я не удаляю. Ничего не меняла."}
                target = candidate.resolve(strict=True)
            except OSError:
                return {"kind": "error", "message": "Не нашла этот файл. Ничего не удаляла."}
            if self.home not in target.parents:
                return {"kind": "error", "message": "Можно удалять только файлы из домашней папки. Ничего не меняла."}
            if not target.is_file():
                return {"kind": "error", "message": "Удаляю только отдельные файлы, не папки. Ничего не меняла."}
            return {"kind": "delete_file", "target": str(target),
                    "description": f"Безвозвратно удалить файл?\n\n{target}"}
        return None

    @staticmethod
    def is_destructive_request(raw: str) -> bool:
        return bool(re.search(r"\b(удали|удалить|сотри|стереть|очисти корзину|выключи компьютер|"
                              r"заверши работу компьютера|перезагрузи компьютер|отформатируй)\b",
                              raw.lower().replace("ё", "е")))

    def execute_confirmed(self, plan: dict) -> str:
        if plan.get("kind") == "create_folder":
            root = (self.home / "Documents" / "Capri").resolve()
            target = Path(plan["target"]).resolve()
            if root not in target.parents or target.exists():
                return "Папку не создала: путь изменился или папка уже появилась."
            target.mkdir(parents=True, exist_ok=False)
            return f"Создала папку «{plan['name']}» в Документы/Capri."
        if plan.get("kind") == "delete_file":
            target = Path(plan["target"])
            try:
                if target.is_symlink() or not target.is_file() or self.home not in target.resolve(strict=True).parents:
                    return "Файл не удалила: путь изменился после подтверждения."
                target.unlink()
                return "Файл удалён."
            except OSError:
                return "Не получилось удалить файл."
        return "Действие не выполнено."

    def handle(self, raw: str) -> str | None:
        text = re.sub(r"\s+", " ", raw.lower().replace("ё", "е")).strip(" .,!?")
        if not text:
            return None

        if re.search(r"\b(который час|сколько времени|время сейчас)\b", text):
            return f"Сейчас {datetime.datetime.now():%H:%M}."
        if re.search(r"\b(какое сегодня число|какая сегодня дата|какой сегодня день)\b", text):
            return datetime.date.today().strftime("Сегодня %d.%m.%Y.")

        if text in {"спрячься", "скройся", "исчезни"}:
            return "__HIDE__"
        if text in {"выход", "закройся", "завершить работу"}:
            return "__QUIT__"

        volume = re.search(r"(?:громкость|звук)\s*(?:на\s*)?(\d{1,3})\s*%?", text)
        if volume and shutil.which("wpctl"):
            amount = max(0, min(100, int(volume.group(1))))
            if self._run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{amount}%"]):
                return f"Громкость установлена на {amount} процентов."
            return "Не получилось изменить громкость."
        if re.search(r"\b(громче|прибавь звук)\b", text):
            return self._volume_step("5%+")
        if re.search(r"\b(тише|убавь звук)\b", text):
            return self._volume_step("5%-")

        if re.search(r"\b(пауза|поставь на паузу|останови музыку)\b", text):
            return self._media("pause")
        if re.search(r"\b(продолжи|продолжай|сними с паузы)\b", text):
            return self._media("play")
        if re.search(r"\b(следующий трек|следующая песня)\b", text):
            return self._media("next")

        search = re.match(r"(?:найди|поищи|загугли|погугли|узнай)\s+(?:в интернете\s+)?(.+)", text)
        if search:
            url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(search.group(1))
            webbrowser.open(url)
            return "Открыла поиск в браузере."

        open_match = re.match(r"(?:открой|запусти|перейди на|зайди на)\s+(.+)", text)
        if open_match:
            target = open_match.group(1).strip()
            sites = {
                "ютуб": "https://www.youtube.com", "youtube": "https://www.youtube.com",
                "гугл": "https://www.google.com", "google": "https://www.google.com",
                "википедию": "https://ru.wikipedia.org", "википедия": "https://ru.wikipedia.org",
                "телеграм": "tg://", "telegram": "tg://",
            }
            if target in sites:
                webbrowser.open(sites[target])
                return f"Открываю {target}."
            if re.fullmatch(r"[\w.-]+\.[a-zа-я]{2,}(/\S*)?", target):
                webbrowser.open("https://" + target)
                return f"Открываю {target}."
            app_aliases = {
                "файлы": ("dolphin",), "проводник": ("dolphin",),
                "терминал": ("konsole",), "консоль": ("konsole",),
                "настройки": ("systemsettings",), "калькулятор": ("kcalc",),
                "браузер": ("firefox", "chromium", "google-chrome"),
            }
            for executable in app_aliases.get(target, ()):
                found = shutil.which(executable)
                if found and self._spawn([found]):
                    return f"Запускаю {target}."
            return f"Не нашла приложение «{target}» среди встроенных команд."

        create = re.match(r"(?:создай|сделай)\s+(?:новую\s+)?папку\s+(.+)", text)
        if create:
            return "Папку не создала: сначала нужно подтвердить действие."
        if self.is_destructive_request(text):
            return "Эта команда не выполнена. Подтверждение доступно только для конкретного файла или папки."

        return None

    @staticmethod
    def _spawn(args: list[str]) -> bool:
        try:
            subprocess.Popen(args, start_new_session=True, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
        except OSError:
            return False

    def _volume_step(self, step: str) -> str:
        if shutil.which("wpctl") and self._run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", step]):
            return "Сделала."
        return "Команда изменения громкости недоступна: не найден wpctl."

    def _media(self, action: str) -> str:
        if not shutil.which("playerctl"):
            return "Для управления музыкой установи playerctl."
        return "Готово." if self._run(["playerctl", action]) else "Сейчас нет плеера, которым можно управлять."
