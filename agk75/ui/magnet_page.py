"""래피드 트리거(자기 축): 키를 여러 개 골라 거리·데드존·RT 를 쓴다. 키마다 작동 거리를 열지도로 보여 준다."""
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QProgressBar, QWidget, QVBoxLayout

from ..i18n import t
from ..service import describe_error
from .layout import LAYOUT
from .page import Page
from .widgets import RangeRow, StateLabel, Switch, alive, button, h2, h3, row, sub

FIELDS = [("travel", 0.1, 3.5), ("lift", 0.1, 3.5), ("dead", 0, 1), ("rt_press", 0.1, 2), ("rt_lift", 0.1, 2)]


class MagnetPage(Page):
    name, label_key, icon, stage, multi, legend_key = "magnet", "nav.magnet", "magnet", True, True, "mag.legend"

    def __init__(self, win):
        super().__init__(win)
        self.vals, self.touched, self.busy = None, set(), False
        self.rows = {}
        self.rt_fx = self.count = self.bar = self.state_lbl = self.rt = self.rtbox = self.apply_sel = self.apply_all = None

    # ---------- 키보드 그림 ----------
    def key_sub(self, i):
        return "%.1f" % self.s["magnet"][i]["travel"]

    def key_fill(self, i):
        frac = (self.s["magnet"][i]["travel"] - 0.1) / 3.4
        return QColor.fromHslF(max(0.0, min(1.0, (215 - 210 * frac) / 360)), 0.6, 0.3)

    def selection_changed(self):
        self.load_vals()
        self.sync()

    # ---------- 화면 ----------
    def load_vals(self):
        self.vals = dict(self.s["magnet"][min(self.win.sel) if self.win.sel else 0])
        self.touched.clear()

    def state(self, text, kind=""):
        if alive(self.state_lbl):
            self.state_lbl.set(text, kind)

    def build(self):
        if not self.win.sel:
            self.win.sel.add(0)
        self.load_vals()
        lay = self.lay
        lay.addWidget(h2(t("mag.title")))
        self.count = sub("")
        lay.addWidget(self.count)
        selall, clear = button(t("mag.selall")), button(t("mag.clear"))
        selall.clicked.connect(lambda: self._select({k[0] for k in LAYOUT}))
        clear.clicked.connect(lambda: self._select(set()))
        lay.addWidget(row(selall, clear, stretch=True))
        lay.addWidget(h3(t("mag.dist")))
        self.rows = {}
        for k, lo, hi in FIELDS[:3]:
            lay.addWidget(self._field(k, lo, hi))
        self.rt = Switch(self.vals["rt"])
        self.rt.clicked.connect(self._toggle_rt)
        lay.addWidget(row(QLabel(t("mag.rt")), self.rt, stretch=True))
        self.rtbox = QWidget()
        box = QVBoxLayout(self.rtbox)
        box.setContentsMargins(0, 0, 0, 0)
        for k, lo, hi in FIELDS[3:]:
            box.addWidget(self._field(k, lo, hi))
        self.rt_fx = QGraphicsOpacityEffect(self.rtbox)
        self.rtbox.setGraphicsEffect(self.rt_fx)
        lay.addWidget(self.rtbox)
        lay.addWidget(sub(t("mag.hint")))
        self.apply_sel, self.apply_all = button(t("mag.apply_sel"), primary=True), button(t("mag.apply_all"))
        self.apply_sel.clicked.connect(self.apply_keys)
        self.apply_all.clicked.connect(self.apply_everything)
        lay.addWidget(row(self.apply_sel, self.apply_all, stretch=True))
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        lay.addWidget(self.bar)
        self.state_lbl = StateLabel()
        lay.addWidget(self.state_lbl)
        self.sync()

    def _field(self, k, lo, hi):
        r = RangeRow(t("mag." + k), lo, hi, 0.1, self.vals[k], " mm")
        r.changed.connect(lambda v, k=k: self._user_set(k, v))
        self.rows[k] = r
        return r

    def _user_set(self, k, v):
        self.vals[k] = v
        self.touched.add(k)

    def _toggle_rt(self):
        self.vals["rt"] = self.rt.isChecked()
        self.touched.add("rt")
        self.sync()

    def _select(self, keys):
        self.win.sel.clear()
        self.win.sel.update(keys)
        self.win.paint()
        self.sync()

    def sync(self):
        if not alive(self.count):
            return
        for k, r in self.rows.items():
            r.set_value(self.vals[k])
        self.rt.set_silent(self.vals["rt"])
        self.rt_fx.setOpacity(1 if self.vals["rt"] else 0.4)
        n = len(self.win.sel)
        self.count.setText(t("mag.count", n=n) if n else t("mag.none_sel"))
        self.apply_sel.setEnabled(not self.busy)
        self.apply_all.setEnabled(not self.busy)

    # ---------- 쓰기 ----------
    def _body(self):
        return {k: self.vals[k] for k in self.touched}

    def progress(self, n, total, idx=None):
        """작업 스레드에서 화면 스레드로 넘어온 진행 알림."""
        if not alive(self.bar):
            return
        self.bar.setValue(round(n / total * 100))
        self.state(t("mag.progress", n=n, total=total, idx=idx) if idx is not None
                   else t("mag.all_progress", n=n, total=total))

    def apply_keys(self):
        idxs = sorted(self.win.sel)
        if not idxs:
            return self.win.toast(t("mag.need_sel"), "bad")
        if not self.touched:
            return self.win.toast(t("mag.no_change"), "bad")
        body, svc, win = self._body(), self.win.svc, self.win
        self.busy = True
        self.sync()
        win.long_start()

        def job():
            out = []
            for n, idx in enumerate(idxs):
                win.worker.call_ui(lambda n=n, idx=idx: self.progress(n + 1, len(idxs), idx))
                try:
                    out.append((idx, svc.magnet(idx=idx, **body), None))
                except Exception as e:  # 한 키에서 실패하면 멈추고 원인을 보여 준다
                    out.append((idx, None, e))
                    break
            return out

        def done(out, err):
            win.long_end()
            self.busy = False
            bad, fail = [], None
            for idx, res, e in out or []:
                if res is not None and self.s is not None:
                    self.s["magnet"][idx] = res["magnet"]
                if res is None or not res["applied"]:
                    bad.append(idx)
                fail = fail or e
            if fail or err:
                win.fail(fail or err)
            self.finish(t("mag.bad_keys", keys=", ".join(map(str, bad))) if bad else "", len(idxs))
        win.run(job, done)

    def apply_everything(self):
        if not self.touched:
            return self.win.toast(t("mag.no_change"), "bad")
        if not self.win.confirm(t("mag.confirm_all")):
            return
        body, svc, win = self._body(), self.win.svc, self.win
        self.busy = True
        self.sync()
        win.long_start()

        def done(out, err):
            win.long_end()
            self.busy = False
            if err is not None:
                win.fail(err)
                self.state(describe_error(err), "bad")
                return self.sync()
            res, st = out
            if self.s is not None:
                self.s["magnet"] = st["magnet"]
            self.finish(t("mag.bad_all", keys=", ".join(map(str, res["failed"]))) if not res["applied"] else "", 128)
        win.run(lambda: (svc.magnet_all(**body), svc.state()), done)

    def finish(self, bad, n):
        if bad:
            self.win.show_banner(bad)
            self.win.toast(bad, "bad", 5000)
        else:
            self.win.report({"applied": True}, None, t("mag.done", n=n))
        self.win.paint()
        if alive(self.count):
            self.sync()
        self.state(bad or t("state.match0"), "bad" if bad else "ok")
        if not bad:
            self.touched.clear()
