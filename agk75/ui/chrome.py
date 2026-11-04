"""메인 창의 껍데기 부품: 상단 바, 왼쪽 내비, 키보드 아래 설명 줄, 장치 없음 화면."""
from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from .. import i18n
from ..i18n import t
from . import theme
from .page import Page
from .widgets import Seg, button, h2, label, sub

LANG_NAMES = [("ko", "한국어"), ("en", "English"), ("zh", "中文")]


class NoDevicePage(Page):
    stage = False

    def build(self):
        self.lay.addWidget(h2(t("nodev.title")))
        self.lay.addWidget(sub(t("nodev.body")))
        retry = button(t("nodev.retry"), primary=True)
        retry.clicked.connect(self.win.load)
        self.lay.addWidget(retry, 0, Qt.AlignLeft)


class Legend(QWidget):
    """키보드 아래 설명 줄. 래피드 트리거 화면에서는 얕음~깊음 색 띠가 붙는다."""

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(10)
        self.text, self.shallow, self.deep = QLabel(), QLabel(), QLabel()
        self.bar = QFrame()
        self.bar.setFixedSize(180, 8)
        self.bar.setStyleSheet("border-radius: 4px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                               "stop:0 hsl(215,80%,55%), stop:0.33 hsl(135,70%,50%), stop:0.66 hsl(40,90%,55%),"
                               "stop:1 hsl(5,85%,55%));")
        for w in (self.text, self.shallow, self.deep):
            w.setProperty("muted", True)
        for w in (self.text, self.shallow, self.bar, self.deep):
            lay.addWidget(w)
        self.setMinimumHeight(18)

    def set(self, key, bar=False):
        self.text.setText(t(key) if key else "")
        for w in (self.shallow, self.bar, self.deep):
            w.setVisible(bar)
        if bar:
            self.shallow.setText(t("mag.shallow"))
            self.deep.setText(t("mag.deep"))




def icon_pixmap(name, color, size=22):
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    QSvgRenderer(QByteArray(theme.icon_svg(name, color))).render(p)
    p.end()
    pm.setDevicePixelRatio(2)
    return pm


def top_bar(win):
    bar = QFrame()
    bar.setObjectName("top")
    bar.setFixedHeight(56)
    lay = QHBoxLayout(bar)
    lay.setContentsMargins(20, 0, 20, 0)
    lay.setSpacing(18)
    icon = QLabel()
    icon.setPixmap(icon_pixmap("keys", theme.ACCENT, 26))
    brand = QLabel("AGK75")
    brand.setObjectName("brand")
    win.dot, win.conn_text, win.rev = QLabel(), QLabel(), QLabel()
    win.dot.setFixedSize(9, 9)
    win.conn_text.setProperty("muted", True)
    win.rev.setProperty("muted", True)
    win.lang_seg = Seg(LANG_NAMES, i18n.lang())
    win.lang_seg.changed.connect(win.set_lang)
    win.profile_label = label("", "muted", wrap=False)
    win.profile_seg = Seg([(i, str(i + 1)) for i in range(4)], None)
    win.profile_seg.changed.connect(win._set_profile)
    for w in (icon, brand, win.dot, win.conn_text, win.rev):
        lay.addWidget(w, 0, Qt.AlignVCenter)
    lay.addStretch(1)
    for w in (win.lang_seg, win.profile_label, win.profile_seg):
        lay.addWidget(w, 0, Qt.AlignVCenter)
    return bar


def nav(win):
    side = QFrame()
    side.setObjectName("side")
    side.setFixedWidth(92)
    lay = QVBoxLayout(side)
    lay.setContentsMargins(8, 12, 8, 12)
    lay.setSpacing(6)
    win.nav = {}
    for name, page in win.pages.items():
        b = QToolButton()
        b.setProperty("nav", True)
        b.setCheckable(True)
        b.setAutoExclusive(True)
        b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        b.setIconSize(QSize(22, 22))
        ic = QIcon()
        ic.addPixmap(icon_pixmap(page.icon, theme.MUTED), QIcon.Normal, QIcon.Off)
        ic.addPixmap(icon_pixmap(page.icon, theme.ACCENT), QIcon.Normal, QIcon.On)
        b.setIcon(ic)
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(62)
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        b.clicked.connect(lambda _=False, n=name: win.show_view(n))
        lay.addWidget(b)
        win.nav[name] = b
    lay.addStretch(1)
    return side
