"""키보드 그림: 다중 선택(Shift·Ctrl 클릭, 끌기), 값 열지도, 조명 색 미리보기."""
from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from . import theme
from .layout import LAYOUT, LAYOUT_H, LAYOUT_W

MIN_U, MAX_U = 30, 58


class KeyboardWidget(QWidget):
    keyPressed = Signal(int, bool)  # (키 번호, Shift·Ctrl 이 눌렸는가)
    keyDragged = Signal(int)

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cells, self.tips, self.selected, self.hover = {}, {}, set(), None
        self.glow, self.opacity, self.dragging = None, 1.0, False
        self.u = MAX_U
        self._fit(self.width() or 800)

    def _fit(self, width):
        self.u = max(MIN_U, min(MAX_U, int(width // LAYOUT_W)))
        self.setFixedHeight(int(LAYOUT_H * self.u) + 6)

    def resizeEvent(self, e):
        self._fit(e.size().width())
        super().resizeEvent(e)

    def sizeHint(self):
        return self.minimumSizeHint()

    def minimumSizeHint(self):
        return QSize(int(LAYOUT_W * MIN_U), int(LAYOUT_H * MIN_U) + 6)

    # ---- 데이터 ----
    def set_cells(self, cells):
        """cells = {키 번호: (글자, 작은 글자 또는 None, QColor 또는 None, 흐리게 여부)}"""
        self.cells = cells
        self.update()

    def set_tips(self, tips):
        """{키 번호: 마우스를 올렸을 때 보일 전체 이름 또는 None}"""
        self.tips = tips

    def event(self, e):
        if e.type() == QEvent.ToolTip:
            tip = self.tips.get(self.key_at(e.pos()))
            if tip:
                QToolTip.showText(e.globalPos(), tip, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)

    def set_selected(self, sel):
        self.selected = set(sel)
        self.update()

    def set_glow(self, color, opacity=1.0):
        self.glow, self.opacity = color, opacity
        self.update()

    # ---- 위치 ----
    def _origin(self):
        return (self.width() - LAYOUT_W * self.u) / 2

    def _rect(self, x, y, w):
        u = self.u
        return QRectF(self._origin() + x * u, y * u + 2, w * u - 4, u - 4)

    def key_at(self, pos):
        for idx, x, y, w in LAYOUT:
            if self._rect(x, y, w).contains(QPointF(pos)):
                return idx
        return None

    def _dim(self, idx):
        return bool(self.cells.get(idx, (None, None, None, False))[3])

    # ---- 마우스 ----
    def mousePressEvent(self, e):
        idx = self.key_at(e.position())
        if e.button() != Qt.LeftButton or idx is None or self._dim(idx):
            return
        self.dragging = True
        self.keyPressed.emit(idx, bool(e.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier)))

    def mouseMoveEvent(self, e):
        idx = self.key_at(e.position())
        if idx != self.hover:
            self.hover = idx
            self.update()
        if self.dragging and idx is not None and not self._dim(idx) and idx not in self.selected:
            self.keyDragged.emit(idx)

    def mouseReleaseEvent(self, _):
        self.dragging = False

    def leaveEvent(self, _):
        self.hover = None
        self.update()

    # ---- 그리기 ----
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        main = QFont(self.font())
        main.setPixelSize(11)
        small = QFont(self.font())
        small.setPixelSize(9)
        for idx, x, y, w in LAYOUT:
            text, subtext, fill, dim = self.cells.get(idx, ("", None, None, False))
            r = self._rect(x, y, w)
            sel, hov = idx in self.selected, idx == self.hover and not dim
            p.setOpacity(self.opacity * (0.45 if dim else 1.0))
            path = QPainterPath()
            path.addRoundedRect(r, 7, 7)
            p.fillPath(path, fill or QColor("#2e3340" if hov else "#262a34"))
            if self.glow is not None:
                p.save()
                p.setClipPath(path)
                p.fillRect(QRectF(r.left(), r.bottom() - 3, r.width(), 3), self.glow)
                p.restore()
            if sel:
                p.setPen(QPen(QColor(theme.ACCENT), 2))
                p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 6, 6)
            else:
                p.setPen(QPen(QColor(theme.ACCENT2 if hov else "#343a47"), 1))
                p.drawRoundedRect(r.adjusted(.5, .5, -.5, -.5), 7, 7)
            p.setPen(QColor(theme.TEXT))
            self._text(p, r, text, subtext, main, small)
        p.end()

    @staticmethod
    def _text(p, r, text, subtext, main, small):
        inner = r.adjusted(2, 0, -2, 0)
        w = int(inner.width())
        p.setFont(main)
        if subtext is None:
            if QFontMetrics(main).horizontalAdvance(text) <= w:
                p.drawText(inner, Qt.AlignCenter, text)
            else:  # 안 들어가면 작은 글자로 줄바꿈(공백·한글 단위), 그래도 넘치면 끝을 줄인다
                text = text.replace("+", "+​")  # 조합 키는 + 뒤에서 줄을 바꾼다
                p.setFont(small)
                fm = QFontMetrics(small)
                rect = fm.boundingRect(QRectF(0, 0, w, inner.height()).toRect(), Qt.AlignCenter | Qt.TextWordWrap, text)
                if rect.height() > inner.height():
                    text = fm.elidedText(text, Qt.ElideRight, w)
                p.drawText(inner, Qt.AlignCenter | Qt.TextWordWrap, text)
            return
        shown = QFontMetrics(main).elidedText(text, Qt.ElideRight, w)
        p.drawText(QRectF(inner.left(), inner.top(), inner.width(), inner.height() / 2 + 6),
                   Qt.AlignHCenter | Qt.AlignBottom, shown)
        p.setFont(small)
        p.setOpacity(p.opacity() * 0.8)
        p.drawText(QRectF(inner.left(), inner.center().y() + 6, inner.width(), inner.height() / 2 - 6),
                   Qt.AlignHCenter | Qt.AlignTop, subtext)
