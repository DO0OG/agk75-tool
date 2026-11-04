"""폴링레이트 측정: Windows Raw Input 으로 이 키보드의 WM_INPUT 도착 시각만 모아 간격을 분석한다.

키 입력 내용(VKey, 스캔코드)은 읽지도 저장하지도 않는다. 측정 중에만 숨은 메시지 전용 창이 있다.
"""
import bisect
import ctypes
import math
import statistics
import threading
import time
from ctypes import wintypes

from .i18n import MsgError

RATES = (125, 250, 500, 1000, 2000, 4000, 8000)
EDGES_MS = (0.125, 0.25, 0.5, 1.0, 2.0)
LABELS = ("<0.125", "0.125~0.25", "0.25~0.5", "0.5~1", "1~2", ">=2")
MIN_SAMPLES = 50
SAME_REPORT_MS = 0.05  # 이보다 짧은 간격은 한 리포트에 든 이벤트로 보고 버린다
NEEDLE = "VID_3151&PID_5009"

WM_INPUT, HWND_MESSAGE = 0x00FF, -3
RID_HEADER, RIDI_DEVICENAME, RIM_TYPEKEYBOARD = 0x10000005, 0x20000007, 1
RIDEV_REMOVE, RIDEV_INPUTSINK = 0x1, 0x100
QS_ALLINPUT, PM_REMOVE = 0x04FF, 1


def _cluster(xs):
    """오름차순 xs 에서 가장 짧은 간격 묶음(최소값의 1.5배 이내, 3개 이상)을 찾는다. 최대 3회."""
    start = 0
    for _ in range(3):
        if start >= len(xs) or xs[start] > 3 * xs[0]:  # 먼 값으로 건너뛰면 이상치 하나로 판정이 갈린다
            return None
        group = [x for x in xs[start:] if x <= xs[start] * 1.5]
        if len(group) >= 3:
            return group
        start += len(group)
    return None


def analyze(intervals_ms):
    """이벤트 간격(ms) 목록 -> 최소 간격, 히스토그램, 가장 짧은 간격 묶음 기준 폴링레이트 하한·추정치."""
    xs = sorted(x for x in intervals_ms if x >= SAME_REPORT_MS)
    n = len(xs)
    counts = [0] * len(LABELS)
    for x in xs:
        counts[bisect.bisect_right(EDGES_MS, x)] += 1
    out = {"samples": n, "enough": n >= MIN_SAMPLES, "min_ms": xs[0] if xs else None,
           "hist": [{"label": l, "count": c} for l, c in zip(LABELS, counts)], "hz_at_least": None,
           "hz_estimate": None, "cluster_ms": None, "cluster_n": 0, "note": "measure.note"}
    group = _cluster(xs) if out["enough"] else None
    if group:
        rep = statistics.median(group)
        # 대표값이 어느 주기보다 짧으면 그 레이트는 배제. 주기가 대표값 이하인 가장 낮은 레이트가 하한 (지터 10% 허용)
        out.update(cluster_ms=rep, cluster_n=len(group),
                   hz_at_least=next((r for r in RATES if 1000 / r <= rep * 1.1), RATES[-1]),
                   hz_estimate=min(RATES, key=lambda r: abs(math.log(r * rep / 1000))))
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
