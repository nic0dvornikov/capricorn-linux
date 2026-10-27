"""One cancellable speech worker; only it owns playback and microphone mute."""
import threading
import logging


class SpeechQueue:
    def __init__(self, speaker, mute, finished):
        self.speaker, self.mute, self.finished = speaker, mute, finished
        self.condition = threading.Condition()
        self.generation = 0
        self.pending = None
        self.active = None
        self.closed = False
        self.thread = threading.Thread(target=self._run, name="capri-speech", daemon=True)
        self.thread.start()

    def submit(self, text):
        with self.condition:
            if self.closed:
                return
            self.generation += 1
            if self.active:
                self.active.set()
            self.pending = (self.generation, text)
            self.condition.notify()

    def cancel(self):
        with self.condition:
            self.generation += 1
            self.pending = None
            if self.active:
                self.active.set()

    def close(self):
        with self.condition:
            self.cancel()
            self.closed = True
            self.condition.notify()
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout=3)
        if self.thread.is_alive():
            stop = getattr(self.speaker, "stop_playback", None)
            if stop:
                stop()

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.pending is not None)
                if self.closed:
                    return
                generation, text = self.pending
                self.pending = None
                cancel = self.active = threading.Event()
                self.mute(True)
            try:
                self.speaker.say(text, cancel)
            except Exception:
                logging.getLogger("capri").exception("Speech playback failed")
            finally:
                with self.condition:
                    self.active = None
                    if self.pending is None:
                        self.mute(False)
                    if generation == self.generation and not self.closed:
                        self.finished(generation)
