"""장치·관리자·측정 호출을 전부 직렬로 실행하는 단일 작업 스레드. 화면은 시그널로만 갱신한다."""
import queue
import threading

from PySide6.QtCore import QThread, Signal


class Worker(QThread):
    done = Signal(object)  # (콜백, 결과, 예외) — 화면 스레드에서 받는다
    ui_call = Signal(object)  # 작업 중 화면을 갱신할 함수를 화면 스레드로 넘긴다

    def __init__(self, on_exit=None, parent=None):
        super().__init__(parent)
        self._q, self._lock = queue.Queue(), threading.Lock()
        self._pending, self._tags, self._on_exit = 0, set(), on_exit
        self.done.connect(self._dispatch)
        self.ui_call.connect(self._ui_run)

    def submit(self, fn, cb=None, tag=None):
        """fn 을 큐에 넣는다. 같은 tag 의 작업이 이미 대기·실행 중이면 버린다(False)."""
        with self._lock:
            if tag is not None and tag in self._tags:
                return False
            if tag is not None:
                self._tags.add(tag)
            self._pending += 1
        self._q.put((fn, cb, tag))
        return True

    def busy(self):
        with self._lock:
            return self._pending > 0

    def call_ui(self, fn):
        self.ui_call.emit(fn)

    def stop(self):
        self._q.put(None)

    def run(self):
        try:
            while True:
                job = self._q.get()
                if job is None:
                    break
                fn, cb, tag = job
                res = err = None
                try:
                    res = fn()
                except BaseException as e:  # 예외는 화면에서 토스트로 보여 준다
                    err = e
                with self._lock:
                    self._pending -= 1
                    self._tags.discard(tag)
                self.done.emit((cb, res, err))
        finally:
            if self._on_exit:
                self._on_exit()

    def _ui_run(self, fn):
        fn()

    def _dispatch(self, item):
        cb, res, err = item
        if cb:
            cb(res, err)
