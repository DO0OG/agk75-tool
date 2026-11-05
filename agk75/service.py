"""장치·백업·폴링레이트 로직. 화면과 무관한 일반 메서드로만 이루어지며 표준 라이브러리만 쓴다."""
import fnmatch
import json
import os
import threading
import time
from pathlib import Path

from . import i18n
from . import protocol as P
from .i18n import MsgError, t

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


class Service:
    """장치 한 개를 한 번에 하나의 작업만 쓰게 묶고, 화면이 부르는 작업을 메서드로 내놓는다."""

    def __init__(self, opener=P.Device, backup_dir=None, factory_dir=None):
        self.opener, self.backup_dir = opener, Path(backup_dir) if backup_dir else data_dir("backups")
        self.factory_dir = Path(factory_dir) if factory_dir else data_dir()
        self.dev, self.lock = None, threading.Lock()
        self.progress = {"n": 0, "total": 0, "running": False}
        self.on_progress = None  # (n, total) 를 받는 함수: 전체 적용 진행 알림
        self.measure = None  # 폴링레이트 측정기(처음 쓸 때 만든다)

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

    def _call(self, fn, body, needs_dev=True):
        if not needs_dev:
            return fn(self, None, body)
        with self.lock:
            try:
                return fn(self, self.device(), body)
            except OSError:
                self.drop()  # 다음 작업에서 다시 연결을 시도한다
                raise

    # ---- 장치 읽기·쓰기(모두 입력을 검사하고 되읽어 판정한다) ----
    def state(self):
        return self._call(h_state, {})

    def profile(self, **body):
        return self._call(h_profile, body)

    def debounce(self, **body):
        return self._call(h_debounce, body)

    def light(self, **body):
        return self._call(h_light, body)

    def sidelight(self, **body):
        return self._call(h_sidelight, body)

    def key(self, **body):
        return self._call(h_key, body)

    def fn(self, **body):
        return self._call(h_fn, body)

    def rate(self, **body):
        return self._call(h_rate, body)

    def rate_read(self):
        return self._call(h_rate_read, {})

    def options(self, **body):
        return self._call(h_options, body)

    def magnet(self, **body):
        return self._call(h_magnet, body)

    def magnet_all(self, **body):
        return self._call(h_magnet_all, body)

    def backup(self, **body):
        return self._call(h_backup, body)

    def restore(self, **body):
        return self._call(h_restore, body)

    # ---- 장치가 필요 없는 작업 ----
    def backups(self):
        return self._call(h_backups, {}, False)

    def measure_start(self, **body):
        return self._call(h_measure_start, body, False)

    def measure_status(self):
        return self._call(h_measure_status, {}, False)

    def poll(self):
        """연결 여부는 장치 쓰기 중이 아닐 때만 가볍게 읽어(프로필) 확인한다."""
        if not self.lock.acquire(blocking=False):
            return {"connected": self.dev is not None}
        try:
            return {"connected": True, "profile": self.device().get_profile()}
        except OSError:
            self.drop()
            return {"connected": False}
        finally:
            self.lock.release()


def describe_error(exc):
    """작업 중 올라온 예외 -> 하단 토스트에 보여 줄 현재 언어 문구."""
    if isinstance(exc, NotImplementedError):
        return str(exc)
    if isinstance(exc, ValueError):
        return i18n.msg(exc)
    if isinstance(exc, OSError):
        return t("err.device", reason=exc)
    return "%s: %s" % (type(exc).__name__, exc)


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


# ---------- 작업 본체: (service, dev, body) -> dict ----------
def h_state(hub, dev, body):
    t = {k: dev.get_magnet(k) for k in (P.M_TRAVEL, P.M_LIFT, P.M_DEAD, P.M_MODE, P.M_RT_PRESS, P.M_RT_LIFT)}
    magnet = {i: {"travel": P.byte_to_mm(t[P.M_TRAVEL][i]), "lift": P.byte_to_mm(t[P.M_LIFT][i]),
                  "dead": P.byte_to_dead(t[P.M_DEAD][i]), "rt": bool(t[P.M_MODE][i] & P.M_RT_FLAG),
                  "rt_press": P.byte_to_mm(t[P.M_RT_PRESS][i]), "rt_lift": P.byte_to_mm(t[P.M_RT_LIFT][i])}
              for i in range(P.KEYS)}
    keymap = {l: dev.get_keymatrix(l) for l in range(P.LAYERS)}
    fn = {l: dev.get_fn(l) for l in range(P.LAYERS)}
    profile = dev.get_profile()
    return {"device": {"id": dev.device_id(), "revision": dev.revision()},
            "profile": profile, "rate": None if profile is None else dev.get_rate(profile), "debounce": dev.get_debounce(), "sleep": dev.get_sleep(),
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
    return {"applied": got == want, "profile": got, "rate": None if got is None else dev.get_rate(got)}


def h_rate_read(hub, dev, body):
    profile = dev.get_profile()
    return {"profile": profile, "rate": None if profile is None else dev.get_rate(profile)}


def h_rate(hub, dev, body):
    want = _int(body, "hz", 1, 100000)
    if want not in P.RATE_CODES:
        raise MsgError("err.hz_choice", list=sorted(P.RATE_CODES, reverse=True))
    profile = dev.get_profile()
    if profile is None:
        raise OSError("Could not read the current profile")
    got = dev.set_rate(want, profile)
    return {"applied": got == want, "profile": profile, "rate": got}


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
            if hub.on_progress:
                hub.on_progress(i + 1, P.KEYS)
    finally:
        hub.progress["running"] = False
    return {"applied": not bad, "failed": bad, "magnet": kw}


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
    seconds = _int({"s": body.get("seconds", 15)}, "s", 3, 60)
    hub.measurer().start(seconds)
    return {"started": True, "seconds": seconds}


def h_measure_status(hub, dev, body):
    return hub.measurer().status()
