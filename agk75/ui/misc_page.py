"""성능·기타: 디바운스, 절전 표시, 장치 옵션, USB 협상값, 폴링레이트 실측, 고정 정보."""
import math

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from ..i18n import t
from ..service import describe_error
from .page import Page
from .widgets import RangeRow, StateLabel, Switch, alive, button, card, clear_layout, h2, row, sub

OPTIONS = ["win_lock", "mac", "wasd_arrow", "led_off", "side_led_off", "keyboard_lock", "fn_matrix", "power_save"]


def dur(s):
    return t("dur.min", n=round(s / 60)) if s >= 60 else t("dur.sec", n=s)


def bold(text):
    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setStyleSheet("font-size: 15px; font-weight: 600;")
    return lb


class MiscPage(Page):
    name, label_key, icon, stage = "misc", "nav.misc", "misc", False

    def __init__(self, win):
        super().__init__(win)
        self.timer = QTimer()
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.measure_tick)
        self.deb = self.deb_state = self.optbox = self.usb_lbl = self.mres = self.mbar = self.mstart = None

    def leave(self):
        self.timer.stop()

    @staticmethod
    def _card(*widgets):
        c = card()
        lay = QVBoxLayout(c)
        lay.setContentsMargins(14, 14, 14, 14)
        for w in widgets:
            lay.addWidget(w)
        return c, lay

    def build(self):
        s = self.s
        self.lay.addWidget(h2(t("misc.title")))
        self.lay.addWidget(sub(t("misc.sub")))
        dev = s["device"]
        cards = [[self._debounce(), self._sleep(),
                  self._card(sub(t("misc.battery")), bold(t("misc.wired")), sub(t("misc.hidden")))[0],
                  self._card(sub(t("misc.device")), bold(t("misc.dev_id", id="-" if dev["id"] is None else dev["id"])),
                             sub(t("top.rev", rev="%04x" % (dev["revision"] or 0))))[0]],
                 [self._options()], [self._measure()]]
        cols = QHBoxLayout()
        cols.setSpacing(12)
        for col in cards:
            box = QVBoxLayout()
            box.setSpacing(12)
            for c in col:
                box.addWidget(c)
            box.addStretch(1)
            cols.addLayout(box, 1)
        self.lay.addLayout(cols)
        self.usb_refresh()
        self.measure_tick()

    # ---------- 카드 ----------
    def _debounce(self):
        self.deb = RangeRow(t("misc.time"), 0, 20, 1, self.s["debounce"] or 0, " ms")
        apply = button(t("misc.apply"), primary=True)
        apply.clicked.connect(self.apply_debounce)
        self.deb_state = StateLabel()
        return self._card(sub(t("misc.debounce")), self.deb, row(apply, stretch=True), self.deb_state)[0]

    def _sleep(self):
        sleeps = " / ".join(dur(x) for x in (self.s["sleep"] or [])) or "-"
        return self._card(sub(t("misc.sleep")), bold(sleeps), sub(t("misc.sleep_note")))[0]

    def _options(self):
        self.optbox = QWidget()
        QVBoxLayout(self.optbox).setContentsMargins(0, 0, 0, 0)
        c = self._card(sub(t("misc.options")), self.optbox, sub(t("misc.options_note")))[0]
        self.draw_options()
        return c

    def draw_options(self):
        lay = self.optbox.layout()
        clear_layout(lay)
        o = self.s["options"]
        if not o:
            return lay.addWidget(sub(t("opt.unreadable")))
        for k in OPTIONS:
            sw = Switch(bool(o[k]))
            sw.clicked.connect(lambda _=False, k=k: self.set_option(k))
            r = row(QLabel(t("opt." + k)), sw)
            r.layout().setStretch(0, 1)
            lay.addWidget(r)

    def _measure(self):
        self.usb_lbl = bold(t("usb.reading"))
        refresh = button(t("misc.refresh"))
        refresh.clicked.connect(self.usb_refresh)
        self.mstart = button(t("misc.start"), primary=True)
        self.mstart.clicked.connect(self.measure_start)
        self.mbar = QProgressBar()
        self.mbar.setRange(0, 100)
        self.mbar.setTextVisible(False)
        self.mres = QWidget()
        QVBoxLayout(self.mres).setContentsMargins(0, 0, 0, 0)
        return self._card(sub(t("misc.measure")), row(self.usb_lbl, refresh), sub(t("misc.usb_note")),
                          row(self.mstart, stretch=True), sub(t("misc.measure_note")), self.mbar, self.mres,
                          sub(t("misc.rate_hint")))[0]

    # ---------- 동작 ----------
    def apply_debounce(self):
        ms = int(self.deb.value())
        self.deb_state.set(t("rate.step.applying"))

        def done(j, err):
            ok = self.win.report(j, err, t("toast.deb_applied"))
            if not alive(self.deb_state):
                return
            if err is not None:
                return self.deb_state.set(describe_error(err), "bad")
            if ok:
                self.s["debounce"] = j["debounce"]
            self.deb_state.set(t("misc.deb_match" if j["applied"] else "misc.deb_mismatch", v=j["debounce"]),
                               "ok" if j["applied"] else "bad")
        self.win.run(lambda: self.win.svc.debounce(ms=ms), done)

    def set_option(self, k):
        o = self.s["options"]
        if not o:
            return
        if k == "keyboard_lock" and not o[k] and not self.win.confirm(t("opt.confirm_lock")):
            return self.draw_options()

        def done(j, err):
            self.win.report(j, err, t("toast.opt_applied"))
            if err is None and j.get("options") and self.s is not None:
                self.s["options"] = j["options"]
            if alive(self.optbox):
                self.draw_options()
        self.win.run(lambda: self.win.svc.options(**{k: not o[k]}), done)

    def usb_refresh(self):
        self.usb_lbl.setText(t("usb.reading"))

        def done(j, err):
            if not alive(self.usb_lbl):
                return
            if err is not None:
                self.usb_lbl.setText(describe_error(err))
            elif j.get("error"):
                self.usb_lbl.setText(j["error"])
            else:
                self.usb_lbl.setText(t("usb.result", us=j["poll_us"], hz=j["max_hz"], speed=j["speed"]))
        self.win.run(self.win.svc.usbinfo, done)

    # ---------- 측정 ----------
    def measure_start(self):
        def done(j, err):
            if err is not None:
                return self.win.fail(err)
            if alive(self.mres):
                self.timer.start()
                self.measure_tick()
        self.win.run(lambda: self.win.svc.measure_start(seconds=10), done)

    def measure_tick(self):
        def done(j, err):
            if not alive(self.mres):
                return self.timer.stop()
            if err is not None:
                self.timer.stop()
                return self.draw_measure({"error": describe_error(err)})
            self.draw_measure(j)
            self.mbar.setValue(round((1 - j["remaining"] / j["seconds"]) * 100) if j["running"] and j["seconds"]
                               else 100 if j["result"] else 0)
            self.mstart.setEnabled(not j["running"])
            if j["running"] and not self.timer.isActive():
                self.timer.start()
            elif not j["running"]:
                self.timer.stop()
        self.win.run(self.win.svc.measure_status, done, tag="mtick")

    def draw_measure(self, j):
        lay = self.mres.layout()
        clear_layout(lay)

        def line(text, kind=""):
            st = StateLabel()
            st.set(text, kind)
            lay.addWidget(st)
        if j.get("error"):
            return line(j["error"], "bad")
        if j["running"]:
            return line(t("measure.running", remaining=math.ceil(j["remaining"]), events=j["events"]))
        r = j["result"]
        if not r:
            return
        if r["min_ms"] is None:
            return line(t("measure.noevents"), "bad")
        if r["hz_at_least"]:
            lay.addWidget(bold(t("measure.summary", atleast=r["hz_at_least"], est=r["hz_estimate"], n=r["cluster_n"],
                                 ms="%.3f" % r["cluster_ms"])))
            if r["cluster_n"] < 10:
                line(t("measure.rough"))
        else:
            lay.addWidget(bold(t("measure.insufficient")))
        line(r["note"])
        line(t("measure.mininfo", min="%.3f" % r["min_ms"], samples=r["samples"]) +
             ("" if r["enough"] else t("measure.notenough")))
        top = max(1, *(h["count"] for h in r["hist"]))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        for i, h in enumerate(r["hist"]):
            bar = QProgressBar()
            bar.setRange(0, top)
            bar.setValue(h["count"])
            bar.setTextVisible(False)
            bar.setMaximumHeight(10)
            grid.addWidget(QLabel("%s ms" % h["label"]), i, 0)
            grid.addWidget(bar, i, 1)
            grid.addWidget(QLabel(str(h["count"])), i, 2)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
