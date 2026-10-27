import threading
import unittest
from speech_queue import SpeechQueue


class SpeechTests(unittest.TestCase):
    def test_replacement_is_serial_and_only_latest_finishes(self):
        started = threading.Event()
        done = threading.Event()
        calls, finished, mute = [], [], []
        class Speaker:
            def say(self, text, cancel):
                calls.append(('start', text))
                if text == 'first':
                    started.set()
                    if not cancel.wait(2):
                        raise AssertionError('not cancelled')
                calls.append(('end', text))
        queue = SpeechQueue(Speaker(), mute.append, lambda g: (finished.append(g), done.set()))
        try:
            queue.submit('first')
            self.assertTrue(started.wait(2))
            queue.submit('second')
            self.assertTrue(done.wait(2))
            self.assertEqual(calls, [('start','first'),('end','first'),('start','second'),('end','second')])
            self.assertEqual(finished, [2])
            self.assertEqual(mute, [True,True,False])
        finally:
            queue.close()
            queue.thread.join(2)
        self.assertFalse(queue.thread.is_alive())

    def test_playback_error_unmutes_and_worker_survives(self):
        done = threading.Event()
        mute = []
        class Speaker:
            def say(self, text, cancel):
                raise RuntimeError('simulated playback failure')
        queue = SpeechQueue(Speaker(), mute.append, lambda g: done.set())
        try:
            with self.assertLogs('capri', level='ERROR'):
                queue.submit('bad')
                self.assertTrue(done.wait(2))
            self.assertEqual(mute, [True,False])
            self.assertTrue(queue.thread.is_alive())
        finally:
            queue.close()
            queue.thread.join(2)

class MicrophoneTests(unittest.TestCase):
    def test_muted_audio_is_drained_not_recognized(self):
        import tempfile
        import pathlib
        import types
        from unittest.mock import patch
        from linux_voice import LinuxListener
        accepted = []
        listener = LinuxListener('/unused', lambda *a: None, lambda *a: None, lambda *a: None)
        listener.muted.set()
        class Recognizer:
            def Reset(self): pass
            def AcceptWaveform(self, data):
                accepted.append(data)
                return False
            def PartialResult(self): return '{}'
        class Pipe:
            n = 0
            def read(self, size):
                self.n += 1
                if self.n == 1:
                    return b'speaker audio'
                if self.n == 2:
                    listener.muted.clear()
                    listener.reset_req.set()
                    return b'speaker tail'
                listener.stop_req.set()
                return b'user audio'
        process = types.SimpleNamespace(stdout=Pipe(), poll=lambda: None, terminate=lambda: None)
        vosk = types.SimpleNamespace(SetLogLevel=lambda x: None, Model=lambda x: None,
                                     KaldiRecognizer=lambda *a: Recognizer())
        with tempfile.TemporaryDirectory() as directory:
            listener.model_path = pathlib.Path(directory)
            (listener.model_path/'am').mkdir()
            (listener.model_path/'am/final.mdl').touch()
            with patch.dict('sys.modules', {'vosk':vosk}), patch.object(listener, '_command', return_value=['fake']), patch('linux_voice.subprocess.Popen', return_value=process):
                listener.run()
        self.assertEqual(accepted, [b'user audio'])
        self.assertEqual(process.stdout.n, 3)

class ShutdownTests(unittest.TestCase):
    def test_close_waits_for_active_speech_to_cancel(self):
        started, stopped = threading.Event(), threading.Event()
        mute = []
        class Speaker:
            def say(self, text, cancel):
                started.set()
                cancel.wait(2)
                stopped.set()
        queue = SpeechQueue(Speaker(), mute.append, lambda g: None)
        queue.submit('speaking')
        self.assertTrue(started.wait(2))
        queue.close()
        self.assertTrue(stopped.is_set())
        self.assertFalse(queue.thread.is_alive())
        self.assertEqual(mute[-1], False)
