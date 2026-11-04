"""화면(메뉴 한 칸) 공통 뼈대. render() 가 내용을 처음부터 다시 만든다(언어 전환 때도 쓴다)."""
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .. import i18n
from .. import protocol as P
from .layout import FN_KEY
from .widgets import clear_layout

SHORT = {"CapsLock": "Caps", "Backspace": "Bksp", "PageUp": "PgUp", "PageDown": "PgDn", "ScrollLock": "ScrLk",
         "Delete": "Del", "Insert": "Ins", "LShift": "Shift", "RShift": "Shift", "LCtrl": "Ctrl", "RCtrl": "Ctrl",
         "LAlt": "Alt", "RAlt": "Alt", "LWin": "Win", "RWin": "Win", "PrtSc": "PrtSc", "Right": "→", "Left": "←",
         "Up": "↑", "Down": "↓"}


def item_name(it):
    """4바이트 항목 -> 이름("없음" / "특수" 포함)."""
    h = P.hid_of(it)
    if h is not None:
        return P.HID_NAMES.get(h, "HID%d" % h)
    return i18n.t("key.special_short") if any(it) else i18n.t("key.none")


def short(name):
    return SHORT.get(name, name)


class Page(QWidget):
    name = label_key = icon = ""
    stage = True  # 키보드 그림을 같이 보여 주는 화면인가
    multi = False  # 키를 여러 개 고를 수 있는가
    legend_key = None

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(6)

    @property
    def s(self):
        return self.win.s

    def render(self):
        clear_layout(self.lay)
        self.build()
        self.lay.addStretch(1)

    def build(self):
        raise NotImplementedError

    def leave(self):
        """다른 화면으로 가기 전에 타이머 같은 것을 정리한다."""

    # ---- 키보드 그림 ----
    def key_text(self, i):
        if i == FN_KEY:
            return "Fn"
        return short(item_name(self.s["keymap"][self.s["profile"]][i]))

    def key_sub(self, i):
        return None

    def key_fill(self, i):
        return None

    def key_dim(self, i):
        return False

    def on_key(self, idx):
        """True 를 돌려주면 선택을 바꾸지 않는다."""
        return False

    def selection_changed(self):
        pass
