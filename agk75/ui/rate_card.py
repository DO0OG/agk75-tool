"""키 설정 화면의 폴링레이트 카드. PC 쪽 USB 필터 드라이버(hidusbf)로 바꾸며, 실행은 전부 작업 스레드에서 한다."""
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from ..i18n import t
from ..service import describe_error
from .widgets import Seg, StateLabel, alive, button, card, clear_layout

RATES = [8000, 4000, 2000, 1000]


class RateCard:
    """카드 모델 + 화면. 언어 전환으로 화면이 다시 만들어져도 진행 중인 작업의 상태는 이 객체에 남는다."""

    def __init__(self, win):
        self.win = win
        self.state = None  # rate_state() 결과
        self.busy, self.step, self.res, self.cls = False, "", "", ""
        self.frame = None

    # ---------- 화면 ----------
    def build(self):
        """카드 위젯을 새로 만들어 돌려준다."""
        self.frame = card()
        QVBoxLayout(self.frame).setContentsMargins(14, 14, 14, 14)
        self.refresh()
        return self.frame

    def usb_hz(self):
        u = (self.state or {}).get("usb") or self.win.s.get("usb")
        return (u or {}).get("max_hz")

    def status_text(self):
        s = (self.state or {}).get("state")
        if not s:
            return t("rate.status.checking")
        if not s["device"]:
            return s.get("device_error") or t("rate.status.nodev")
        if not s["service"] or not s["sys"]:
            return t("rate.status.nodriver_ready" if s["package"] else "rate.status.nodriver_need")
        if not s["filter"]:
            return t("rate.status.nofilter")
        if s["configured_hz"]:
            return t("rate.status.active_hz", hz=s["configured_hz"])
        return t("rate.status.active_bi", b=s["binterval"])

    def refresh(self):
        if not alive(self.frame):
            return
        lay = self.frame.layout()
        clear_layout(lay)
        s = (self.state or {}).get("state")
        hz = self.usb_hz()
        cur = None if not s else s["configured_hz"] if s["filter"] else 8000
        head = QHBoxLayout()
        title = QLabel("<b>%s</b>" % t("rate.title"))
        head.addWidget(title)
        usb = QLabel(t("rate.usb_now", hz=hz) if hz else "")
        usb.setProperty("sub", True)
        head.addWidget(usb, 1)
        lay.addLayout(head)
        seg = Seg([(r, t("rate.off8000") if r == 8000 else "%dHz" % r) for r in RATES], cur)
        seg.set_enabled_all(not (self.busy or not s or not s["device"]))
        seg.changed.connect(self.apply)
        prep = button(t("rate.prepare"), enabled=not self.busy)
        prep.clicked.connect(self.prepare)
        for w in (seg, prep):
            line = QHBoxLayout()
            line.addWidget(w)
            line.addStretch(1)
            lay.addLayout(line)
        self._line(lay, self.status_text())
        if s and s["hvci"]:
            self._line(lay, t("rate.hvci"), "bad")
        self._line(lay, t("rate.table_warn"), "bad")
        if self.busy:
            self._line(lay, self.step)
        if self.res:
            self._line(lay, self.res, self.cls)
        self._line(lay, t("rate.note"))

    @staticmethod
    def _line(lay, text, kind=""):
        st = StateLabel()
        st.set(text, kind)
        lay.addWidget(st)

    # ---------- 동작 ----------
    def load(self):
        def done(res, err):
            if err is None:
                self.state = res
            else:
                self.res, self.cls = t("rate.load_fail") + ": " + describe_error(err), "bad"
            self.refresh()
        self.win.run(self.win.svc.rate_state, done, tag="rate_state")

    def result(self, j, err, hz):
        if err is not None:
            return "bad", describe_error(err)
        if j.get("prepared"):
            return "ok", t("rate.res.prepared_nopatch" if j["nopatch"] else "rate.res.prepared")
        if not j["applied"]:
            return "bad", t("rate.res.failed", msg=j["message"] or t("rate.res.unknown"))
        if j["reboot_needed"]:
            return "bad", t("rate.res.reboot")
        got = (j.get("usb") or {}).get("max_hz")
        if not got:
            return "", t("rate.res.nocheck")
        if got == hz:
            return "ok", t("rate.res.ok", hz=got)
        return "bad", t("rate.res.mismatch", got=got, want=hz)

    def run(self, fn, step_key, hz):
        if self.busy:
            return
        self.busy, self.step, self.res, self.cls = True, t(step_key), "", ""
        self.refresh()
        self.win.long_start()

        def done(j, err):
            self.win.long_end()
            self.busy = False
            self.cls, self.res = self.result(j, err, hz)
            if err is None and (j.get("usb") or {}) and "error" not in j["usb"]:
                self.win.s["usb"] = j["usb"]
            self.refresh()
            self.load()
        self.win.run(fn, done)

    def apply(self, hz):
        s = (self.state or {}).get("state")
        if s and not s["service"] and not self.win.confirm(t("rate.confirm_install")):
            self.refresh()
            return
        svc = self.win.svc
        self.run(svc.rate_reset if hz == 8000 else (lambda: svc.rate_set(hz=hz)), "rate.step.applying", hz)

    def prepare(self):
        self.run(self.win.svc.rate_prepare, "rate.step.downloading", 8000)

    def on_step(self, text):
        if self.busy:
            self.step = text
            self.refresh()
