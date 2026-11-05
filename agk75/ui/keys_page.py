"""키 설정: 키보드 그림에서 키를 고르고, 바꿀 키를 그림/목록/실제 키 입력으로 지정한다."""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from .. import protocol as P
from ..i18n import t
from ..service import describe_error
from .layout import FN_KEY
from .page import Page, item_name, item_short
from .rate_card import RateCard
from .widgets import Seg, StateLabel, alive, button, clear_layout, h2, h3, hr, row, sub

# 장치 스캔 코드(Set 1, 확장 키는 0x100 을 더함) -> HID 사용 코드. 자판 배열과 무관한 물리 키 위치다.
SCAN_HID = {0x01: 41, 0x0C: 45, 0x0D: 46, 0x0E: 42, 0x0F: 43, 0x1A: 47, 0x1B: 48, 0x1C: 40, 0x1D: 224, 0x27: 51,
            0x28: 52, 0x29: 53, 0x2A: 225, 0x2B: 49, 0x33: 54, 0x34: 55, 0x35: 56, 0x36: 229, 0x38: 226, 0x39: 44,
            0x3A: 57, 0x46: 71, 0x56: 100, 0x57: 68, 0x58: 69, 0x11D: 228, 0x137: 70, 0x138: 230, 0x147: 74,
            0x148: 82, 0x149: 75, 0x14B: 80, 0x14D: 79, 0x14F: 77, 0x150: 81, 0x151: 78, 0x152: 73, 0x153: 76,
            0x15B: 227, 0x15C: 231, 0x15D: 101}
SCAN_HID.update({0x02 + i: 30 + i for i in range(10)})  # 1..0
SCAN_HID.update({0x3B + i: 58 + i for i in range(10)})  # F1..F10
for _start, _letters in ((0x10, "QWERTYUIOP"), (0x1E, "ASDFGHJKL"), (0x2C, "ZXCVBNM")):
    SCAN_HID.update({_start + i: ord(c) - 65 + 4 for i, c in enumerate(_letters)})


def hid_from_scan(scan, key=0):
    """실제 키 입력의 스캔 코드(없으면 Qt 키 값)를 HID 사용 코드로 바꾼다. 모르는 키는 None."""
    if scan in SCAN_HID:
        return SCAN_HID[scan]
    if key == Qt.Key_Pause:
        return 72
    if Qt.Key_A <= key <= Qt.Key_Z:
        return key - Qt.Key_A + 4
    if Qt.Key_1 <= key <= Qt.Key_9:
        return key - Qt.Key_1 + 30
    return {Qt.Key_0: 39}.get(key)


class KeysPage(Page):
    name, label_key, icon, stage = "keys", "nav.keys", "keys", True

    def __init__(self, win):
        super().__init__(win)
        self.layer, self.fn, self.mode, self.armed, self.listening, self.filter = None, False, "board", False, False, ""
        self.rate = RateCard(win)
        self.kedit = self.kstate = self.klist = self.mode_box = None

    # ---------- 키보드 그림 ----------
    def cur(self):
        return (self.s["fn"] if self.fn else self.s["keymap"])[self.layer]

    def target(self):
        return min(self.win.sel) if self.win.sel else None

    def key_text(self, i):
        if i == FN_KEY:
            return "Fn"
        it = self.cur()[i]
        return "" if self.fn and not any(it) else item_short(it)

    def key_tip(self, i):
        return None if i == FN_KEY or (self.fn and not any(self.cur()[i])) else item_name(self.cur()[i])

    def key_dim(self, i):
        return i == FN_KEY

    def on_key(self, idx):
        if not self.armed:
            return False
        self.armed = False
        hid = P.DEFAULT_HID.get(idx)
        if hid:
            self.apply(hid)
        else:
            self.win.toast(t("keys.cannot"), "bad")
        self.editor()
        return True

    def selection_changed(self):
        self.editor()

    # ---------- 화면 ----------
    def build(self):
        if self.layer is None:
            self.layer = self.s["profile"] or 0
        self.stop_listen()
        self.armed = False
        lay = self.lay
        lay.addWidget(h2(t("keys.title")))
        lay.addWidget(sub(t("keys.sub")))
        lay.addWidget(self.rate.build())
        lay.addWidget(h3(t("keys.layer")))
        layer = Seg([(i, str(i + 1)) for i in range(4)], self.layer)
        layer.changed.connect(self._set_layer)
        kind = Seg([(False, t("keys.kind.n")), (True, t("keys.kind.f"))], self.fn)
        kind.changed.connect(self._set_kind)
        lay.addWidget(row(layer, stretch=True))
        lay.addWidget(row(kind, stretch=True))
        lay.addWidget(hr())
        self.kedit = QWidget()
        QVBoxLayout(self.kedit).setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.kedit)
        self.editor()

    def _set_layer(self, v):
        self.layer = v
        self.win.render()

    def _set_kind(self, v):
        self.fn = v
        self.win.render()

    def editor(self):
        if not alive(self.kedit) or self.s is None:
            return
        box = self.kedit.layout()
        clear_layout(box)
        idx = self.target()
        if idx is None:
            box.addWidget(sub(t("keys.none_selected")))
            self.kstate = None
            return
        it = self.cur()[idx]
        default = P.DEFAULT_HID.get(idx)
        name = item_name(it)
        box.addWidget(h3(t("keys.selected", idx=idx)))
        cap = QLabel(name)
        cap.setProperty("keycap", True)
        cap.setAlignment(Qt.AlignCenter)
        cap.setWordWrap(True)
        desc = (t("keys.kind.f") if self.fn else t("keys.std_pos", name=P.HID_NAMES.get(default, "-") if default else "-"))
        desc += "\n" + t("keys.value", hex=" ".join("%02x" % b for b in it))
        cap.setMinimumWidth(190)  # 긴 기능 이름도 한 줄~두 줄에 읽히게
        box.addWidget(row(cap, stretch=True))
        box.addWidget(sub(desc))
        box.addWidget(h3(t("keys.pick_title")))
        mode = Seg([("board", t("keys.mode.board")), ("list", t("keys.mode.list")), ("press", t("keys.mode.press"))],
                   self.mode)
        mode.changed.connect(self._set_mode)
        box.addWidget(row(mode, stretch=True))
        self.mode_box = QWidget()
        QVBoxLayout(self.mode_box).setContentsMargins(0, 6, 0, 0)
        box.addWidget(self.mode_box)
        factory = bool(self.s["factory"])
        default_btn, none_btn = button(t("keys.def"), enabled=factory), button(t("keys.setnone"))
        default_btn.clicked.connect(lambda: self.apply(0, True))
        none_btn.clicked.connect(lambda: self.apply(0))
        box.addWidget(row(default_btn, none_btn, stretch=True))
        if not factory:
            box.addWidget(sub(t("keys.nofactory")))
        self.kstate = StateLabel()
        box.addWidget(self.kstate)
        self.mode_html()

    def _set_mode(self, v):
        self.mode = v
        self.armed = False
        self.stop_listen()
        self.editor()

    def mode_html(self):
        lay = self.mode_box.layout()
        clear_layout(lay)
        if self.mode == "board":
            b = button(t("keys.arm_on" if self.armed else "keys.arm_off"), primary=self.armed)
            b.clicked.connect(self._toggle_arm)
            lay.addWidget(b)
        elif self.mode == "press":
            b = button(t("keys.listen_on" if self.listening else "keys.listen_off"), primary=self.listening)
            b.clicked.connect(self._toggle_listen)
            lay.addWidget(b)
        else:
            edit = QLineEdit(self.filter)
            edit.setPlaceholderText(t("keys.search_ph"))
            edit.textChanged.connect(self._set_filter)
            self.klist = QListWidget()
            self.klist.setMaximumHeight(190)
            self.klist.itemClicked.connect(lambda item: self.apply(item.data(Qt.UserRole)))
            lay.addWidget(edit)
            lay.addWidget(self.klist)
            self.list_html()

    def _set_filter(self, text):
        self.filter = text
        self.list_html()

    def list_html(self):
        self.klist.clear()
        for hid, name in sorted(P.HID_NAMES.items()):
            if self.filter.lower() in name.lower():
                item = QListWidgetItem(name)
                item.setData(Qt.UserRole, hid)
                self.klist.addItem(item)

    def _toggle_arm(self):
        self.armed = not self.armed
        self.mode_html()

    # ---------- 실제 키 누르기 ----------
    def _toggle_listen(self):
        if self.listening:
            self.stop_listen()
        else:
            self.listening = True
            QApplication.instance().installEventFilter(self)
        self.mode_html()

    def stop_listen(self):
        if self.listening:
            self.listening = False
            QApplication.instance().removeEventFilter(self)

    def leave(self):
        self.stop_listen()

    def eventFilter(self, obj, ev):
        if not self.listening or ev.type() not in (QEvent.KeyPress, QEvent.ShortcutOverride):
            return False
        if ev.type() == QEvent.KeyPress and not ev.isAutoRepeat():
            self.stop_listen()
            hid = hid_from_scan(ev.nativeScanCode(), ev.key())
            if alive(self.mode_box):
                self.mode_html()
            if hid:
                self.apply(hid)
            else:
                self.win.toast(t("keys.unsupported", code=ev.text() or "0x%x" % ev.key()), "bad")
        ev.accept()
        return True

    # ---------- 쓰기 ----------
    def state_line(self, text, kind=""):
        if alive(self.kstate):
            self.kstate.set(text, kind)

    def apply(self, hid, use_default=False):
        idx = self.target()
        if idx is None or self.s is None:
            return
        layer, fn, svc = self.layer, self.fn, self.win.svc
        kw = {"layer": layer, "idx": idx, **({"default": True} if use_default else {"hid": hid})}
        self.state_line(t("keys.applying"))

        def done(j, err):
            ok = self.win.report(j, err, t("toast.key_applied", idx=idx))
            if err is None and self.s is not None:
                (self.s["fn"] if fn else self.s["keymap"])[layer][idx] = list(j["item"])
                self.win.paint()
                self.editor()
            name = j["name"] if err is None else ""
            if err is not None:
                self.state_line(describe_error(err), "bad")
            else:
                self.state_line(t("state.match" if ok else "state.mismatch", name=name), "ok" if ok else "bad")
        self.win.run(lambda: (svc.fn if fn else svc.key)(**kw), done)
