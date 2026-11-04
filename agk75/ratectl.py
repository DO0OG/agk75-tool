"""PC 쪽 USB 필터 드라이버(hidusbf)로 키보드의 USB 폴링 간격을 바꾼다.

읽기 전용 함수(find_device_instance, driver_state, verify_signature)와 내려받기·작업 계획은 일반 권한에서 돌고,
레지스트리 쓰기·드라이버 설치·장치 재시작은 admin_main 이 관리자 프로세스에서만 수행한다.
외부 명령은 전부 _run 한 곳을 거치고, 내려받기는 _urlopen, 상승은 _shell_execute 를 거친다(테스트에서 교체).
"""
import ctypes
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path

from . import i18n, usbinfo

FILTER = "hidusbf"
INSTANCE_RE = r"USB\\%s\\[0-9A-Za-z&_.\-]+" % usbinfo.VID_PID
ENUM = r"SYSTEM\CurrentControlSet\Enum\USB" + "\\" + usbinfo.VID_PID
SERVICE = r"SYSTEM\CurrentControlSet\Services\hidusbf"
HVCI = r"SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity"
SECURE_BOOT = r"SYSTEM\CurrentControlSet\Control\SecureBoot\State"
SYS_PATH = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "hidusbf.sys"
PKG_URL = "https://github.com/LordOfMice/hidusbf/raw/HEAD/hidusbf.zip"
MAX_ZIP = 64 << 20
MAX_UNPACK, MAX_FILES = 20 << 20, 200  # 압축 해제 총량과 파일 수 상한
SIGNER_SUBJECT = ("CN=Microsoft Windows Hardware Compatibility Publisher, O=Microsoft Corporation, "
                  "L=Redmond, S=Washington, C=US")
USB_CLASS = "{36fc9e60-c465-11cf-8056-444553540000}"
INF_UNINSTALL = "HIDUSBFU.INF"
MAX_INF = 256 << 10
JOB_RE = re.compile(r"[0-9a-f]{32}\.ops\.json")
REBOOT_RE = re.compile(r"다시 부팅|재부팅|reboot", re.I)
INF_SET, INF_SYS = "HIDUSBF_AS.INF", ("amd64_as", "hidusbf.sys")
OPS = ("install", "filter_add", "filter_remove", "binterval", "binterval_del", "restart")
# 8000Hz 는 필터 해제(bInterval 1 이 기본 그대로). 값의 의미는 실기기 확인 전 가설 A(125µs × 2^(n-1)).
RATE_TABLE = {8000: 1, 4000: 2, 2000: 3, 1000: 4}


class RateError(i18n.MsgError):
    """사용자에게 보여 줄 수 있는 실패(서버가 400 으로 돌려준다). 키가 사전에 없으면 영어 원문이다."""


# ---------- 외부 동작(테스트에서 교체) ----------
def _run(args, timeout=60):
    p = subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=timeout,
                       creationflags=0x08000000)  # CREATE_NO_WINDOW
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _urlopen(url):
    return urllib.request.urlopen(url, timeout=30)


def _shell_execute(exe, args, cwd):
    return int(ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, cwd, 0) or 0)


def _sleep(sec):
    time.sleep(sec)


def _reg_read(sub, name):
    """HKLM\\sub 의 값(없으면 None). 읽기만 한다."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def _reg_subkeys(sub):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub) as k:
            return [winreg.EnumKey(k, i) for i in range(winreg.QueryInfoKey(k)[0])]
    except OSError:
        return []


# ---------- 경로 ----------
def base_dir(sub=""):
    return Path(os.environ.get("APPDATA") or Path.home()) / "AGK75Tool" / sub


def stage_dir():
    return base_dir("hidusbf") / "stage"


def _inst_key(inst):
    return ENUM + "\\" + inst.split("\\")[-1]


# ---------- 읽기 ----------
def connected_instances():
    """지금 연결된 키보드의 복합 장치 인스턴스 ID. pnputil 출력에서 ID 패턴만 찾는다(언어 무관)."""
    rc, out = _run(["pnputil", "/enum-devices", "/connected", "/class", USB_CLASS])
    return list(dict.fromkeys(re.findall(INSTANCE_RE, out, re.I))) if rc == 0 else []


def all_instances():
    """레지스트리에 남아 있는 이 키보드의 모든 인스턴스(연결 여부 무관)."""
    ids = ("USB\\%s\\%s" % (usbinfo.VID_PID, k) for k in _reg_subkeys(ENUM))
    return [i for i in ids if re.fullmatch(INSTANCE_RE, i, re.I)]


def find_device_instance():
    """연결된 인스턴스 하나. 없으면 None, 둘 이상이면 어느 쪽인지 알 수 없으므로 오류."""
    found = connected_instances()
    if len(found) > 1:
        raise RateError("rate.multi_device", n=len(found), ids=", ".join(found))
    return found[0] if found else None


def driver_state():
    try:
        inst, err, msg = find_device_instance(), None, None
    except RateError as e:
        inst, err, msg = None, str(e), i18n.to_json(e)
    key = _inst_key(inst) if inst else None
    filters = (_reg_read(key, "LowerFilters") if key else None) or []
    interval = _reg_read(key + "\\Device Parameters", "bInterval") if key else None
    on = any(f.lower() == FILTER for f in filters)
    back = {v: k for k, v in RATE_TABLE.items()}
    return {"device": inst, "device_error": err, "device_error_msg": msg, "service": _reg_read(SERVICE, "ImagePath") is not None,
            "sys": SYS_PATH.is_file(), "filter": on, "binterval": interval, "configured_hz": back.get(interval) if on else None,
            "hvci": _reg_read(HVCI, "Enabled") == 1, "secure_boot": _reg_read(SECURE_BOOT, "UEFISecureBootEnabled") == 1,
            "package": (stage_dir() / INF_SET).is_file()}


def verify_signature(path, subject=SIGNER_SUBJECT):
    """Authenticode 서명이 유효하고 서명자 Subject 가 subject 와 완전히 같은지 확인한다."""
    ps = ("$s=Get-AuthenticodeSignature -LiteralPath '%s'; 'Status='+$s.Status; "
          "'Subject='+$s.SignerCertificate.Subject" % str(path).replace("'", "''"))
    rc, out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps])
    kv = dict(re.findall(r"^(Status|Subject)=(.*)$", out, re.M))
    status, subject_got = kv.get("Status", "").strip(), kv.get("Subject", "").strip()
    return {"ok": rc == 0 and status == "Valid" and subject_got == subject,
            "status": status or "unknown", "subject": subject_got}


# ---------- 내려받기·준비 ----------
def download_package(dest, url=PKG_URL):
    """zip 을 내려받아 .inf 와 hidusbf.sys 만 새 빈 폴더 dest 에 푼다. 경로가 폴더 밖으로 나가면 통째로 거부한다."""
    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()):
        raise RateError("rate.dir_not_empty", path=dest)
    try:
        with _urlopen(url) as r:
            data = r.read(MAX_ZIP + 1)
    except OSError as e:  # URLError 포함
        raise RateError("rate.download_fail", reason=e)
    if len(data) > MAX_ZIP:
        raise RateError("rate.too_big")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise RateError("rate.not_zip")
    root, picks = dest.resolve(), []
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_UNPACK:
            raise RateError("rate.zip_big")
        for info in infos:
            name = info.filename
            target = (dest / name).resolve()
            if name.startswith(("/", "\\")) or ":" in name or root not in (target, *target.parents):
                raise RateError("rate.zip_path", name=name)
            if not name.endswith("/") and name.lower().endswith((".inf", "hidusbf.sys")):
                picks.append((info, target))
        for info, target in picks:
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def _ci(base, *parts):
    """대소문자를 무시하고 base 아래 경로를 찾는다(없으면 None)."""
    p = Path(base)
    for part in parts:
        p = next((c for c in p.iterdir() if c.name.lower() == part.lower()), None) if p.is_dir() else None
        if p is None:
            return None
    return p


def stage_package(src, stage):
    """압축 해제본에서 INF 와 서명된 AMD64_AS 드라이버만 골라 INF 가 기대하는 구조(amd64_as\\hidusbf.sys)로 복사한다.
    NoPatch 가 있으면 그것을 쓴다. 서명이 유효하지 않으면 스테이징을 지우고 실패한다."""
    infs = sorted((p for p in Path(src).rglob("*") if p.name.upper() == INF_SET), key=lambda p: len(p.parts))
    if not infs:
        raise RateError("rate.inf_missing", name=INF_SET)
    d = infs[0].parent
    uninf = _ci(d, INF_UNINSTALL)
    sys_file = _ci(d, "AMD64_AS", "NoPatch", INF_SYS[1])
    nopatch = sys_file is not None
    sys_file = sys_file or _ci(d, "AMD64_AS", INF_SYS[1])
    if not (uninf and sys_file):
        raise RateError("rate.files_missing")
    out = Path(stage)
    shutil.rmtree(out, ignore_errors=True)
    (out / INF_SYS[0]).mkdir(parents=True)
    shutil.copy(infs[0], out / INF_SET)
    shutil.copy(uninf, out / INF_UNINSTALL)
    shutil.copy(sys_file, out.joinpath(*INF_SYS))
    v = verify_signature(out.joinpath(*INF_SYS))
    if not v["ok"]:
        shutil.rmtree(out, ignore_errors=True)
        raise RateError("rate.sig_fail", status=v["status"], signer=v["subject"] or i18n.Msg("common.none"))
    return {"inf": str(out / INF_SET), "nopatch": nopatch, "signer": v["subject"]}


def prepare(base=None):
    base = Path(base) if base else base_dir("hidusbf")
    tmp = base / ("dl_" + uuid.uuid4().hex)
    try:
        download_package(tmp)
        return stage_package(tmp, base / "stage")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- 작업 계획(데이터) ----------
def _device(state):
    if not state.get("device"):
        m = state.get("device_error_msg") or {"key": "rate.device_missing"}
        raise RateError(m["key"], **m.get("params", {}))
    return state["device"]


def plan_set(hz, state=None):
    if hz == 8000:
        return plan_reset()
    if hz not in RATE_TABLE:
        raise RateError("rate.unsupported", hz=hz)
    state = state or driver_state()
    inst, ops = _device(state), []
    if not (state["service"] and state["sys"]):
        if not state["package"]:
            raise RateError("rate.prepare_first")
        ops.append({"op": "install", "inf": str(stage_dir() / INF_SET)})
    if not state["filter"]:
        ops.append({"op": "filter_add", "instance": inst})
    return ops + [{"op": "binterval", "instance": inst, "value": RATE_TABLE[hz]},
                  {"op": "restart", "instance": inst}]


def plan_reset():
    """연결 여부와 무관하게 이 키보드의 모든 인스턴스에서 bInterval 과 필터를 지운다(복구용). 재시작은 연결된 것만. 이미 원래 상태면 빈 목록."""
    ops, hit = [], []
    for inst in all_instances():
        key = _inst_key(inst)
        has = any(f.lower() == FILTER for f in (_reg_read(key, "LowerFilters") or []))
        if has or _reg_read(key + "\\Device Parameters", "bInterval") is not None:
            ops += [{"op": "binterval_del", "instance": inst}, {"op": "filter_remove", "instance": inst}]
            hit.append(inst)
    live = {i.lower() for i in connected_instances()}
    return ops + [{"op": "restart", "instance": i} for i in hit if i.lower() in live]


# ---------- 관리자 실행(요청 쪽) ----------
def _err(key, **params):
    """결과 dict 에 넣을 오류: error 는 영어 원문, error_msg 는 서버가 요청 언어로 번역할 키."""
    e = RateError(key, **params)
    return {"error": str(e), "error_msg": i18n.to_json(e)}


def _self_cmd(jobfile):
    if "__compiled__" in globals():
        return sys.executable, '--admin "%s"' % jobfile, None
    return sys.executable, '-m agk75 --admin "%s"' % jobfile, str(Path(__file__).resolve().parents[1])


def admin_pending(result):
    """결과 경로가 있는데 아직 결과 파일이 없으면 그 관리자 작업은 끝나지 않은 것이다."""
    return bool(result) and not Path(result).is_file()


def run_admin(ops, timeout=600, poll=0.5):
    """자기 자신을 관리자로 다시 띄워 ops 를 맡기고 결과 파일을 기다린다. 다른 PC 에서는 UAC 창이 뜬다.
    기한 안에 결과가 없으면 pending 에 결과 경로를 담아 돌려준다(호출 쪽이 그 작업이 끝날 때까지 새 요청을 막는다)."""
    d = base_dir("admin")
    d.mkdir(parents=True, exist_ok=True)
    job = uuid.uuid4().hex
    jobfile, result = d / (job + ".ops.json"), d / (job + ".json")
    jobfile.write_text(json.dumps({"ops": ops}), encoding="utf-8")
    code = _shell_execute(*_self_cmd(jobfile))
    if code <= 32:
        return {"ok": False, "ops": [], **_err("rate.admin_denied", code=code)}
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if result.is_file():
            try:
                return json.loads(result.read_text(encoding="utf-8"))
            except ValueError:
                pass  # 아직 쓰는 중
        _sleep(poll)
    return {"ok": False, "ops": [], "pending": str(result), **_err("rate.admin_timeout", sec=timeout)}


def needs_reboot(res):
    """장치 재시작 출력에 재부팅 보류 문구가 있으면 True."""
    return any(REBOOT_RE.search(str(o.get("detail", ""))) for o in res.get("ops", []))


def reread_usb(tries=10, delay=1.0):
    """장치가 다시 연결돼 USB 협상값을 읽을 수 있을 때까지 기다린다."""
    for _ in range(tries):
        usb = usbinfo.read()
        if "error" not in usb:
            break
        _sleep(delay)
    return usb


# ---------- 관리자 쪽 ----------
def _check_op(op):
    kind = op.get("op") if isinstance(op, dict) else None
    if kind not in OPS:
        raise RateError("operation not allowed: %r" % (kind,))
    if kind == "install":  # 요청 쪽이 적은 경로는 믿지 않고, 고정된 준비 폴더의 INF 인지만 확인한다
        real = lambda p: os.path.normcase(os.path.realpath(str(p)))
        if real(op.get("inf", "")) != real(stage_dir() / INF_SET):
            raise RateError("INF cannot be installed: %s" % op.get("inf"))
    elif not re.fullmatch(INSTANCE_RE, str(op.get("instance", "")), re.I):
        raise RateError("device ID not allowed: %s" % op.get("instance"))
    if kind == "binterval" and op.get("value") not in RATE_TABLE.values():
        raise RateError("bInterval not allowed: %s" % op.get("value"))
    return op


def _sh(args, ok=(0,)):
    rc, out = _run(args)
    if rc not in ok:
        raise RateError("rate.sh_fail", cmd=args[0], rc=rc, out=out.strip())
    return out.strip()


def _set_filters(key, items):
    path = "HKLM\\" + key
    if items:
        _sh(["reg", "add", path, "/v", "LowerFilters", "/t", "REG_MULTI_SZ", "/d", "\\0".join(items), "/f"])
    else:
        _sh(["reg", "delete", path, "/v", "LowerFilters", "/f"])


# ---------- INF 엄격 검사 ----------
_FORBIDDEN = ("registerdlls", "runpresetupcommands", "runpostsetupcommands", "addreg", "delreg", "copyinf", "include",
              "needs", "updateinis", "updateinifields", "ini2reg", "bitreg", "addinterface")
_VERSION_KEYS = ("signature", "class", "classguid", "provider", "driverver", "catalogfile",
                 "driverpackagedisplayname", "driverpackagetype")
_SVC_NUM = {"servicetype": 1, "starttype": 3, "errorcontrol": 1}
_WORD = r"[\w.\-]*"
_SVC_SEC = r"hidusbfservice|" + _WORD + "_service_inst"
_DEST_OK = ("12", "10,system32" + chr(92) + "drivers")  # 드라이버 폴더 외 목적지는 허용하지 않는다


def _inf_kind(sec, uninstall):
    files = _WORD + "delfiles" + _WORD if uninstall else "drivercopyfiles" + _WORD
    for pat, kind in (("version", "ver"), ("destinationdirs", "dirs"), ("strings", "strings"),
                      ("defaultinstall" + _WORD + "|" + _WORD + r"\.services|" + _WORD + "addservice", "install"),
                      (files, "files"), ("sourcedisksnames" + _WORD, "disks"), ("sourcedisksfiles" + _WORD, "srcfiles"),
                      (_SVC_SEC, "svc")):
        if re.fullmatch(pat, sec):
            return kind
    return None


def _inf_lines(text):
    for raw in text.splitlines():
        out, quoted = [], False
        for ch in raw:
            if ch == '"':
                quoted = not quoted
            elif ch == ";" and not quoted:
                break
            out.append(ch)
        line = "".join(out).strip()
        if line:
            yield line


def _num(v):
    try:
        return int(v.strip(), 0)
    except ValueError:
        return None


def check_inf(text, uninstall=False):
    """INF 를 섹션·지시어 화이트리스트로 검사한다. 하나라도 벗어나면 RateError.
    설치 INF 는 hidusbf.sys 복사와 hidusbf 서비스 등록만, 제거 INF 는 그 삭제만 허용한다."""
    if "\x00" in text:
        raise RateError("INF contains a NUL character")
    allow = ("delfiles", "delservice") if uninstall else ("copyfiles", "addservice")
    files_pat = _WORD + "delfiles" + _WORD if uninstall else "drivercopyfiles" + _WORD
    dirs_pat = r"defaultdestdir|driverdelfiles(nt)?" if uninstall else r"defaultdestdir|drivercopyfiles(nt)?"
    sec, kind, seen, binary = None, None, set(), False
    for line in _inf_lines(text):
        if line.endswith("\\"):
            raise RateError("INF line continuation is not allowed: %s" % line)
        m = re.fullmatch(r"\[([^\]]+)\]", line)
        if m:
            sec = m.group(1).strip().lower()
            kind = _inf_kind(sec, uninstall)
            if kind is None:
                raise RateError("INF section not allowed: [%s]" % m.group(1))
            seen.add(sec)
            continue
        if sec is None:
            raise RateError("INF line outside any section: %s" % line)
        if kind == "files":  # hidusbf.sys[,,,0x04] 형태만(대상·원본 이름 자리는 비워야 한다)
            f = [t.strip().lower() for t in line.split(",")]
            if f[0] != "hidusbf.sys" or not all(re.fullmatch(r"|0x[0-9a-f]+", t) for t in f[1:]):
                raise RateError("INF file not allowed: %s" % line)
            continue
        key, eq, val = (t.strip() for t in line.partition("="))
        key = key.lower()
        parts = [t.strip() for t in val.split(",")]
        ok = False
        if key in _FORBIDDEN or not eq:
            pass
        elif kind == "ver":
            ok = key in _VERSION_KEYS or key.startswith("catalogfile.")
        elif kind == "dirs":
            ok = val.lower() in _DEST_OK and re.fullmatch(dirs_pat, key) is not None
        elif kind == "strings":
            ok = re.fullmatch(r"[\w.\-]+", key) is not None
        elif kind == "install" and key in allow:
            if key in ("copyfiles", "delfiles"):
                ok = all(p.lower() == "@hidusbf.sys" or re.fullmatch(files_pat, p.lower()) for p in parts)
            elif key == "addservice":
                ok = len(parts) >= 3 and parts[0].lower() == FILTER and bool(re.fullmatch(_SVC_SEC, parts[2].lower()))
            else:
                ok = parts[0].lower() == FILTER
        elif kind == "disks":
            ok = not re.search(r"\.\.|:", val) and not val.startswith(("\\", "/"))
        elif kind == "srcfiles":
            ok = key == "hidusbf.sys" and _num(parts[0]) is not None and not re.search(r"\.\.|:", val)
        elif kind == "svc":
            if key == "servicebinary":
                ok = binary = val.lower() == r"%12%\hidusbf.sys"
            else:
                ok = key in ("displayname", "description", "loadordergroup") or (key in _SVC_NUM and _num(val) == _SVC_NUM[key])
        if not ok:
            raise RateError("INF directive not allowed: %s" % line)
    if not any(x.startswith("defaultinstall") for x in seen) or not (uninstall or binary):
        raise RateError("INF is missing the required DefaultInstall or ServiceBinary")


def _read_inf(path):
    raw = Path(path).read_bytes()
    if len(raw) > MAX_INF:
        raise RateError("INF is too large: %s" % Path(path).name)
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


# ---------- 관리자 전용 폴더로 복사한 뒤 설치 ----------
def secure_root():
    return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "AGK75Tool" / "stage"


def _admin_only(d, fresh=False):
    """폴더를 만들고 상속을 끊어 Administrators·SYSTEM 만 쓰게 한다."""
    d.mkdir(parents=True, exist_ok=not fresh)
    _sh(["icacls", str(d), "/inheritance:r", "/grant:r", "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"])


def _install():
    src, dst = stage_dir(), secure_root() / uuid.uuid4().hex
    for d in (dst.parent.parent, dst.parent):
        _admin_only(d)
    _admin_only(dst, fresh=True)
    try:
        for rel in (INF_SET, INF_UNINSTALL, "/".join(INF_SYS)):
            s = src / rel
            if not s.is_file() or s.stat().st_size > MAX_UNPACK:
                raise RateError("rate.staged_missing", rel=rel)
            (dst / rel).parent.mkdir(exist_ok=True)
            shutil.copyfile(s, dst / rel)
        v = verify_signature(dst.joinpath(*INF_SYS))  # 검사는 전부 관리자 전용 복사본에 대해 한다
        if not v["ok"]:
            raise RateError("rate.sig_bad", status=v["status"])
        check_inf(_read_inf(dst / INF_SET))
        check_inf(_read_inf(dst / INF_UNINSTALL), uninstall=True)
        _sh(["rundll32", "setupapi,InstallHinfSection", "DefaultInstall", "132", str(dst / INF_SET)])
        if _reg_read(SERVICE, "ImagePath") is None:
            raise RateError("rate.svc_missing")
    finally:
        shutil.rmtree(dst, ignore_errors=True)
    return i18n.Msg("rate.installed")


def _do_op(op):
    kind = op["op"]
    if kind == "install":
        return _install()
    inst = op["instance"]
    key = _inst_key(inst)
    params = "HKLM\\" + key + "\\Device Parameters"
    filters = list(_reg_read(key, "LowerFilters") or [])
    if kind == "filter_add":
        if not any(f.lower() == FILTER for f in filters):
            _set_filters(key, filters + [FILTER])
    elif kind == "filter_remove":
        rest = [f for f in filters if f.lower() != FILTER]
        if rest != filters:
            _set_filters(key, rest)
    elif kind == "binterval":
        _sh(["reg", "add", params, "/v", "bInterval", "/t", "REG_DWORD", "/d", str(op["value"]), "/f"])
    elif kind == "binterval_del":
        if _reg_read(key + "\\Device Parameters", "bInterval") is not None:
            _sh(["reg", "delete", params, "/v", "bInterval", "/f"])
    else:  # restart (3010 = 재부팅 필요, 장치 재시작 요청 자체는 성공)
        rc, out = _run(["pnputil", "/restart-device", inst])
        if rc not in (0, 3010):
            raise RateError("rate.pnputil", rc=rc, out=out.strip())
        return i18n.Msg("rate.restart_reboot", out=out.strip()) if rc == 3010 else out.strip()
    return i18n.Msg("rate.done")


def _op_out(op, ok, detail):
    """작업 결과 한 줄: detail 은 영어 원문, detail_msg 는 서버가 번역할 키."""
    out = {"op": op["op"], "ok": ok, "detail": str(detail)}
    if isinstance(detail, i18n.Msg):
        out["detail_msg"] = i18n.to_json(detail)
    return out


def admin_main(path):
    """관리자 프로세스 진입점: 작업 파일 → 레지스트리 백업(reg export) → 작업 순서대로 수행 → 결과 파일.
    0 = 성공, 1 = 작업 실패(결과 파일에 기록), 2 = 작업 파일 위치·이름이 올바르지 않아 아무것도 쓰지 않음."""
    jobfile = Path(os.path.realpath(path))
    try:
        if not JOB_RE.fullmatch(jobfile.name) or os.path.normcase(str(jobfile.parent)) != os.path.normcase(
                os.path.realpath(base_dir("admin"))):
            raise RateError("job file location is invalid")
        job = json.loads(jobfile.read_text(encoding="utf-8"))
        if not isinstance(job, dict) or not isinstance(job.get("ops"), list):
            raise RateError("job file format is invalid")
    except (RateError, OSError, ValueError):
        return 2
    result = jobfile.with_name(jobfile.name[:-len(".ops.json")] + ".json")  # JSON 의 result 는 무시한다
    out = {"ok": False, "backup": None, "ops": []}
    try:
        ops = [_check_op(o) for o in job["ops"]]  # 하나라도 틀리면 아무것도 하지 않는다
        if len({o["instance"] for o in ops if o["op"] in ("filter_add", "binterval")}) > 1:
            raise RateError("values can be written to only one device at a time")
        for n, inst in enumerate(sorted({o["instance"] for o in ops if "instance" in o})):
            backup = result.with_name(result.stem + (".%d" % n if n else "") + ".reg")
            _sh(["reg", "export", "HKLM\\" + _inst_key(inst), str(backup), "/y"])
            out["backup"] = out["backup"] or str(backup)
        for op in ops:
            try:
                out["ops"].append(_op_out(op, True, _do_op(op)))
            except (RateError, OSError) as e:
                out["ops"].append(_op_out(op, False, e))
                raise
        out["ok"] = True
    except (RateError, OSError) as e:
        out["error"] = str(e)
        if isinstance(e, i18n.Msg):
            out["error_msg"] = i18n.to_json(e)
    tmp = result.with_name(result.name + "." + uuid.uuid4().hex + ".tmp")
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False))  # O_EXCL: 미리 놓인 링크를 따라가지 않는다
    os.replace(tmp, result)  # 요청 쪽이 쓰다 만 파일을 읽지 않게 한다
    return 0 if out["ok"] else 1
