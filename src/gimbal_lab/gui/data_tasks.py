"""Bounded background image and dataset jobs. Workers never edit GUI state."""
import logging
import threading
import time

from PySide6.QtCore import QObject, QRunnable, QThread, Signal

from gimbal_lab.domain.camera import render_frame


class PreviewSignals(QObject):
    done = Signal(int, object, str)


class PreviewTask(QRunnable):
    def __init__(self, revision, state):
        super().__init__()
        self.revision = revision
        self.state = state
        self.signals = PreviewSignals()

    def run(self):
        try:
            result = render_frame(self.state)
            self.signals.done.emit(self.revision, result, "")
        except Exception as exc:
            self.signals.done.emit(self.revision, None, str(exc))


class DatasetJob(QThread):
    progress = Signal(object, object, int, int)

    def __init__(self, operation, action, parent=None):
        super().__init__(parent)
        self.operation, self.action = operation, action
        self.cancel_event = threading.Event()
        self.result, self.error = None, ""
        self.last_progress = 0.0

    def report(self, record, frame, valid, failed):
        now = time.monotonic()
        if now - self.last_progress >= 0.08:
            self.progress.emit(record, frame, valid, failed)
            self.last_progress = now

    def run(self):
        try:
            self.result = self.action(self.cancel_event, self.report)
        except Exception as exc:
            logging.exception("Dataset job %s failed", self.operation)
            self.error = str(exc)
