"""키 설정 화면의 폴링레이트 카드. 키보드 레지스터에 쓰고 되읽으며, 실행은 전부 작업 스레드에서 한다."""
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from ..i18n import t
from .widgets import Seg, StateLabel, alive, card, clear_layout

RATES = [8000, 4000, 2000, 1000, 500, 250]


class RateCard:
    """카드 모델 + 화면. 현재 값은 win.s["rate"](현재 프로필)에서 읽는다."""

    def __init__(self, win):
        self.win = win
        self.busy = False
        self.frame = None

    def build(self):
        """카드 위젯을 새로 만들어 돌려준다."""
        self.frame = card()
        QVBoxLayout(self.frame).setContentsMargins(14, 14, 14, 14)
        self.refresh()
        return self.frame

    def refresh(self):
        if not alive(self.frame):
            return
        lay = self.frame.layout()
        clear_layout(lay)
        s = self.win.s or {}
        cur, n = s.get("rate"), (s.get("profile") or 0) + 1
        head = QHBoxLayout()
        head.addWidget(QLabel("<b>%s</b>" % t("rate.title")))
        state = QLabel(t("rate.cur", n=n, hz=cur) if cur else t("rate.unreadable", n=n))
        state.setProperty("sub", True)
        head.addWidget(state, 1)
        lay.addLayout(head)
        seg = Seg([(r, str(r)) for r in RATES], cur)
        seg.set_enabled_all(not self.busy and bool(s))
        seg.setStyleSheet('QFrame[seg="true"] QPushButton { padding: 5px 6px; }')  # 버튼 6개가 패널 폭에 들어가게
        seg.changed.connect(self.apply)
        line = QHBoxLayout()
        line.addWidget(seg)
        line.addStretch(1)
        lay.addLayout(line)
        for key in ("rate.fast", "rate.wired", "rate.note"):
            st = StateLabel()
            st.set(t(key))
            lay.addWidget(st)

    def apply(self, hz):
        if self.busy:
            return
        self.busy = True
        self.refresh()

        def done(j, err):
            self.busy = False
            if err is not None:
                self.win.fail(err)
            else:
                if self.win.s is not None:
                    self.win.s["rate"] = j["rate"]
                if j["applied"]:
                    self.win.toast(t("rate.ok", hz=hz))
                else:
                    self.win.toast(t("rate.mismatch", want=hz, got=j["rate"] or "-"), "bad", 5000)
            self.refresh()
        self.win.run(lambda: self.win.svc.rate(hz=hz), done)
