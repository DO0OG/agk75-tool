"""메인 창: 상단 바, 왼쪽 내비, 키보드 그림, 화면 묶음(QStackedWidget), 토스트."""
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from .. import i18n
from ..i18n import t
from ..service import describe_error
from . import theme
from .backup_page import BackupPage
from .chrome import Legend, NoDevicePage, nav, top_bar
from .keyboard_widget import KeyboardWidget
from .keys_page import KeysPage
from .layout import LAYOUT
from .light_page import LightPage
from .magnet_page import MagnetPage
from .misc_page import MiscPage
from .worker import Worker

PANEL_W = 360


class MainWindow(QMainWindow):
    def __init__(self, svc, settings=None, poll_ms=2000):
        super().__init__()
        self.svc, self.s, self.sel = svc, None, set()
        self.conn, self.reconn, self.loading, self.long_jobs, self._last_err = None, 0, False, 0, None
        self.settings = settings or QSettings(QSettings.IniFormat, QSettings.UserScope, "DO0OG", "AGK75Tool")
        saved = str(self.settings.value("lang", ""))
        i18n.set_lang(saved if saved in i18n.LANGS else i18n.system_lang())
        self.worker = Worker(on_exit=svc.close)
        svc.on_progress = lambda n, total: self.worker.call_ui(lambda: self._progress(n, total))
        svc.on_step = lambda key: self.worker.call_ui(lambda: self._step(key))
        self.pages = {p.name: p for p in (KeysPage(self), LightPage(self), MagnetPage(self), MiscPage(self),
                                          BackupPage(self))}
        self.view = "keys"
        self.nodev = NoDevicePage(self)
        self._build()
        self.worker.start()
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll)
        self.poll_timer.start(poll_ms)
        self.retranslate()
        self.load()

    # ---------- 화면 뼈대 ----------
    def _build(self):
        self.resize(1280, 800)
        self.setMinimumSize(1100, 700)
        root = QWidget(self)
        root.setObjectName("root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(top_bar(self))
        self.banner = QLabel()
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)
        self.banner.hide()
        v.addWidget(self.banner)
        body = QHBoxLayout()
        body.setSpacing(0)
        body.addWidget(nav(self))
        main = QHBoxLayout()
        main.setContentsMargins(14, 14, 14, 14)
        main.setSpacing(14)
        main.addWidget(self._stage(), 1)
        main.addWidget(self._panel())
        body.addLayout(main, 1)
        v.addLayout(body, 1)
        self.toasts = QWidget(root)
        self.toasts.setAttribute(Qt.WA_TransparentForMouseEvents)
        QVBoxLayout(self.toasts).setSpacing(8)
        self.toasts.layout().setContentsMargins(0, 0, 0, 0)

    def _stage(self):
        self.stage = QFrame()
        self.stage.setObjectName("card")
        lay = QVBoxLayout(self.stage)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(14)
        lay.addStretch(1)
        self.kb = KeyboardWidget()
        self.kb.keyPressed.connect(lambda i, add: self.select(i, add, False))
        self.kb.keyDragged.connect(lambda i: self.select(i, True, True))
        self.legend = Legend()
        lay.addWidget(self.kb)
        lay.addWidget(self.legend)
        lay.addStretch(1)
        return self.stage

    def _panel(self):
        self.panel = QFrame()
        self.panel.setObjectName("card")
        lay = QVBoxLayout(self.panel)
        lay.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack)
        self.scrolls = {}
        for name, page in [*self.pages.items(), ("nodev", self.nodev)]:
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.NoFrame)
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            page.setContentsMargins(18, 18, 18, 18)
            sc.setWidget(page)
            self.stack.addWidget(sc)
            self.scrolls[name] = sc
        return self.panel

    # ---------- 작업 실행 ----------
    def run(self, fn, cb=None, tag=None):
        """fn 을 작업 스레드에서 실행하고 cb(결과, 예외)를 이 스레드에서 부른다."""
        return self.worker.submit(fn, cb or (lambda res, err: err and self.fail(err)), tag)

    def fail(self, err):
        """예외를 번역된 문구로 토스트에 보인다. 장치 통신 오류면 연결 끊김으로 표시한다."""
        if isinstance(err, OSError):
            self.set_conn(False)
        self.toast(describe_error(err), "bad", 5000)

    def report(self, res, err, ok_msg=None):
        """쓰기 결과 처리: 예외·되읽기 불일치는 빨간색. 정상 적용이면 True."""
        if err is not None:
            self.fail(err)
            return False
        if res.get("applied") is False:
            self.show_banner(t("banner.mismatch"))
            self.toast(t("toast.mismatch"), "bad", 5000)
            return False
        self.banner.hide()
        self.toast(ok_msg or t("toast.applied"))
        return True

    def show_banner(self, text):
        self.banner.setText(text)
        self.banner.show()

    def confirm(self, text):
        box = QMessageBox(QMessageBox.Question, t("app.title"), text, QMessageBox.NoButton, self)
        yes = box.addButton(t("common.yes"), QMessageBox.YesRole)
        box.setDefaultButton(box.addButton(t("common.no"), QMessageBox.NoRole))
        box.exec()
        return box.clickedButton() is yes

    def long_start(self):
        self.long_jobs += 1

    def long_end(self):
        self.long_jobs = max(0, self.long_jobs - 1)

    def _progress(self, n, total):
        page = self.pages["magnet"]
        page.progress(n, total)

    def _step(self, key):
        self.pages["keys"].rate_step(t(key))

    # ---------- 토스트·연결 ----------
    def toast(self, text, kind="ok", ms=2600):
        lb = QLabel(text)
        lb.setProperty("toast", True)
        lb.setProperty("kind", kind)
        lb.setAlignment(Qt.AlignCenter)
        lb.setMaximumWidth(max(300, self.width() - 200))
        lb.setWordWrap(True)
        self.toasts.layout().addWidget(lb)
        QTimer.singleShot(ms, lambda: (lb.setParent(None), lb.deleteLater(), self._place_toasts()))
        self._place_toasts()

    def _place_toasts(self):
        self.toasts.adjustSize()
        self.toasts.move((self.width() - self.toasts.width()) // 2, self.height() - 18 - self.toasts.height())
        self.toasts.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_toasts()

    def set_conn(self, on):
        if self.conn == on:
            return
        self.conn = on
        self._draw_conn()

    def _draw_conn(self):
        color = {None: theme.MUTED, True: theme.OK, False: theme.BAD}[self.conn]
        self.dot.setStyleSheet("background:%s; border-radius:4px;" % color)
        key = "conn.checking" if self.conn is None else "conn.on" if self.conn else "conn.off"
        self.conn_text.setText(t(key))

    # ---------- 언어·상단 바 ----------
    def set_lang(self, code):
        i18n.set_lang(code)
        self.settings.setValue("lang", i18n.lang())
        self.settings.sync()
        self.retranslate()
        self.render()

    def retranslate(self):
        QApplication.instance().setStyleSheet(theme.qss(i18n.lang()))
        self.setWindowTitle(t("app.title"))
        self.lang_seg.set_current(i18n.lang())
        self.profile_label.setText(t("top.profile"))
        self._draw_conn()
        for name, page in self.pages.items():
            label = t(page.label_key)
            label = label.replace(" ", chr(10), 1) if len(label) > 6 else label
            self.nav[name].setText(label.replace("&", "&&"))  # & 는 단축키 표시라 두 번 쓴다
        self.nav[self.view].setChecked(True)
        self.draw_top()

    def draw_top(self):
        rev = ((self.s or {}).get("device") or {}).get("revision") or 0
        self.rev.setText(t("top.rev", rev="%04x" % rev) if self.s else "")
        if self.s and self.s.get("profile") is not None:
            self.profile_seg.set_current(self.s["profile"])

    def _set_profile(self, layer):
        if self.s is None:
            return

        def done(res, err):
            if self.report(res, err, t("toast.profile", n=layer + 1)):
                self.s["profile"] = res["profile"]
                self.paint()
            self.draw_top()
        self.run(lambda: self.svc.profile(layer=layer), done)

    # ---------- 선택·그리기 ----------
    def page(self):
        return self.pages[self.view]

    def select(self, idx, add, drag):
        if self.s is None:
            return
        pg = self.page()
        if pg.on_key(idx):
            return
        if not pg.multi or (not add and not drag):
            self.sel.clear()
        if pg.multi and add and not drag and idx in self.sel:
            self.sel.discard(idx)
        else:
            self.sel.add(idx)
        self.paint()
        pg.selection_changed()

    def paint(self):
        if self.s is None:
            return
        pg = self.page()
        self.kb.set_cells({i: (pg.key_text(i), pg.key_sub(i), pg.key_fill(i), pg.key_dim(i)) for i, *_ in LAYOUT})
        self.kb.set_selected(self.sel)

    def show_view(self, name):
        self.page().leave()
        self.view = name
        self.sel.clear()
        self.nav[name].setChecked(True)
        self.kb.set_glow(None, 1.0)
        self.render()

    def render(self):
        pg = self.page()
        self.legend.set(pg.legend_key, bar=(self.view == "magnet"))
        if self.s is None:
            self.stage.hide()
            self.nodev.render()
            self.stack.setCurrentWidget(self.scrolls["nodev"])
        else:
            self.stage.setVisible(pg.stage)
            self.stack.setCurrentWidget(self.scrolls[self.view])
            pg.render()
            self.paint()
        if self.stage.isHidden():
            self.panel.setMinimumWidth(0)
            self.panel.setMaximumWidth(16777215)
        else:
            self.panel.setFixedWidth(PANEL_W)

    # ---------- 불러오기·연결 감시 ----------
    def load(self):
        if self.loading:
            return
        self.loading = True
        self.run(self.svc.state, self._on_state)

    def _on_state(self, res, err):
        self.loading = False
        self.s = res if err is None else None
        if err is None:
            self.set_conn(True)
            self._last_err = None
        elif isinstance(err, OSError):
            self.set_conn(False)
        elif str(err) != self._last_err:
            self._last_err = str(err)
            self.fail(err)
        self.draw_top()
        self.page().leave()
        self.sel.clear()
        self.render()

    def _poll(self):
        if not self.worker.busy():
            self.run(self.svc.poll, self._on_poll, tag="poll")

    def _on_poll(self, res, err):
        if err is not None:
            self.set_conn(False)
            return
        was = self.conn
        self.set_conn(res["connected"])
        if not res["connected"]:
            return
        if was is False:
            self.reconn += 1  # 재연결 횟수(폴링레이트 적용 확인용)
        if self.s is None or was is False:
            self.load()
        elif res.get("profile") is not None and res["profile"] != self.s["profile"]:
            self.s["profile"] = res["profile"]
            self.draw_top()
            self.paint()

    # ---------- 종료 ----------
    def closeEvent(self, e):
        if self.long_jobs and not self.confirm(t("close.busy")):
            e.ignore()
            return
        self.poll_timer.stop()
        self.worker.stop()
        if not self.worker.wait(3000):  # 장치 쓰기가 멈추지 않으면 강제로 끝낸다(사용자가 확인함)
            self.worker.terminate()
            self.worker.wait(1000)
        e.accept()
