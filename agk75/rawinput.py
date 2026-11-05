"""폴링레이트 측정: Windows Raw Input 으로 이 키보드의 WM_INPUT 도착 시각만 모아 간격을 분석한다.

키 입력 내용(VKey, 스캔코드)은 읽지도 저장하지도 않는다. 측정 중에만 숨은 메시지 전용 창이 있다.
"""
import ctypes
import math
import threading
import time
from ctypes import wintypes

from .i18n import MsgError

PERIODS_MS = ((4, 250), (2, 500), (1, 1000))  # 큰 주기부터 본다(4ms 배수는 2ms·1ms 에서도 높게 나온다)
GAP_MIN_MS, GAP_MAX_MS = 1.5, 28.0  # 이 범위 밖: 한 리포트의 연속 이벤트·메시지 지연, 자동 반복(31ms 대)
R_MIN = 0.35
MIN_SAMPLES = 50
HIST_MS = 16
SAME_REPORT_MS = 0.05  # 이보다 짧은 간격은 한 리포트에 든 이벤트로 보고 히스토그램에서 뺀다
NEEDLE = "VID_3151&PID_5009"

WM_INPUT, HWND_MESSAGE = 0x00FF, -3
RID_HEADER, RIDI_DEVICENAME, RIM_TYPEKEYBOARD = 0x10000005, 0x20000007, 1
RIDEV_REMOVE, RIDEV_INPUTSINK = 0x1, 0x100
QS_ALLINPUT, PM_REMOVE = 0x04FF, 1


def _rayleigh(gaps, period):
    w = 2 * math.pi / period
    return math.hypot(sum(math.cos(w * g) for g in gaps), sum(math.sin(w * g) for g in gaps)) / len(gaps)


def analyze(intervals_ms):
    """이벤트 간격(ms) 목록 -> 간격이 4·2·1ms 주기에 몰리는 정도(Rayleigh R)로 250/500/1000Hz 를 판정한다.

    판정 근거는 주기성뿐이다. 1000Hz 보다 빠른 구간(2000~8000Hz)은 PC 쪽 측정으로 구분되지 않는다.
    """
    counts = [0] * HIST_MS
    for x in intervals_ms:
        if SAME_REPORT_MS <= x < HIST_MS:
            counts[int(x)] += 1
    gaps = [x for x in intervals_ms if GAP_MIN_MS <= x < GAP_MAX_MS]
    n = len(gaps)
    out = {"samples": n, "enough": n >= MIN_SAMPLES, "r": {}, "hz": None, "faster": False,
           "hist": [{"label": "%d~%d" % (i, i + 1), "count": c} for i, c in enumerate(counts)]}
    if out["enough"]:
        out["r"] = {p: _rayleigh(gaps, p) for p, _ in PERIODS_MS}
        out["hz"] = next((hz for p, hz in PERIODS_MS if out["r"][p] >= R_MIN), None)
        out["faster"] = out["hz"] is None
    return out


class _RawInputHeader(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                ("hDevice", wintypes.HANDLE), ("wParam", wintypes.WPARAM)]


class _RawInputDevice(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
                ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]


class _WndClass(ctypes.Structure):
    pass


_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_WndClass._fields_ = [("style", wintypes.UINT), ("lpfnWndProc", _WNDPROC), ("cbClsExtra", ctypes.c_int),
                      ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HANDLE),
                      ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HANDLE),
                      ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


def _user32():
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.DefWindowProcW.restype = ctypes.c_ssize_t
    u.RegisterClassW.argtypes = [ctypes.POINTER(_WndClass)]
    u.RegisterClassW.restype = wintypes.ATOM
    u.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                  wintypes.HANDLE, wintypes.HINSTANCE, wintypes.LPVOID]
    u.CreateWindowExW.restype = wintypes.HWND
    u.DestroyWindow.argtypes = [wintypes.HWND]
    u.RegisterRawInputDevices.argtypes = [ctypes.POINTER(_RawInputDevice), wintypes.UINT, wintypes.UINT]
    u.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPVOID,
                                  ctypes.POINTER(wintypes.UINT), wintypes.UINT]
    u.GetRawInputData.restype = wintypes.UINT
    u.GetRawInputDeviceInfoW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPVOID,
                                         ctypes.POINTER(wintypes.UINT)]
    u.GetRawInputDeviceInfoW.restype = wintypes.UINT
    u.MsgWaitForMultipleObjects.argtypes = [wintypes.DWORD, wintypes.LPVOID, wintypes.BOOL, wintypes.DWORD,
                                            wintypes.DWORD]
    u.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
                               wintypes.UINT]
    u.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    return u


class _Window:
    """숨은 메시지 전용 창. register=True 일 때만 키보드 Raw Input 을 받기 시작한다."""

    def __init__(self, on_event=None, register=True):
        self.u, self.on_event, self.names, self.registered = _user32(), on_event, {}, False
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        k.GetModuleHandleW.restype = wintypes.HINSTANCE
        self.hinst = k.GetModuleHandleW(None)
        self.cls = "agk75_rawprobe_%d_%d" % (id(self), time.monotonic_ns())
        self.proc = _WNDPROC(self._proc)  # 창이 있는 동안 참조를 잡아 둔다
        wc = _WndClass(0, self.proc, 0, 0, self.hinst, None, None, None, None, self.cls)
        if not self.u.RegisterClassW(ctypes.byref(wc)):
            raise OSError("Window class registration failed (%d)" % ctypes.get_last_error())
        self.hwnd = self.u.CreateWindowExW(0, self.cls, "agk75", 0, 0, 0, 0, 0, HWND_MESSAGE, None, self.hinst, None)
        if not self.hwnd:
            self.u.UnregisterClassW(self.cls, self.hinst)
            raise OSError("Window creation failed (%d)" % ctypes.get_last_error())
        if register:
            self._register(RIDEV_INPUTSINK, self.hwnd)
            self.registered = True

    def _register(self, flags, target):
        rid = _RawInputDevice(1, 6, flags, target)  # 일반 데스크톱 컨트롤러 > 키보드
        if not self.u.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(rid)):
            raise OSError("Raw Input registration failed (%d)" % ctypes.get_last_error())

    def _is_target(self, handle):
        if handle not in self.names:
            size = wintypes.UINT(0)
            self.u.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, None, ctypes.byref(size))
            buf = ctypes.create_unicode_buffer(size.value + 1)
            ok = self.u.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, buf, ctypes.byref(size)) != 0xFFFFFFFF
            self.names[handle] = ok and NEEDLE in buf.value.upper()
        return self.names[handle]

    def _proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_INPUT and self.on_event:
            t = time.perf_counter_ns()  # Windows 에서는 QueryPerformanceCounter 기반
            hdr, size = _RawInputHeader(), wintypes.UINT(ctypes.sizeof(_RawInputHeader))
            if (self.u.GetRawInputData(lparam, RID_HEADER, ctypes.byref(hdr), ctypes.byref(size),
                                       ctypes.sizeof(hdr)) != 0xFFFFFFFF and hdr.dwType == RIM_TYPEKEYBOARD
                    and self._is_target(hdr.hDevice)):
                self.on_event(t)
        return self.u.DefWindowProcW(hwnd, msg, wparam, lparam)

    def pump(self, ms):
        self.u.MsgWaitForMultipleObjects(0, None, False, ms, QS_ALLINPUT)
        msg = wintypes.MSG()
        while self.u.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            self.u.DispatchMessageW(ctypes.byref(msg))

    def close(self):
        if self.registered:
            self._register(RIDEV_REMOVE, None)
            self.registered = False
        self.u.DestroyWindow(self.hwnd)
        self.u.UnregisterClassW(self.cls, self.hinst)


def probe():
    """창을 만들었다가 바로 지운다(Raw Input 은 등록하지 않는다). 동작 확인용."""
    _Window(register=False).close()
    return True


class Measurer:
    """측정 스레드 한 개. 측정이 끝나면 창이 사라지고 시각 목록은 간격 분석 결과만 남긴다."""

    def __init__(self):
        self.thread, self.times, self.total, self.t0 = None, [], 0, 0.0
        self.result = self.error = None

    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, seconds):
        if self.running():
            raise MsgError("err.measure_busy")
        self.times, self.result, self.error = [], None, None
        self.total, self.t0 = seconds, time.monotonic()
        self.thread = threading.Thread(target=self._run, args=(seconds,), daemon=True)
        self.thread.start()

    def _run(self, seconds):
        times = self.times
        try:
            win = _Window(times.append)
            try:
                end = time.monotonic() + seconds
                while time.monotonic() < end:
                    win.pump(50)
            finally:
                win.close()
            self.result = analyze([(b - a) / 1e6 for a, b in zip(times, times[1:])])
        except Exception as e:  # 화면에 원인을 그대로 보여 준다
            self.error = "%s: %s" % (type(e).__name__, e)
        finally:
            self.times = []  # 시각 목록은 결과 계산 뒤 버린다

    def status(self):
        run = self.running()
        return {"running": run, "seconds": self.total, "events": len(self.times),
                "remaining": max(0.0, self.total - (time.monotonic() - self.t0)) if run else 0.0,
                "result": self.result, "error": self.error}
