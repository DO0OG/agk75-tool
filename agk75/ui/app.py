"""화면 진입점: QApplication 을 만들고 메인 창을 띄운다. 창을 닫으면 프로세스가 끝난다."""
import sys
import traceback
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .. import i18n
from ..service import Service
from . import theme
from .main_window import MainWindow


def make_app():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(theme.qss(i18n.lang()))
    ico = Path(__file__).resolve().parents[2] / "icon.ico"  # 소스 실행과 설치본 모두 agk75 폴더의 바깥에 둔다
    if ico.is_file():
        app.setWindowIcon(QIcon(str(ico)))
    return app


def run():
    app = make_app()
    win = MainWindow(Service())

    def hook(kind, exc, tb):  # 창 모드 exe 는 콘솔이 없으니 예외도 토스트로 보인다
        traceback.print_exception(kind, exc, tb)
        win.toast("%s: %s" % (kind.__name__, exc), "bad", 5000)
    sys.excepthook = hook
    win.show()
    return app.exec()
