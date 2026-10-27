"""Memory tests never contact Ollama or read/write the user's saved state."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import local_ai


class MemorySafetyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state_dir = Path(temporary.name)
        self.memory_path = self.state_dir / "memory.json"
        self.memory_path.write_text(json.dumps({
            "facts": ["Старая заметка"],
            "history": [{"role": "user", "content": "Старый вопрос"}],
        }), encoding="utf-8")
        for name, value in (("STATE_DIR", self.state_dir), ("MEMORY_PATH", self.memory_path)):
            patcher = patch.object(local_ai, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        context = patch.object(local_ai, "user_context", return_value="")
        context.start()
        self.addCleanup(context.stop)
        self.ai = local_ai.LocalAI({})

    def _clear_during_request(self, fail=False):
        started = threading.Event()
        release = threading.Event()
        cleared = threading.Event()
        results, errors = [], []

        def chat(*args, **kwargs):
            started.set()
            if not release.wait(5):
                raise TimeoutError("test did not release response")
            if fail:
                raise OSError("simulated connection failure")
            return "Ответ по старой заметке."

        def ask():
            try:
                results.append(self.ai.ask("Расскажи о моей заметке"))
            except BaseException as error:
                errors.append(error)

        def clear():
            try:
                self.ai.clear_memory()
                cleared.set()
            except BaseException as error:
                errors.append(error)

        with patch.object(self.ai, "_chat", side_effect=chat):
            worker = threading.Thread(target=ask, daemon=True)
            worker.start()
            clearer = None
            try:
                self.assertTrue(started.wait(2), "HTTP stub was not reached")
                clearer = threading.Thread(target=clear, daemon=True)
                clearer.start()
                self.assertTrue(cleared.wait(2), "clear_memory blocked behind HTTP")
                # New data written after clearing must survive a stale result/error.
                self.ai.ask("Запомни: новая заметка")
                expected = self.memory_path.read_text(encoding="utf-8")
            finally:
                release.set()
                worker.join(3)
                if clearer:
                    clearer.join(3)
            self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results, [None])
        self.assertEqual(self.ai.history, [])
        self.assertEqual(self.ai.memory, ["новая заметка"])
        self.assertEqual(self.memory_path.read_text(encoding="utf-8"), expected)

    def test_success_after_clear_is_discarded(self):
        self._clear_during_request()

    def test_error_after_clear_does_not_pop_empty_history(self):
        self._clear_during_request(fail=True)

    def test_clear_command_requires_confirmation(self):
        before = self.memory_path.read_text(encoding="utf-8")
        with patch.object(self.ai, "_chat", side_effect=AssertionError("must not call model")):
            for command in ("очисти память", "Забудь всё!", "забудь все обо мне", "Капри, очисти память!"):
                with self.subTest(command=command):
                    self.assertTrue(local_ai.LocalAI.is_clear_memory_request(command))
                    self.assertIn("Подтверди", self.ai.ask(command))
        self.assertEqual(self.memory_path.read_text(encoding="utf-8"), before)
        self.assertEqual(self.ai.memory, ["Старая заметка"])
        self.assertFalse(local_ai.LocalAI.is_clear_memory_request("покажи память"))

    def test_normal_answer_is_saved(self):
        with patch.object(self.ai, "_chat", return_value="Готово."):
            self.assertEqual(self.ai.ask("Привет"), "Готово.")
        saved = json.loads(self.memory_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["history"][-2:], [
            {"role": "user", "content": "Привет"},
            {"role": "assistant", "content": "Готово."},
        ])

    def test_connection_failure_removes_only_its_question(self):
        with patch.object(self.ai, "_chat", side_effect=OSError("offline")):
            self.assertIsNone(self.ai.ask("Новый вопрос"))
        self.assertEqual(self.ai.history, [{"role": "user", "content": "Старый вопрос"}])


if __name__ == "__main__":
    unittest.main()
