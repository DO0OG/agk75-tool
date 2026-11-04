"""설정 화면용 로컬 서버: agk75/web 정적 파일 + JSON API. 표준 라이브러리만 쓴다."""
import fnmatch
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import i18n
from . import protocol as P
from . import ratectl, usbinfo
from .i18n import MsgError, t

WEB = Path(__file__).parent / "web"
TYPES = {".html": "text/html", ".css": "text/css", ".js": "application/javascript",
         ".svg": "image/svg+xml", ".json": "application/json"}
MAG_NUM = ("travel", "lift", "dead", "rt_press", "rt_lift")
MAG_RANGE = {"travel": (0.1, 3.5), "lift": (0.1, 3.5), "dead": (0.0, 1.0),
             "rt_press": (0.1, 2.0), "rt_lift": (0.1, 2.0)}


def data_dir(sub=""):
    """빌드된 exe 는 %APPDATA% 아래 AGK75Tool 폴더, 소스 실행은 현재 폴더."""
    if "__compiled__" in globals():
        d = Path(os.environ.get("APPDATA") or Path.home()) / "AGK75Tool" / sub
        d.mkdir(parents=True, exist_ok=True)
        return d
    return Path(".")


class Hub:
    """장치 한 개를 한 번에 하나의 요청만 쓰게 묶는다."""

    def __init__(self, opener=P.Device, backup_dir=None, factory_dir=None):
        self.opener, self.backup_dir = opener, Path(backup_dir) if backup_dir else data_dir("backups")
        self.factory_dir = Path(factory_dir) if factory_dir else data_dir()
        self.dev, self.lock = None, threading.Lock()
        self.beat = None  # 마지막 heartbeat 의 monotonic 시각
        self.progress = {"n": 0, "total": 0, "running": False}
        self.measure = None  # 폴링레이트 측정기(처음 쓸 때 만든다)
        self.rate = {"running": False, "step": ""}  # PC 쪽 폴링레이트 변경 진행 상황
        self.rate_lock = threading.Lock()
        self.rate_pending = None  # 기한 안에 끝나지 않은 관리자 작업의 결과 파일 경로

    def measurer(self):
        if self.measure is None:
            from .rawinput import Measurer
            self.measure = Measurer()
        return self.measure

    def device(self):  # lock 을 잡은 채로 부른다
        if self.dev is None:
            self.dev = self.opener()
        return self.dev

    def drop(self):
        dev, self.dev = self.dev, None
        if dev is not None:
            try:
                dev.close()
            except OSError:
                pass

    def close(self):
        with self.lock:
            self.drop()


# ---------- 입력 검사 ----------
def _int(body, key, lo, hi):
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise MsgError("err.int_range", name=key, lo=lo, hi=hi)
    return v


def _num(body, key):
    v = body[key]
    lo, hi = MAG_RANGE[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise MsgError("err.mm_range", name=key, lo=lo, hi=hi)
    return round(v, 1)


def _magnet_args(body):
    kw = {k: _num(body, k) for k in MAG_NUM if body.get(k) is not None}
    if body.get("rt") is not None:
        if not isinstance(body["rt"], bool):
            raise MsgError("err.bool", name="rt")
        kw["rt"] = body["rt"]
    if not kw:
        raise MsgError("err.no_change")
    return kw


def _mag_ok(got, kw):
    if "rt" in kw and got["rt"] != kw["rt"]:
        return False
    return all(abs(got[k] - v) < 0.06 for k, v in kw.items()
               if k in MAG_NUM and (got["rt"] or not k.startswith("rt_")))


def _magnet_out(m):
    return {k: m[k] for k in (*MAG_NUM, "rt")}


def _split(raw):
    return [list(raw[i:i + 4]) for i in range(0, len(raw), 4)]


def _factory_path(hub, dev):
    did = dev.device_id()
    return None if did is None else hub.factory_dir / ("factory_%d.json" % did)


def _factory_load(hub, dev):
    """첫 연결 때 저장해 둔 키맵·Fn 스냅샷(없거나 깨졌으면 None)."""
    path = _factory_path(hub, dev)
    try:
        with open(path, encoding="utf-8") as f:
            snap = json.load(f)
        for kind in ("keymap", "fn"):
            for l in range(P.LAYERS):
                if len(bytes.fromhex(snap[kind][str(l)])) != 4 * P.KEYS:
                    return None
        return snap
    except (OSError, TypeError, ValueError, KeyError):
        return None


def _factory_ensure(hub, dev, keymap, fn):
    """스냅샷이 없으면 지금 읽은 값을 저장한다(장치에는 쓰지 않는다). 스냅샷이 있으면 True."""
    if _factory_load(hub, dev) is not None:
        return True
    path = _factory_path(hub, dev)
    if path is None:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"keymap": {str(l): v.hex() for l, v in keymap.items()},
                       "fn": {str(l): v.hex() for l, v in fn.items()}}, f)
    except OSError:
        return False
    return True


def _key_idx(body):
    idx = _int(body, "idx", 0, 127)
    if idx not in P.DEFAULT_HID:
        raise MsgError("err.key_locked")
    return _int(body, "layer", 0, P.LAYERS - 1), idx


def _light_args(body, effects):
    rgb = body.get("rgb")
    if not isinstance(rgb, list) or len(rgb) != 3:
        raise MsgError("err.rgb")
    rgb = tuple(_int({"c": c}, "c", 0, 255) for c in rgb)
    effect = _int(body, "effect", 0, 255)
    if effect not in effects:
        raise MsgError("err.effect", effect=effect)
    return (effect, _int(body, "speed", 0, P.MAXSPEED), _int(body, "bright", 0, P.BRIGHT_MAX),
            _int(body, "option", 0, 15), rgb, bool(body.get("dazzle")))


def _light_result(got, want, side=False):
    exp = P.light_expect(*want, side=side)
    ok = bool(got) and all(got[k] == exp[k] for k in ("effect", "speed", "bright", "option", "rgb", "dazzle"))
    return {"applied": ok, "light" if not side else "sidelight": got}


# ---------- API 핸들러: (hub, dev, body) -> dict ----------
def h_state(hub, dev, body):
    t = {k: dev.get_magnet(k) for k in (P.M_TRAVEL, P.M_LIFT, P.M_DEAD, P.M_MODE, P.M_RT_PRESS, P.M_RT_LIFT)}
    magnet = {i: {"travel": P.byte_to_mm(t[P.M_TRAVEL][i]), "lift": P.byte_to_mm(t[P.M_LIFT][i]),
                  "dead": P.byte_to_dead(t[P.M_DEAD][i]), "rt": bool(t[P.M_MODE][i] & P.M_RT_FLAG),
                  "rt_press": P.byte_to_mm(t[P.M_RT_PRESS][i]), "rt_lift": P.byte_to_mm(t[P.M_RT_LIFT][i])}
              for i in range(P.KEYS)}
    keymap = {l: dev.get_keymatrix(l) for l in range(P.LAYERS)}
    fn = {l: dev.get_fn(l) for l in range(P.LAYERS)}
    return {"device": {"id": dev.device_id(), "revision": dev.revision()},
            "usb": _usb(),  # 재연결 뒤 값이 바뀌므로 캐시하지 않는다
            "profile": dev.get_profile(), "debounce": dev.get_debounce(), "sleep": dev.get_sleep(),
            "light": dev.get_light(), "sidelight": dev.get_sidelight(),
            "options": (lambda r: P.decode_options(r) if r else None)(dev.get_options()),
            "keymap": {l: _split(v) for l, v in keymap.items()},
            "fn": {l: _split(v) for l, v in fn.items()}, "magnet": magnet,
            "factory": _factory_ensure(hub, dev, keymap, fn),
            "meta": {"hid_names": P.HID_NAMES, "default_hid": P.DEFAULT_HID, "effects": P.EFFECTS,
                     "presets": P.PRESET_COLORS, "keys": P.KEYS, "layers": P.LAYERS,
                     "side_effects": P.SIDE_EFFECTS}}


def h_profile(hub, dev, body):
    want = _int(body, "layer", 0, P.LAYERS - 1)
    got = dev.set_profile(want)
    return {"applied": got == want, "profile": got}


def h_debounce(hub, dev, body):
    want = _int(body, "ms", 0, 20)
    got = dev.set_debounce(want)
    return {"applied": got == want, "debounce": got}


def h_light(hub, dev, body):
    want = _light_args(body, P.EFFECTS)
    return _light_result(dev.set_light(*want), want)


def h_sidelight(hub, dev, body):
    want = _light_args(body, P.SIDE_EFFECTS)
    return _light_result(dev.set_sidelight(*want), want, side=True)


def h_options(hub, dev, body):
    if not body:
        raise MsgError("err.no_change")
    raw = dev.set_options(**body)
    got = P.decode_options(raw) if raw else None
    return {"applied": bool(got) and all(got[k] == v for k, v in body.items()), "options": got}


def _item_label(item):
    if P.hid_of(item) is not None:
        return P.item_name(item)
    return t("key.none") if not any(item) else t("key.special", hex=" ".join("%02x" % x for x in item))


def _tr_usb(u):
    """usbinfo.read() 결과의 오류 키를 요청 언어로 바꾼다."""
    if "error" in u:
        u = {k: v for k, v in u.items() if k != "error_params"} | {"error": t(u["error"], **u.get("error_params", {}))}
    return u


def _usb():
    return _tr_usb(usbinfo.read())


def _driver_state():
    st = ratectl.driver_state()
    m = st.pop("device_error_msg", None)
    if m:
        st["device_error"] = i18n.msg(i18n.from_json(m))
    return st


def _admin_out(res):
    """관리자 작업 결과의 error·detail 을 요청 언어로 바꾸고 번역용 키는 뺀다."""
    out = {k: v for k, v in res.items() if k != "error_msg"}
    if res.get("error_msg"):
        out["error"] = i18n.msg(i18n.from_json(res["error_msg"]))
    out["ops"] = [{**{k: v for k, v in o.items() if k != "detail_msg"},
                   **({"detail": i18n.msg(i18n.from_json(o["detail_msg"]))} if o.get("detail_msg") else {})}
                  for o in res.get("ops", [])]
    return out


def _write_key(hub, dev, setter, body, kind):
    layer, idx = _key_idx(body)
    if body.get("default") is True:
        snap = _factory_load(hub, dev)
        if snap is None:
            raise MsgError("err.no_factory")
        item = bytes.fromhex(snap[kind][str(layer)])[idx * 4:idx * 4 + 4]
    else:
        hid = _int(body, "hid", 0, 255)
        item = P.key_item(hid) if hid else bytes(4)
    got = setter(layer, idx, item)
    return {"applied": got == item, "item": list(got), "name": _item_label(got)}


def h_key(hub, dev, body):
    return _write_key(hub, dev, dev.set_key, body, "keymap")


def h_fn(hub, dev, body):
    return _write_key(hub, dev, dev.set_fn, body, "fn")


def h_magnet(hub, dev, body):
    idx = _int(body, "idx", 0, P.KEYS - 1)
    kw = _magnet_args(body)
    got = dev.set_magnet(idx, **kw)
    return {"applied": _mag_ok(got, kw), "idx": idx, "magnet": _magnet_out(got)}


def h_magnet_all(hub, dev, body):
    kw = _magnet_args(body)
    hub.progress = {"n": 0, "total": P.KEYS, "running": True}
    bad = []
    try:
        for i in range(P.KEYS):
            if not _mag_ok(dev.set_magnet(i, **kw), kw):
                bad.append(i)
            hub.progress["n"] = i + 1
    finally:
        hub.progress["running"] = False
    return {"applied": not bad, "failed": bad, "magnet": kw}


def h_progress(hub, dev, body):
    return dict(hub.progress)


def h_backup(hub, dev, body):
    allp = body.get("all_profiles", False)
    if not isinstance(allp, bool):
        raise MsgError("err.bool", name="all_profiles")
    name = "backup_%s.json" % time.strftime("%Y%m%d_%H%M%S")
    with open(hub.backup_dir / name, "w", encoding="utf-8") as f:
        json.dump(P.dump(dev, all_profiles=allp), f, ensure_ascii=False, indent=1)
    return {"applied": True, "name": name}


def h_restore(hub, dev, body):
    name = body.get("file")
    if not isinstance(name, str) or name != Path(name).name or not fnmatch.fnmatch(name, "backup_*.json"):
        raise MsgError("err.backup_name")
    try:
        with open(hub.backup_dir / name, encoding="utf-8") as f:
            backup = json.load(f)
    except OSError as e:  # 파일 문제를 장치 통신 오류(503)로 오해하지 않게 한다
        raise MsgError("err.backup_open", reason=e)
    try:
        skipped = P.restore(dev, backup)
    except P.RestoreError as e:
        if isinstance(e.__cause__, OSError):
            hub.drop()  # 장치 통신이 끊겼을 수 있으니 다음 요청에서 다시 연결한다
        return {"applied": False, "partial": True, "skipped": [], "diff": [], "message": i18n.msg(e)}
    diff = P.diff_backup(backup, P.dump(dev, all_profiles=len(backup["magnet"]) > 1))
    return {"applied": not diff, "skipped": skipped, "diff": diff}


def h_backups(hub, dev, body):
    files = sorted(hub.backup_dir.glob("backup_*.json"), reverse=True)
    return {"backups": [{"name": f.name, "size": f.stat().st_size,
                         "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.stat().st_mtime))}
                        for f in files]}


def h_measure_start(hub, dev, body):
    seconds = _int({"s": body.get("seconds", 10)}, "s", 3, 60)
    hub.measurer().start(seconds)
    return {"started": True, "seconds": seconds}


def h_measure_status(hub, dev, body):
    st = hub.measurer().status()
    r = st.get("result")
    if r and r.get("note"):
        st = {**st, "result": {**r, "note": t(r["note"])}}
    return st


def h_usbinfo(hub, dev, body):
    return _usb()


def _rate_job(hub, step, fn):
    """폴링레이트 작업은 한 번에 하나만 돌린다. 진행 문구는 /api/rate/progress 로 읽는다."""
    if not hub.rate_lock.acquire(blocking=False):
        raise MsgError("err.rate_busy")
    hub.rate = {"running": True, "step": step}
    try:
        if ratectl.admin_pending(hub.rate_pending):
            raise MsgError("err.admin_busy")
        hub.rate_pending = None
        return fn()
    finally:
        hub.rate["running"] = False
        hub.rate_lock.release()


def _rate_apply(hub, hz):
    def go():
        ops = ratectl.plan_set(hz)
        with hub.lock:
            hub.drop()  # 장치를 재시작하면 열어 둔 핸들이 무효가 된다
            if ops:
                hub.rate["step"] = "rate.step.admin"
                res = ratectl.run_admin(ops)
                hub.rate_pending = res.get("pending")
                hub.rate["step"] = "rate.step.wait"
                usb = ratectl.reread_usb()
            else:
                res, usb = {"ok": True, "ops": []}, usbinfo.read()
        got = usb.get("max_hz") if "error" not in usb else None
        admin = _admin_out(res)
        return {"applied": bool(res.get("ok")), "requested": hz, "message": admin.get("error", ""), "admin": admin,
                "reboot_needed": ratectl.needs_reboot(res), "usb": _tr_usb(usb), "verified": None if got is None else got == hz, "state": _driver_state()}
    return _rate_job(hub, "rate.step.preparing", go)


def h_rate_state(hub, dev, body):
    return {"state": _driver_state(), "usb": _usb(), "table": ratectl.RATE_TABLE}


def h_rate_prepare(hub, dev, body):
    def go():
        info = ratectl.prepare()
        return {"prepared": True, "nopatch": info["nopatch"], "signer": info["signer"], "state": _driver_state()}
    return _rate_job(hub, "rate.step.download", go)


def h_rate_set(hub, dev, body):
    hz = _int(body, "hz", 1, 100000)
    if hz not in ratectl.RATE_TABLE:
        raise MsgError("err.hz_choice", list=sorted(ratectl.RATE_TABLE, reverse=True))
    return _rate_apply(hub, hz)


def h_rate_reset(hub, dev, body):
    return _rate_apply(hub, 8000)


def h_rate_progress(hub, dev, body):
    return {**hub.rate, "step": t(hub.rate["step"])}


def h_heartbeat(hub, dev, body):
    """연결 여부는 장치 쓰기 중이 아닐 때만 가볍게 읽어(프로필) 확인한다."""
    hub.beat = time.monotonic()
    if not hub.lock.acquire(blocking=False):
        return {"connected": hub.dev is not None}
    try:
        profile = hub.device().get_profile()
        return {"connected": True, "profile": profile}
    except OSError:
        hub.drop()
        return {"connected": False}
    finally:
        hub.lock.release()


# 경로 -> (핸들러, 장치 필요 여부)
ROUTES = {("GET", "/api/state"): (h_state, True), ("POST", "/api/profile"): (h_profile, True),
          ("POST", "/api/debounce"): (h_debounce, True), ("POST", "/api/light"): (h_light, True),
          ("POST", "/api/sidelight"): (h_sidelight, True), ("POST", "/api/key"): (h_key, True),
          ("POST", "/api/options"): (h_options, True), ("POST", "/api/restore"): (h_restore, True),
          ("POST", "/api/measure/start"): (h_measure_start, False),
          ("GET", "/api/measure/status"): (h_measure_status, False),
          ("POST", "/api/fn"): (h_fn, True), ("POST", "/api/magnet"): (h_magnet, True),
          ("POST", "/api/magnet_all"): (h_magnet_all, True), ("GET", "/api/progress"): (h_progress, False),
          ("POST", "/api/backup"): (h_backup, True), ("GET", "/api/backups"): (h_backups, False),
          ("GET", "/api/heartbeat"): (h_heartbeat, False),
          ("GET", "/api/usbinfo"): (h_usbinfo, False),
          ("GET", "/api/rate/state"): (h_rate_state, False), ("POST", "/api/rate/prepare"): (h_rate_prepare, False),
          ("POST", "/api/rate/set"): (h_rate_set, False), ("POST", "/api/rate/reset"): (h_rate_reset, False),
          ("GET", "/api/rate/progress"): (h_rate_progress, False)}


def handle(hub, method, path, body=None, lang=None):
    """-> (HTTP 상태, 응답 dict). 소켓과 무관해서 단위 테스트에서 바로 부른다. lang = X-Lang 값(기본 ko)."""
    with i18n.use(lang):
        return _handle(hub, method, path, body)


def _handle(hub, method, path, body):
    route = ROUTES.get((method, path))
    if route is None:
        return 404, {"ok": False, "error": t("err.not_found", path=path)}
    fn, needs_dev = route
    body = body if body is not None else {}
    try:
        if not needs_dev:
            return 200, {"ok": True, **fn(hub, None, body)}
        with hub.lock:
            try:
                return 200, {"ok": True, **fn(hub, hub.device(), body)}
            except OSError:
                hub.drop()  # 다음 요청에서 다시 연결을 시도한다
                raise
    except NotImplementedError as e:
        return 501, {"ok": False, "error": str(e)}
    except ValueError as e:
        return 400, {"ok": False, "error": i18n.msg(e)}
    except OSError as e:
        return 503, {"ok": False, "connected": False, "error": t("err.device", reason=e)}
    except Exception as e:  # 예기치 못한 오류도 화면에 그대로 보여 준다
        return 500, {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}


def json_content_type(value):
    """application/json 만 허용한다(뒤에는 charset 파라미터만 올 수 있다)."""
    mime, *params = [x.strip().lower() for x in value.split(";")]
    return mime == "application/json" and all(x.startswith("charset=") for x in params)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, data, ctype="application/json"):
        if isinstance(data, dict):
            data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _host_ok(self):  # 다른 사이트가 DNS 로 이 서버를 가리켜 장치를 쓰는 것을 막는다
        return self.headers.get("Host", "").split(":")[0] in ("127.0.0.1", "localhost")

    def _api(self, method, body):
        path = urlparse(self.path).path
        self._send(*handle(self.server.hub, method, path, body, self.headers.get("X-Lang")))

    def _deny(self, status, key):
        with i18n.use(self.headers.get("X-Lang")):
            self._send(status, {"ok": False, "error": t(key)})

    def do_GET(self):
        if not self._host_ok():
            return self._deny(403, "err.host")
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            return self._api("GET", None)
        f = (WEB / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
        if WEB.resolve() not in f.parents or not f.is_file():
            return self._send(404, b"not found", "text/plain")
        self._send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))

    def do_POST(self):
        # application/json 만 받는다: 다른 사이트의 단순 폼 POST 로는 장치를 쓸 수 없다
        if not self._host_ok() or not json_content_type(self.headers.get("Content-Type", "")):
            return self._deny(403, "err.request")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self._deny(400, "err.body")
        self._api("POST", body)


def make_server(hub, port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.hub = hub
    srv.daemon_threads = True
    return srv
