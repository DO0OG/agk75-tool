"""어두운 테마(QSS)와 색 상수. 강조색 #ff5a1f."""
BG, CARD, CARD2, LINE = "#121418", "#1b1e25", "#232731", "#2a2e38"
TEXT, MUTED = "#e6e8ee", "#8b92a3"
ACCENT, ACCENT2, OK, BAD = "#ff5a1f", "#ff7b4a", "#3ecf8e", "#ff4d4f"
BAR = "#15181e"
# 언어마다 글자꼴을 먼저 정해 한글·한자가 엉뚱한 글꼴로 섞이지 않게 한다
FONTS = {"ko": '"Malgun Gothic", "Segoe UI", sans-serif', "en": '"Segoe UI", "Malgun Gothic", sans-serif',
         "zh": '"Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif'}

_TEMPLATE = """
* { font-family: %(font)s; font-size: 13px; color: %(text)s; }
QMainWindow, #root { background: %(bg)s; }
QToolTip { background: %(card2)s; border: 1px solid %(line)s; padding: 4px; }
#top { background: %(bar)s; border-bottom: 1px solid %(line)s; }
#brand { font-size: 18px; font-weight: 600; letter-spacing: 1px; }
#muted, QLabel[muted="true"] { color: %(muted)s; }
#side { background: %(bar)s; border-right: 1px solid %(line)s; }
QToolButton[nav="true"] { border: 0; border-left: 3px solid transparent; border-radius: 12px; background: transparent;
  color: %(muted)s; font-size: 11px; padding: 8px 0; }
QToolButton[nav="true"]:hover { background: %(card)s; color: %(text)s; }
QToolButton[nav="true"]:checked { background: %(card2)s; color: %(accent)s; border-left: 3px solid %(accent)s; }
#card, QFrame[card="true"] { background: %(card)s; border: 1px solid %(line)s; border-radius: 16px; }
QFrame[inner="true"] { background: %(card2)s; border: 1px solid %(line)s; border-radius: 16px; }
QFrame[inner="true"] QLabel { background: transparent; }
#card QLabel, #card QCheckBox { background: transparent; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: 0; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #343a47; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QLabel[h2="true"] { font-size: 16px; font-weight: 600; }
QLabel[h3="true"] { font-size: 12px; font-weight: 600; color: %(muted)s; }
QLabel[sub="true"] { color: %(muted)s; }
QLabel[state="true"] { font-size: 12px; color: %(muted)s; }
QLabel[state="true"][kind="bad"] { color: %(bad)s; }
QLabel[state="true"][kind="ok"] { color: %(ok)s; }
QFrame[hr="true"] { background: %(line)s; max-height: 1px; border: 0; }
QPushButton { border: 1px solid %(line)s; background: %(card2)s; padding: 7px 14px; border-radius: 10px; }
QPushButton:hover:enabled { border-color: %(accent2)s; }
QPushButton:disabled { color: #5a6070; background: #1f222a; }
QPushButton[primary="true"] { background: %(accent)s; border-color: %(accent)s; color: #fff; }
QPushButton[primary="true"]:disabled { background: #4a2a1e; border-color: #4a2a1e; color: #8a7a72; }
QFrame[seg="true"] { background: %(bg)s; border: 1px solid %(line)s; border-radius: 10px; }
QFrame[seg="true"] QPushButton { border: 0; background: transparent; padding: 5px 11px; border-radius: 7px; color: %(muted)s; }
QFrame[seg="true"] QPushButton:hover:enabled:!checked { color: %(text)s; }
QFrame[seg="true"] QPushButton:checked { background: %(accent)s; color: #fff; }
QFrame[seg="true"] QPushButton:disabled { color: #4a5060; }
QPushButton[fx="true"] { padding: 6px 2px; border-radius: 10px; }
QPushButton[fx="true"]:checked { border: 1px solid %(accent)s; }
QPushButton[fx="true"] QLabel { background: transparent; }
QPushButton[swatch="true"] { padding: 0; border: 2px solid transparent; border-radius: 13px; }
QPushButton[swatch="true"]:checked { border: 2px solid #fff; }
QPushButton[colorbtn="true"] { padding: 0; border: 1px solid %(line)s; border-radius: 8px; }
QLabel[keycap="true"] { min-width: 64px; min-height: 52px; padding: 0 14px; border-radius: 10px; border: 1px solid #3a4150;
  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #303541,stop:1 #262a34); font-size: 16px; font-weight: 600; }
QLineEdit { background: %(bg)s; border: 1px solid %(line)s; border-radius: 8px; padding: 6px 9px; }
QListWidget { background: transparent; border: 1px solid %(line)s; border-radius: 10px; outline: 0; }
QListWidget::item { padding: 6px 12px; border-bottom: 1px solid %(line)s; }
QListWidget::item:hover { background: %(card2)s; }
QListWidget::item:selected { background: %(card2)s; color: %(text)s; border-left: 3px solid %(accent)s; }
QSlider::groove:horizontal { height: 4px; background: #3a3f4c; border-radius: 2px; }
QSlider::sub-page:horizontal { background: %(accent)s; border-radius: 2px; }
QSlider::handle:horizontal { background: %(accent)s; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }
QSlider::handle:horizontal:disabled { background: #6a5048; }
QProgressBar { background: %(bg)s; border: 0; border-radius: 4px; max-height: 8px; min-height: 8px; }
QProgressBar::chunk { background: %(accent)s; border-radius: 4px; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid %(line)s; border-radius: 4px; background: %(bg)s; }
QCheckBox::indicator:checked { background: %(accent)s; border-color: %(accent)s; }
#banner { background: %(bad)s; color: #fff; padding: 8px 20px; }
#banner { color: #fff; }
QLabel[toast="true"] { padding: 9px 18px; border-radius: 10px; background: #2a2f3a; border: 1px solid %(line)s; }
QLabel[toast="true"][kind="ok"] { border: 1px solid %(ok)s; }
QLabel[toast="true"][kind="bad"] { background: #4a1d20; border: 1px solid %(bad)s; }
QMessageBox, QColorDialog { background: %(card)s; }
"""


def qss(lang="ko"):
    return _TEMPLATE % dict(font=FONTS.get(lang, FONTS["en"]), text=TEXT, bg=BG, card=CARD, card2=CARD2, line=LINE,
                            muted=MUTED, accent=ACCENT, accent2=ACCENT2, ok=OK, bad=BAD, bar=BAR)


ICONS = {
    "keys": '<rect x="2" y="6" width="20" height="12" rx="3"/><path d="M6 10h2M11 10h2M16 10h2M7 14h10"/>',
    "light": '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"/>',
    "magnet": '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    "misc": '<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>',
    "backup": '<path d="M5 3h11l3 3v15H5zM8 3v5h7V3M8 21v-7h8v7"/>',
}


def icon_svg(name, color):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="%s" stroke-width="1.7" '
            'stroke-linecap="round" stroke-linejoin="round">%s</svg>' % (color, ICONS[name])).encode()
