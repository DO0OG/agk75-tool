"""폴링레이트 실측: Windows USB ETW 추적에서 이 키보드의 인터럽트 IN 완료 시각만 뽑아 최소 간격 대역으로 판정한다.

전송 시각은 어느 설정에서나 0.125ms 눈금에 맞을 수 있어 격자 판정은 근거가 못 된다. 키를 여러 개 동시에 누르면
펌웨어가 폴링 주기마다 리포트를 보내므로, 관찰된 가장 짧은 간격 대역이 폴링 주기의 근거다.
페이로드 키워드는 켜지 않는다(시각과 엔드포인트만 쓰고 키 내용은 읽지도 저장하지도 않는다).

권한 상승이 필요한 일(추적 세션)은 이 모듈을 `--trace <작업 파일>`로 다시 실행한 관리자 프로세스가 한다.
관리자 쪽은 작업 파일에서 초 수(3~60 정수)만 받고, 실행할 명령은 고정 경로의 logman/tracerpt 뿐이다.
"""
import bisect
import ctypes
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from ctypes import wintypes
from pathlib import Path

from .i18n import MsgError
from .protocol import PID, VID

SESSION = "agk75poll"
NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"
G_UCX = "{36da592d"  # USB-UCX: 이벤트 6(파이프 rundown), 27(인터럽트/벌크 전송 완료)
G_XHCI = "{30e1d284"  # USB-USBXHCI: 이벤트 4(rundown, 장치 디스크립터 VID/PID)
PROVIDERS = ("{30E1D284-5D88-459C-83FD-6345B39B19EC} 0x8000 0x04\n"
             "{36DA592D-E43A-4E28-AF6F-4BC57C5A11E8} 0x8040 0x04\n")

HZ = {0.125: 8000, 0.25: 4000, 0.5: 2000, 1.0: 1000, 2.0: 500, 4.0: 250}
PERIODS = tuple(sorted(HZ))
BAND_LO, BAND_HI = 0.85, 1.05  # 대역 = 주기의 0.85~1.05배(실측 최소 간격은 주기의 0.88~1.0배였다)
SHORT_MAX = 4.2  # ms. 가장 긴 주기(4ms)의 대역 끝. 이보다 긴 간격은 판정에 쓰지 않는다
MIN_SHORT, MIN_BAND, ENOUGH_BAND = 30, 10, 50
BELOW_MAX = 0.10  # 대역보다 짧은 간격은 상위 표본의 10% 이하여야 한다(앞 패킷 완료 기록이 늦은 이상치)
KEEP_MS = 10.0  # 관리자 쪽 결과에는 이보다 짧은 간격만 남긴다
HIST_STEP, HIST_BINS = 0.125, 16  # 짧은 간격 분포: 0~2ms

JOB_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.ops\.json")
SECONDS_MIN, SECONDS_MAX = 3, 60
WAIT_EXTRA = 120  # 변환에 걸리는 시간 여유(초)


# ---------------------------------------------------------------- 판정
def analyze_gaps(gaps_ms):
    """한 엔드포인트의 완료 간격(ms) -> 최소 간격 대역으로 본 폴링 주기.

    이론 주기 후보마다 대역에 든 간격 수를 세고, 그 대역보다 짧은 간격이 적을 때(이상치뿐일 때) 가장 짧은 주기를 고른다.
    관찰된 최소 간격이므로 표본이 적으면 실제 폴링레이트는 이보다 높을 수 있다(note "few").
    """
    short = sorted(g for g in gaps_ms if 0 < g <= SHORT_MAX)
    out = {"hz": None, "period_ms": None, "band_count": 0, "min_ms": short[0] if short else None, "max_ms": None,
           "samples": len(short), "note": "insufficient"}
    if len(short) < MIN_SHORT:
        return out
    for p in PERIODS:
        i, j = bisect.bisect_left(short, p * BAND_LO), bisect.bisect_right(short, p * BAND_HI)
        if j - i >= MIN_BAND and i <= BELOW_MAX * (len(short) - i):
            out.update(hz=HZ[p], period_ms=p, band_count=j - i, min_ms=short[i], max_ms=short[j - 1],
                       note="ok" if j - i >= ENOUGH_BAND else "few")
            break
    return out


def histogram(gaps_ms):
    h = [0] * HIST_BINS
    for g in gaps_ms:
        if 0 < g < HIST_STEP * HIST_BINS:
            h[int(g / HIST_STEP)] += 1
    return h


def summarize(data):
    """관리자 쪽 결과(엔드포인트별 간격) -> 엔드포인트별 판정과 가장 빠른 엔드포인트."""
    eps = []
    for e in data["endpoints"]:
        r = analyze_gaps(e["gaps_ms"])
        r.update(ep=e["ep"], events=e["events"], hist=histogram(e["gaps_ms"]))
        eps.append(r)
    done = [e for e in eps if e["hz"]]
    return {"endpoints": eps, "best": max(done, key=lambda e: e["hz"]) if done else (eps[0] if eps else None)}


# ---------------------------------------------------------------- 관리자 쪽
def _run(cmd):
    return subprocess.run(cmd, capture_output=True, creationflags=0x08000000)  # CREATE_NO_WINDOW


def _windir():
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.kernel32.GetSystemWindowsDirectoryW(buf, 260)
    return buf.value


def _sys32(name):
    return os.path.join(_windir(), "System32", name)


def job_dir():
    return Path(os.environ["APPDATA"]) / "AGK75Tool" / "admin"


def read_job(path):
    """작업 파일 -> (초 수, 결과 파일 경로). 이름·위치·내용이 하나라도 어긋나면 ValueError."""
    real, base = os.path.realpath(path), os.path.realpath(job_dir())
    if os.path.normcase(os.path.dirname(real)) != os.path.normcase(base) or not JOB_RE.fullmatch(os.path.basename(real)):
        raise ValueError("job path")
    with open(real, "rb") as f:
        raw = f.read(257)
    data = json.loads(raw) if len(raw) <= 256 else None
    sec = data.get("seconds") if isinstance(data, dict) and set(data) == {"seconds"} else None
    if isinstance(sec, bool) or not isinstance(sec, int) or not SECONDS_MIN <= sec <= SECONDS_MAX:
        raise ValueError("job content")
    return sec, os.path.join(base, os.path.basename(real)[:-len(".ops.json")] + ".result.json")


def _tns(ts):
    y, mo, d, h, mi, s, f = re.match(r"(\d+)-(\d+)-(\d+)T(\d+):(\d+):(\d+)\.(\d+)", ts).groups()
    day = datetime.date(int(y), int(mo), int(d)).toordinal()
    return ((day * 24 + int(h)) * 60 + int(mi)) * 60 * 10**9 + int(s) * 10**9 + int((f + "000000000")[:9])


def _flat(ed):
    return {x.get("Name"): (x.text or "").strip() for x in ed.iter(NS + "Data") if x.get("Name")}


def parse_etl_xml(path, vid, pid):
    """tracerpt XML -> 이 장치의 인터럽트 IN 엔드포인트별 완료 시각(ns) {주소: [시각]}."""
    dev, pipe, comp = {}, {}, []
    for _, e in ET.iterparse(path, events=("end",)):
        if e.tag != NS + "Event":
            continue
        s = e.find(NS + "System")
        g = s.find(NS + "Provider").get("Guid").lower()[:9]
        eid = int(s.find(NS + "EventID").text)
        if (g, eid) in ((G_XHCI, 4), (G_UCX, 6), (G_UCX, 27)):
            d = _flat(e.find(NS + "EventData"))
            if (g, eid) == (G_XHCI, 4):
                dev[d["fid_UsbDevice"]] = (int(d["fid_idVendor"], 0), int(d["fid_idProduct"], 0))
            elif (g, eid) == (G_UCX, 6):
                pipe[d["fid_PipeHandle"]] = (int(d["fid_bEndpointAddress"], 0), int(d["fid_bmAttributes"], 0))
            else:
                comp.append((_tns(s.find(NS + "TimeCreated").get("SystemTime")), d["fid_PipeHandle"], d["fid_UsbDevice"]))
        e.clear()
    eps = {}
    for ts, ph, ud in comp:
        pi = pipe.get(ph)
        if pi and pi[0] & 0x80 and pi[1] & 3 == 3 and dev.get(ud) == (vid, pid):  # 인터럽트 IN 만
            eps.setdefault(pi[0], []).append(ts)
    return eps


def _gaps(times_ns):
    t = sorted(times_ns)
    return [round((b - a) / 1e6, 4) for a, b in zip(t, t[1:]) if 0 < b - a < KEEP_MS * 1e6]


def capture(seconds, work):
    """추적 세션 시작 -> seconds 대기 -> 중지 -> 변환 -> 엔드포인트별 간격. 세션 정리는 호출한 쪽이 한 번 더 한다."""
    etl, xml, pf = (os.path.join(work, n) for n in ("trace.etl", "trace.xml", "providers.txt"))
    with open(pf, "w", encoding="ascii") as f:
        f.write(PROVIDERS)
    logman, tracerpt = _sys32("logman.exe"), _sys32("tracerpt.exe")
    _run([logman, "stop", SESSION, "-ets"])  # 이전 실행이 남긴 세션
    r = _run([logman, "start", SESSION, "-ets", "-pf", pf, "-o", etl, "-ct", "perf", "-bs", "1024", "-nb", "64", "256"])
    if r.returncode:
        raise RuntimeError("logman start failed: " + (r.stdout + r.stderr).decode("mbcs", "replace")[:200])
    try:
        time.sleep(seconds)
    finally:
        _run([logman, "stop", SESSION, "-ets"])
    r = _run([tracerpt, etl, "-of", "XML", "-o", xml, "-y", "-lr"])
    if not os.path.exists(xml):
        raise RuntimeError("tracerpt failed: " + (r.stdout + r.stderr).decode("mbcs", "replace")[:200])
    return {"endpoints": [{"ep": ep, "events": len(ts), "gaps_ms": _gaps(ts)}
                          for ep, ts in sorted(parse_etl_xml(xml, VID, PID).items())]}


def admin_main(jobfile):
    """`--trace <작업 파일>`. 작업 파일 검증에 실패하면 아무것도 쓰지 않고 2 로 끝낸다."""
    try:
        seconds, result_path = read_job(jobfile)
    except (OSError, ValueError, KeyError):
        return 2
    work, res = None, None
    try:
        work = tempfile.mkdtemp(prefix="agk75_", dir=os.path.join(_windir(), "Temp"))  # 이 프로세스가 새로 만든 폴더
        res = {"ok": True, **capture(seconds, work)}
    except Exception as e:  # 원인은 결과 파일로 알린다(관리자 프로세스는 창이 없다)
        res = {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
    finally:
        try:
            _run([_sys32("logman.exe"), "stop", SESSION, "-ets"])
        except OSError:
            pass
        if work:
            shutil.rmtree(work, ignore_errors=True)
    try:
        with open(result_path, "x", encoding="utf-8") as f:  # 이미 있으면(바꿔치기) 쓰지 않는다
            json.dump(res, f)
    except OSError:
        return 3
    return 0


# ---------------------------------------------------------------- 일반 권한 쪽
class _ShellExecInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]


def _elevate(job, on_launched, wait_s):
    """자기 자신을 runas 로 `--trace` 실행하고 끝날 때까지 기다려 종료 코드를 돌려준다."""
    if "__compiled__" in globals():  # 빌드본의 sys.executable 은 없는 python.exe 를 가리키므로 argv[0](exe 경로)를 쓴다
        exe, args, cwd = os.path.abspath(sys.argv[0]), '--trace "%s"' % job, None
    else:
        exe, args, cwd = sys.executable, '-m agk75 --trace "%s"' % job, str(Path(__file__).resolve().parent.parent)
    sh, k = ctypes.WinDLL("shell32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
    sh.ShellExecuteExW.argtypes = [ctypes.POINTER(_ShellExecInfo)]
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    # 0x40 NOCLOSEPROCESS, 0x8000 NO_CONSOLE. 마지막 0 = SW_HIDE
    info = _ShellExecInfo(ctypes.sizeof(_ShellExecInfo), 0x40 | 0x8000, None, "runas", exe, args, cwd, 0)
    if not sh.ShellExecuteExW(ctypes.byref(info)):
        err = ctypes.get_last_error()
        raise MsgError("err.trace_uac" if err == 1223 else "err.trace_launch", code=err)
    try:
        if on_launched:
            on_launched()
        if k.WaitForSingleObject(info.hProcess, int(wait_s * 1000)) != 0:
            raise MsgError("err.trace_timeout")
        code = wintypes.DWORD()
        k.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return code.value
    finally:
        k.CloseHandle(info.hProcess)


def _check_result(data):
    if not isinstance(data, dict) or not isinstance(data.get("ok"), bool):
        raise ValueError
    if data["ok"]:
        for e in data["endpoints"]:
            if not (isinstance(e["ep"], int) and isinstance(e["events"], int)
                    and all(isinstance(g, (int, float)) for g in e["gaps_ms"])):
                raise ValueError


def request(seconds, on_launched=None):
    """작업 파일을 만들고 관리자 프로세스를 띄워 결과(엔드포인트별 간격)를 받는다. 두 파일은 항상 지운다."""
    d = job_dir()
    d.mkdir(parents=True, exist_ok=True)
    uid = str(uuid.uuid4())
    job, res = d / (uid + ".ops.json"), d / (uid + ".result.json")
    try:
        job.write_text(json.dumps({"seconds": seconds}), encoding="utf-8")
        code = _elevate(job, on_launched, seconds + WAIT_EXTRA)
        if not res.exists():
            raise MsgError("err.trace_nofile", code=code)
        try:
            data = json.loads(res.read_text("utf-8"))
            _check_result(data)
        except (OSError, ValueError, KeyError, TypeError):
            raise MsgError("err.trace_bad")
    finally:
        for f in (job, res):
            try:
                f.unlink()
            except OSError:
                pass
    if not data["ok"]:
        raise MsgError("err.trace_run", reason=data.get("error", ""))
    return data


class Tracer:
    """측정 스레드 한 개. 작업 스레드를 막지 않고, 진행 상태는 status() 로 읽는다."""

    def __init__(self):
        self.thread, self.total, self.t0, self.phase = None, 0, 0.0, ""
        self.result = self.error = None

    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, seconds):
        if self.running():
            raise MsgError("err.measure_busy")
        self.result = self.error = None
        self.total, self.phase = seconds, "uac"
        self.thread = threading.Thread(target=self._run, args=(seconds,), daemon=True)
        self.thread.start()

    def _launched(self):
        self.t0, self.phase = time.monotonic(), "capture"

    def _run(self, seconds):
        try:
            self.result = summarize(request(seconds, self._launched))
        except Exception as e:  # 화면에 원인을 그대로 보여 준다
            self.error = e
        finally:
            self.phase = ""

    def status(self):
        run, phase = self.running(), self.phase
        remaining = max(0.0, self.total - (time.monotonic() - self.t0)) if run and phase == "capture" else float(self.total)
        if run and phase == "capture" and remaining == 0:
            phase = "analyze"
        return {"running": run, "phase": phase if run else "", "seconds": self.total,
                "remaining": remaining if run else 0.0, "result": self.result, "error": self.error}
