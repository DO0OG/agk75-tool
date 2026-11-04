"""
Nuitka EXE 빌드 스크립트
실행: python build_exe.py           # 증분 빌드
실행: python build_exe.py --clean   # dist 삭제 후 클린 빌드
출력: dist/AGK75Tool.dist/AGK75Tool.exe
필요: pip install PySide6-Essentials (QtCore·QtGui·QtWidgets·QtSvg 만 쓴다)
"""
import importlib.util
import multiprocessing
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
os.environ["PYTHONUTF8"] = "1"
VERSION = "1.0.0"

if importlib.util.find_spec("nuitka") is None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "nuitka", "ordered-set", "zstandard"])

if "--clean" in sys.argv and os.path.isdir("dist"):
    shutil.rmtree("dist")

# 쓰지 않는 Qt 모듈은 따라가지 않아 크기를 줄인다(화면은 QtCore·QtGui·QtWidgets·QtSvg 만 쓴다)
UNUSED_QT = ["Qt3D*", "QtBluetooth", "QtCharts", "QtConcurrent", "QtDataVisualization", "QtDesigner", "QtHelp",
             "QtLocation", "QtMultimedia*", "QtNetwork*", "QtNfc", "QtOpenGL*", "QtPdf*", "QtPositioning",
             "QtPrintSupport", "QtQml", "QtQuick*", "QtRemoteObjects", "QtScxml", "QtSensors", "QtSerialPort",
             "QtSql", "QtStateMachine", "QtTest", "QtTextToSpeech", "QtUiTools", "QtWebChannel", "QtWebEngine*",
             "QtWebSockets", "QtWebView", "QtXml"]

args = [
    sys.executable, "-m", "nuitka",
    "--standalone",
    f"--jobs={multiprocessing.cpu_count()}",
    "--windows-console-mode=disable",
    "--windows-icon-from-ico=icon.ico",
    "--enable-plugin=pyside6",
    "--include-qt-plugins=platforms,styles,imageformats",  # 창(windows)·시험용(offscreen) 플랫폼, 기본 스타일, 아이콘(ico) 읽기
    "--include-data-files=icon.ico=icon.ico",  # 창 아이콘
    "--noinclude-dlls=opengl32sw.dll",  # 소프트웨어 OpenGL(약 20MB). 위젯 화면은 쓰지 않는다
    "--noinclude-dlls=d3dcompiler_47.dll",
    *[f"--nofollow-import-to=PySide6.{m}" for m in UNUSED_QT],
    "--include-package=agk75",
    "--include-module=hid",  # hidapi 는 단일 확장 모듈(hid.pyd)이다
    "--output-dir=dist",
    "--output-filename=AGK75Tool.exe",
    "--company-name=DO0OG",
    "--product-name=AGK75 Tool",
    f"--file-version={VERSION}.0",
    f"--product-version={VERSION}.0",
    "--file-description=AGK75 keyboard settings",
    "--assume-yes-for-downloads",
    "--remove-output",
    "agk75_app.py",
]
code = subprocess.call(args)
if code:
    sys.exit(code)
if os.path.isdir("dist/agk75_app.dist"):  # Nuitka 는 진입 스크립트 이름으로 폴더를 만든다
    shutil.rmtree("dist/AGK75Tool.dist", ignore_errors=True)
    os.rename("dist/agk75_app.dist", "dist/AGK75Tool.dist")
out = os.path.join("dist", "AGK75Tool.dist", "AGK75Tool.exe")
if not os.path.isfile(out):
    sys.exit("빌드 결과가 없습니다: " + out)
print("출력:", out)
