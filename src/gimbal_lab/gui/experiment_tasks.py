import logging
import queue
import threading

from PySide6.QtCore import QThread, Signal


class ExperimentJob(QThread):
    event = Signal(object)

    def __init__(self, mode, action, parent=None):
        super().__init__(parent)
        self.mode, self.action = mode, action
        self.cancel_event = threading.Event()
        self.stdin_queue = queue.Queue()
        self.result, self.error = None, ''

    def run(self):
        try:
            self.result = self.action(self.cancel_event, self.event.emit, self.stdin_queue)
        except Exception as exc:
            logging.exception('Experiment job %s failed', self.mode)
            self.error = str(exc)
