"""여러 화면이 같이 쓰는 작은 부품."""
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QWidget
from shiboken6 import isValid

from . import theme


def alive(w):
    return w is not None and isValid(w)


def clear_layout(lay):
    while lay.count():
        item = lay.takeAt(0)
        w = item.widget()
        if w:
            w.setParent(None)
            w.deleteLater()
        elif item.layout():
            clear_layout(item.layout())


def label(text="", role=None, wrap=True):
    lb = QLabel(text)
    lb.setWordWrap(wrap)
    if role:
        lb.setProperty(role, True)
    return lb


def h2(text):
    return label(text, "h2")


def h3(text):
    lb = label(text, "h3")
    lb.setContentsMargins(0, 10, 0, 0)
    return lb


def sub(text):
    return label(text, "sub")


def hr():
    f = QFrame()
    f.setProperty("hr", True)
    f.setFixedHeight(1)
    return f


def button(text, primary=False, enabled=True):
    b = QPushButton(text)
    b.setProperty("primary", primary)
    b.setEnabled(enabled)
    b.setCursor(Qt.PointingHandCursor)
    return b


def row(*items, stretch=False):
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 4, 0, 4)
    lay.setSpacing(10)
    for it in items:
        lay.addWidget(it)
    if stretch:
        lay.addStretch(1)
    return box


def card(inner=True):
    f = QFrame()
    f.setProperty("inner" if inner else "card", True)
    return f


def repolish(w):
    w.style().unpolish(w)
    w.style().polish(w)


class StateLabel(QLabel):
    """작은 상태 줄. kind = "", "ok", "bad"."""

    def __init__(self, text=""):
        super().__init__(text)
        self.setWordWrap(True)
        self.setProperty("state", True)
        self.setProperty("kind", "")
        self.setMinimumHeight(18)

    def set(self, text, kind=""):
        self.setText(text)
        self.setProperty("kind", kind)
        repolish(self)


class Seg(QFrame):
    """버튼 묶음 중 하나를 고르는 분할 선택기. 사용자가 누를 때만 changed 가 나간다."""
    changed = Signal(object)

    def __init__(self, items, current=None):
        super().__init__()
        self.setProperty("seg", True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.group, self.buttons = QButtonGroup(self), {}
        self.group.setExclusive(True)
        for value, text in items:
            b = QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(value == current)
            self.group.addButton(b)
            self.buttons[value] = b
            lay.addWidget(b)
            b.clicked.connect(lambda _=False, v=value: self.changed.emit(v))

    def set_current(self, value):
        b = self.buttons.get(value)
        if b is not None:
            b.setChecked(True)

    def set_enabled_all(self, on):
        for b in self.buttons.values():
            b.setEnabled(on)


class Switch(QAbstractButton):
    """켬/끔 스위치. 사용자가 누르면 clicked 가 나간다."""

    def __init__(self, on=False):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(on)
        self.setFixedSize(40, 22)
        self.setCursor(Qt.PointingHandCursor)

    def set_silent(self, on):
        self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(False)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.ACCENT if self.isChecked() else "#3a3f4c"))
        p.drawRoundedRect(QRectF(0, 0, 40, 22), 11, 11)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(21 if self.isChecked() else 3, 3, 16, 16))


class RangeRow(QWidget):
    """이름 + 슬라이더 + 값 표시. 사용자가 움직일 때만 changed 가 나간다(set_value 는 신호를 막는다)."""
    changed = Signal(float)

    def __init__(self, name, lo, hi, step, value, unit=""):
        super().__init__()
        self.step, self.unit, self.scale = step, unit, round(1 / step)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(10)
        self.name = QLabel(name)
        self.name.setProperty("muted", True)
        self.name.setMinimumWidth(92)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(round(lo * self.scale), round(hi * self.scale))
        self.out = QLabel()
        self.out.setFixedWidth(60)
        self.out.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.name)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.out)
        self.set_value(value)
        self.slider.valueChanged.connect(self._moved)

    def _show(self):
        v = self.slider.value() / self.scale
        self.out.setText(("%.1f" if self.step < 1 else "%d") % v + self.unit)

    def _moved(self, raw):
        self._show()
        self.changed.emit(raw / self.scale)

    def value(self):
        return self.slider.value() / self.scale

    def set_value(self, v):
        self.slider.blockSignals(True)
        self.slider.setValue(round(v * self.scale))
        self.slider.blockSignals(False)
        self._show()
