"""조명: 값을 바꾸면 300ms 뒤 자동 적용하고, 장치가 되돌려 준 값으로 확정한다. 본체와 측면 조명은 같은 편집기를 쓴다."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import i18n
from .. import protocol as P
from ..i18n import t
from ..service import describe_error
from .page import Page
from .widgets import RangeRow, Seg, StateLabel, Switch, alive, h2, h3, hr, row, sub


def hexc(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


def gloss(name):
    """영문 원명은 그대로 두고 언어별 병기명만 붙인다(원명과 같으면 생략)."""
    key = "fx." + name
    g = t(key) if key in i18n.MSG[i18n.lang()] else ""
    return "" if g.lower() == name.lower() else g


class FxButton(QPushButton):
    def __init__(self, name):
        super().__init__()
        self.setCheckable(True)
        self.setProperty("fx", True)
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(0)
        g = gloss(name)
        for text, small in ((name, False), (g, True)):
            if not text and small:
                continue
            lb = QLabel(text)
            lb.setAlignment(Qt.AlignCenter)
            lb.setWordWrap(True)
            lb.setAttribute(Qt.WA_TransparentForMouseEvents)
            if small:
                lb.setStyleSheet("color: #8b92a3; font-size: 10.5px;")
            lay.addWidget(lb)
        self.setMinimumHeight(46)


class Zone:
    """key = 상태의 키("light"/"sidelight"), send = 서비스 메서드 이름."""

    def __init__(self, page, key, effects, send, on_change=None):
        self.page, self.key, self.effects, self.send_name, self.on_change = page, key, effects, send, on_change
        self.L, self.busy, self.again = None, False, False
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.send)
        self.state_lbl = None

    def state(self, text, kind=""):
        if alive(self.state_lbl):
            self.state_lbl.set(text, kind)

    def build(self):
        if not self.timer.isActive() and not self.busy:
            cur = self.page.s[self.key]
            self.L = {**cur, "rgb": list(cur["rgb"])}
        L = self.L
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(h3(t("light.effect")))
        grid, self.fx = QGridLayout(), {}
        grid.setSpacing(6)
        for n, (k, name) in enumerate(self.effects.items()):
            b = FxButton(name)
            b.setChecked(k == L["effect"])
            b.clicked.connect(lambda _=False, k=k: self._set("effect", k))
            self.fx[k] = b
            grid.addWidget(b, n // 3, n % 3)
        lay.addLayout(grid)
        lay.addWidget(h3(t("light.color")))
        self.color_btn = QPushButton()
        self.color_btn.setProperty("colorbtn", True)
        self.color_btn.setFixedSize(44, 32)
        self.color_btn.setCursor(Qt.PointingHandCursor)
        self.color_btn.clicked.connect(self._pick_color)
        sw = QWidget()
        swl = QGridLayout(sw)
        swl.setContentsMargins(0, 0, 0, 0)
        swl.setSpacing(7)
        self.swatches = []
        for i, c in enumerate(P.PRESET_COLORS):
            b = QPushButton()
            b.setCheckable(True)
            b.setProperty("swatch", True)
            b.setFixedSize(26, 26)
            b.setToolTip(hexc(c))
            b.setStyleSheet("QPushButton { background: %s; }" % hexc(c))
            b.clicked.connect(lambda _=False, c=c: self._preset(c))
            self.swatches.append((c, b))
            swl.addWidget(b, 0, i)
        lay.addWidget(row(self.color_btn, sw, stretch=True))
        self.dazzle = Switch(L["dazzle"])
        self.dazzle.clicked.connect(lambda: self._set("dazzle", self.dazzle.isChecked()))
        lay.addWidget(row(QLabel(t("light.rainbow")), self.dazzle, stretch=True))
        lay.addWidget(h3(t("light.bright_speed")))
        self.bright = RangeRow(t("light.bright"), 0, P.BRIGHT_MAX, 1, L["bright"])
        self.speed = RangeRow(t("light.speed"), 0, P.MAXSPEED, 1, L["speed"])
        self.bright.changed.connect(lambda v: self._set("bright", int(v)))
        self.speed.changed.connect(lambda v: self._set("speed", int(v)))
        lay.addWidget(self.bright)
        lay.addWidget(self.speed)
        lay.addWidget(h3(t("light.option")))
        self.option = Seg([(o, str(o)) for o in sorted({0, 1, 2, 3, L["option"]})], L["option"])
        self.option.changed.connect(lambda v: self._set("option", v))
        lay.addWidget(row(self.option, stretch=True))
        self.state_lbl = StateLabel()
        lay.addWidget(self.state_lbl)
        self.sync()
        return box

    # ---------- 값 바꾸기 ----------
    def _set(self, name, value):
        self.L[name] = value
        self.sync()
        self.change()

    def _preset(self, c):
        self.L["rgb"], self.L["dazzle"] = list(c), False
        self.sync()
        self.change()

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(*self.L["rgb"]), self.page.win, t("light.color"),
                                  QColorDialog.DontUseNativeDialog)
        if c.isValid():
            self._preset(c.getRgb()[:3])

    def sync(self):
        L = self.L
        for k, b in self.fx.items():
            b.setChecked(k == L["effect"])
        for c, b in self.swatches:
            b.setChecked(hexc(c) == hexc(L["rgb"]) and not L["dazzle"])
        self.dazzle.set_silent(L["dazzle"])
        self.option.set_current(L["option"])
        self.color_btn.setStyleSheet("QPushButton { background: %s; }" % hexc(L["rgb"]))

    def change(self):
        self.timer.stop()
        self.state(t("light.changed"))
        if self.on_change:
            self.on_change(self.L)
        self.timer.start(300)

    def send(self):
        if self.busy:
            self.again = True
            return
        self.busy = True
        self.state(t("light.applying"))
        want, svc, key = {**self.L, "rgb": list(self.L["rgb"])}, self.page.win.svc, self.key

        def done(j, err):
            self.busy = False
            if self.again:
                self.again = False
                self.send()
                return
            ok = self.page.win.report(j, err, t("toast.light_applied"))
            if err is not None:
                self.state(describe_error(err), "bad")
                return
            if self.page.s is not None:
                self.page.s[key] = j[key]
            got = j[key] or {}
            self.state(t("state.match0") if ok else t("light.mismatch_detail", effect=got.get("effect"),
                                                      bright=got.get("bright")), "ok" if ok else "bad")
        self.page.win.run(lambda: getattr(svc, self.send_name)(**want), done)


class LightPage(Page):
    name, label_key, icon, stage, legend_key = "light", "nav.light", "light", True, "light.legend"

    def __init__(self, win):
        super().__init__(win)
        self.main = Zone(self, "light", P.EFFECTS, "light", self.glow)
        self.side = Zone(self, "sidelight", P.SIDE_EFFECTS, "sidelight")

    def glow(self, L):
        color = QColor(0, 0, 0, 0) if L["effect"] == 0 else QColor("#fff" if L["dazzle"] else hexc(L["rgb"]))
        self.win.kb.set_glow(color, 0.55 + L["bright"] * 0.1125)

    def build(self):
        self.lay.addWidget(h2(t("light.title")))
        self.lay.addWidget(sub(t("light.sub")))
        self.lay.addWidget(self.main.build())
        self.lay.addWidget(hr())
        self.lay.addWidget(h2(t("light.side_title")))
        self.lay.addWidget(self.side.build() if self.s["sidelight"] else sub(t("light.side_fail")))
        self.glow(self.main.L)
