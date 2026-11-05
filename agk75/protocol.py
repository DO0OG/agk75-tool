"""AGK75 설정 채널: MI_02, 64바이트 Feature report.

아래 ALLOWED 밖의 opcode 는 보내지 않는다.
"""
import json
import time

from .i18n import Msg, MsgError

VID, PID = 0x3151, 0x5009
USAGE_PAGE, USAGE = 0xFFFF, 0x0002

# GET
G_REV, G_PROFILE, G_OPTION, G_LED, G_SLED, G_KEYMATRIX = 128, 133, 134, 135, 136, 137
G_ID, G_FN, G_DEBOUNCE, G_SLEEP, G_MAGNET, G_RATE = 143, 144, 145, 146, 229, 132
# SET
S_PROFILE, S_OPTION, S_LED, S_SLED, S_DEBOUNCE, S_KEY, S_FN, S_MAGNET = 5, 6, 7, 8, 17, 19, 21, 101
S_KEYMATRIX, S_FNMATRIX = 9, 16  # 복원 때만 쓰는 전체 키맵/Fn 청크 쓰기
S_RATE = 4
ALLOWED = {G_REV, G_PROFILE, G_OPTION, G_LED, G_SLED, G_KEYMATRIX, G_ID, G_FN, G_DEBOUNCE,
           G_SLEEP, G_MAGNET, G_RATE, S_PROFILE, S_OPTION, S_LED, S_SLED, S_DEBOUNCE, S_KEY, S_FN, S_MAGNET,
           S_KEYMATRIX, S_FNMATRIX, S_RATE}
# 폴링레이트 레지스터 값. 코드 6 은 주기가 없어 쓰지 않는다. 레지스터는 범위 밖 값도 저장하므로 쓰기 전에 검사한다.
# 2000·4000·8000Hz 는 1000Hz 보다 빠르다는 것만 확인했고 값 자체는 추정이다.
RATE_CODES = {8000: 0, 4000: 1, 2000: 2, 1000: 3, 500: 4, 250: 5}

EFFECTS = {0: "Off", 1: "AlwaysOn", 2: "Breath", 3: "Neon", 4: "Wave", 5: "Ripple",
           6: "Raindrop", 7: "Snake", 8: "Press", 9: "Converge", 10: "SineWave",
           11: "Kaleidoscope", 12: "LineWave", 14: "Laser", 15: "CircleWave", 16: "Dazzle",
           17: "RainDown", 18: "Meteor", 19: "PressOff", 20: "Music3", 21: "ScreenColor",
           22: "Music2", 23: "Train", 24: "FireWorks"}
SIDE_EFFECTS = {0: "Off", 1: "AlwaysOn", 2: "Breath", 3: "Neon", 4: "Wave", 5: "Snake",
                20: "Music3", 21: "ScreenColor", 22: "Music2"}
MAXSPEED, BRIGHT_MAX, DAZZLE, NORMAL = 4, 4, 8, 7
PRESET_COLORS = [(255, 0, 0), (255, 128, 0), (255, 255, 0), (0, 255, 0), (0, 255, 255),
                 (0, 0, 255), (255, 0, 255)]  # 모드 니블 0..6 은 이 색을 뜻한다
KEYS = 128  # 자기 축 값 표의 키 수(0.1mm 단위, 키당 1바이트)
# 자기 축 타입(GET 229 / SET 101 의 두 번째 바이트)
M_TRAVEL, M_LIFT, M_RT_PRESS, M_RT_LIFT, M_DYN, M_MT, M_DEAD, M_MODE = 0, 1, 2, 3, 4, 5, 6, 7
M_DKS_DATA = 10  # DKS 트리거 모드 표(키 128개 x 4칸 = 512바이트), 읽기 전용
M_RT_FLAG = 128  # M_MODE 바이트의 최상위 비트 = 래피드 트리거 켜짐
LAYERS = 4
MAG_ORDER = (7, 0, 1, 2, 3, 6, 4, 5, 9)  # 복원 때 쓰는 순서(모드 표가 먼저)

# 표준 HID 키보드 사용 코드 표(키 번호는 장치의 키맵 순서, 65번은 Fn 키 자체라 제외). 번호는 키맵/Fn/자기 축/조명 공통이다.
DEFAULT_HID = dict(map(int, p.split(":")) for p in (
    "0:41 1:53 2:43 3:57 4:225 5:224 6:58 7:30 8:20 9:4 10:100 12:59 13:31 14:26 15:22 16:29 "
    "17:227 18:60 19:32 20:8 21:7 22:27 23:226 24:61 25:33 26:21 27:9 28:6 30:62 31:34 32:23 "
    "33:10 34:25 36:63 37:35 38:28 39:11 40:5 41:44 42:64 43:36 44:24 45:13 46:17 48:65 49:37 "
    "50:12 51:14 52:16 54:66 55:38 56:18 57:15 58:54 60:67 61:39 62:19 63:51 64:55 66:68 67:45 "
    "68:47 69:52 70:56 71:228 72:69 73:46 74:48 75:50 76:229 77:80 78:76 79:42 80:49 81:40 82:82 "
    "83:81 84:74 85:77 86:75 87:78 89:79").split())


def checksum(b, n=7):
    return 255 - (sum(b[:n]) & 0xFF)


def encode(cmd, bit8=False):
    """cmd -> 64바이트 리포트. 일반은 b[7], 조명 SET 은 b[8] 에 체크섬."""
    b = bytearray(bytes(cmd)[:64].ljust(64, b"\0"))
    n = 8 if bit8 else 7
    b[n] = checksum(b, n)
    return bytes(b)


def decode_light(r, side=False):
    """GET 135/136 응답 -> dict. 순백(FFFFFF)은 장치에서 FAFFFA 로 오간다. 측면 조명은 속도 값이 그대로다.

    효과 20·22 는 무지개 여부를 모드 니블 0 으로, 그 밖은 8 로 판정한다. 본체 조명의 21·22 는 색 프리셋
    치환을 하지 않는다(측면 조명은 모두 치환).
    """
    rgb = (r[5], r[6], r[7])
    if rgb == (0xFA, 0xFF, 0xFA):
        rgb = (255, 255, 255)
    effect, mode = r[1], r[4] & 15
    if mode < len(PRESET_COLORS) and (side or effect not in (21, 22)):
        rgb = PRESET_COLORS[mode]
    return {"effect": effect, "speed": r[2] if side else MAXSPEED - r[2], "bright": r[3], "option": r[4] >> 4,
            "dazzle": mode == 0 if effect in (20, 22) else mode == DAZZLE, "mode": mode, "rgb": rgb}


def _light_mode(effect, option, dazzle, side):
    """조명 SET 의 byte 4(옵션 << 4 | 모드)."""
    if side and effect == 3:  # 측면 Neon
        return 8
    if effect == 21:
        return 0
    if effect in (20, 22):
        return option << 4 | (0 if dazzle else 4)
    return option << 4 | (DAZZLE if dazzle else NORMAL)


def _wire_rgb(rgb):
    return (0xFA, 0xFF, 0xFA) if tuple(rgb) == (255, 255, 255) else tuple(rgb)


def encode_light(effect, speed, bright, option, rgb, dazzle=False):
    """조명 SET 리포트(체크섬은 b[8])."""
    return encode([S_LED, effect, MAXSPEED - speed, bright, _light_mode(effect, option, dazzle, False),
                   *_wire_rgb(rgb)], bit8=True)


def encode_sidelight(effect, speed, bright, option, rgb, dazzle=False):
    """측면 조명 SET 리포트(체크섬은 b[8], 속도는 반전하지 않는다)."""
    return encode([S_SLED, effect, speed, bright, _light_mode(effect, option, dazzle, True),
                   *_wire_rgb(rgb)], bit8=True)


def light_expect(effect, speed, bright, option, rgb, dazzle=False, side=False):
    """이 값을 쓰면 장치가 되돌려 줘야 하는 값(되읽기 비교용)."""
    enc = (encode_sidelight if side else encode_light)(effect, speed, bright, option, rgb, dazzle)
    return decode_light(bytes([G_SLED if side else G_LED]) + enc[1:8], side)


KB_FLAGS = {"win_lock": 0, "mac": 1, "wasd_arrow": 3, "led_off": 4, "side_led_off": 5, "keyboard_lock": 7}


def decode_options(raw):
    """GET 134 응답의 B1..B5 -> dict(B2 비트, B3 b0 Fn 매트릭스, B4 절전)."""
    d = {k: bool(raw[1] >> b & 1) for k, b in KB_FLAGS.items()}
    return {**d, "fn_matrix": bool(raw[2] & 1), "power_save": raw[3] != 0}


def encode_options(raw, **change):
    """현재 raw(B1..B5)에서 바꿀 항목만 반영한 SET 명령. 해석되지 않는 비트는 그대로 둔다."""
    flags, fn, ps = raw[1], raw[2], raw[3]
    for k, v in change.items():
        if not isinstance(v, bool):
            raise MsgError("err.bool", name=k)
        if k in KB_FLAGS:
            flags = flags & ~(1 << KB_FLAGS[k]) | int(v) << KB_FLAGS[k]
        elif k == "fn_matrix":
            fn = fn & ~1 | int(v)
        elif k == "power_save":
            ps = int(v)
        else:
            raise MsgError("err.unknown_option", name=k)
    return bytes([S_OPTION, 0, flags, fn, ps])


def mm_to_byte(mm):
    """작동/해제/RT 거리(mm) -> 장치 값. 0.1mm 단위, 값+1 이 거리."""
    return max(0, round(mm * 10) - 1)


def byte_to_mm(b):
    return (b + 1) / 10


def dead_to_byte(mm):
    return max(0, 40 - round(mm * 10) - 1)


def byte_to_dead(b):
    return (40 - (b + 1)) / 10


def key_item(hid):
    return bytes([0, 0, hid, 0])


def hid_of(item):
    """4바이트 항목이 단순 키(0,0,hid,0)이면 hid, 아니면 None."""
    return item[2] if item[0] == 0 and item[1] == 0 and item[3] == 0 and item[2] else None


def _names():
    n = {i + 4: chr(65 + i) for i in range(26)}
    n.update({30 + i: str((i + 1) % 10) for i in range(10)})
    n.update({40: "Enter", 41: "Esc", 42: "Backspace", 43: "Tab", 44: "Space", 45: "-", 46: "=",
              47: "[", 48: "]", 49: "\\", 50: "ISO#", 51: ";", 52: "'", 53: "`", 54: ",", 55: ".", 56: "/",
              57: "CapsLock", 70: "PrtSc", 71: "ScrollLock", 72: "Pause", 73: "Insert",
              74: "Home", 75: "PageUp", 76: "Delete", 77: "End", 78: "PageDown", 79: "Right",
              80: "Left", 81: "Down", 82: "Up", 100: "ISO\\", 101: "Menu",
              224: "LCtrl", 225: "LShift", 226: "LAlt", 227: "LWin", 228: "RCtrl",
              229: "RShift", 230: "RAlt", 231: "RWin"})
    n.update({58 + i: "F%d" % (i + 1) for i in range(12)})
    return n


HID_NAMES = _names()


def item_name(item):
    h = hid_of(item)
    if h is not None:
        return HID_NAMES.get(h, "HID%d" % h)
    return "None" if not any(item) else "Special[" + " ".join("%02x" % x for x in item) + "]"


def check_int(name, v, lo, hi):
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise MsgError("err.int_range", name=name, lo=lo, hi=hi)
    return v


def check_mm(name, v, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo - 1e-9 <= v <= hi + 1e-9:
        raise MsgError("err.mm_range", name=name, lo=lo, hi=hi)
    return v


def check_light(effect, speed, bright, option, rgb, effects):
    if effect not in effects:
        raise MsgError("err.effect", effect=effect)
    check_int("speed", speed, 0, MAXSPEED)
    check_int("bright", bright, 0, BRIGHT_MAX)
    check_int("option", option, 0, 15)
    if not isinstance(rgb, (list, tuple)) or len(rgb) != 3:
        raise MsgError("err.rgb")
    for c in rgb:
        check_int("rgb", c, 0, 255)


def _light_key(d):
    return d["effect"], d["speed"], d["bright"], d["option"], tuple(d["rgb"]), d["dazzle"]


class Device:
    def __init__(self):
        import hid
        path = next((d["path"] for d in hid.enumerate(VID, PID)
                     if d["usage_page"] == USAGE_PAGE and d["usage"] == USAGE), None)
        if path is None:
            raise OSError("AGK75 (3151:5009) MI_02 not found")
        self.dev = hid.device()
        self.dev.open_path(path)
        self.log = []  # (보낸 hex, 받은 hex)

    def close(self):
        self.dev.close()

    def send(self, cmd, bit8=False, wait=0.02):
        if cmd[0] not in ALLOWED:
            raise ValueError("opcode not allowed: %r" % cmd[0])
        out = encode(cmd, bit8)
        n = self.dev.send_feature_report(b"\0" + out)
        if n is None or n < 0:
            raise OSError("Write to device failed (send_feature_report=%r)" % (n,))
        self.log.append((out.hex(), ""))
        time.sleep(wait)

    def xfer(self, cmd, bit8=False):
        self.send(cmd, bit8)
        resp = bytes(self.dev.get_feature_report(0, 65)[1:])
        self.log[-1] = (self.log[-1][0], resp.hex())
        return resp

    def get(self, op, *args):
        """GET 응답의 첫 바이트가 opcode 와 다르면(장치가 바빠 이전 응답이 남은 경우) 잠시 뒤 다시 읽는다."""
        for _ in range(4):
            r = self.xfer(bytes([op, *args]))
            if r[:1] == bytes([op]):
                return r
            time.sleep(0.2)
        return None

    # ---- 단순 값 ----
    def device_id(self):
        r = self.get(G_ID)
        return int.from_bytes(r[1:5], "little") if r else None

    def revision(self):
        r = self.get(G_REV)
        return (r[2] << 8 | r[1]) if r else None

    def get_profile(self):
        r = self.get(G_PROFILE)
        return r[1] // 4 if r else None

    def set_profile(self, layer):
        check_int("layer", layer, 0, LAYERS - 1)
        self.send(bytes([S_PROFILE, layer * 4]), wait=0.3)
        return self.get_profile()

    def select_profile(self, layer):
        """프로필을 고르고 되읽어 확인한다(늦게 반영되면 기다리고, 그래도 다르면 1회 재전송).
        끝내 다르면 OSError(더 쓰지 않도록 호출자가 중단한다)."""
        for _ in range(2):
            self.set_profile(layer)
            got = self._settle(self.get_profile, layer, 4)
            if got == layer:
                return
        raise OSError("Could not switch to profile %d (current %r)" % (layer, got))

    def get_debounce(self):
        r = self.get(G_DEBOUNCE)
        return r[2] if r else None

    def set_debounce(self, ms):
        check_int("ms", ms, 0, 255)
        self.send(bytes([S_DEBOUNCE, 0, ms]), wait=0.3)
        return self.get_debounce()

    def get_rate(self, profile=0):
        """프로필의 폴링레이트(Hz). 코드가 표 밖이면 None."""
        check_int("profile", profile, 0, LAYERS - 1)
        r = self.get(G_RATE, profile)
        return next((hz for hz, c in RATE_CODES.items() if r and c == r[2]), None)

    def set_rate(self, hz, profile=0):
        """폴링레이트를 쓰고 반영될 때까지 되읽어 마지막으로 읽은 값(Hz)을 돌려준다."""
        if type(hz) is not int or hz not in RATE_CODES:
            raise MsgError("err.hz_choice", list=sorted(RATE_CODES, reverse=True))
        check_int("profile", profile, 0, LAYERS - 1)
        self.send(bytes([S_RATE, profile, RATE_CODES[hz]]), wait=0.3)
        return self._settle(lambda: self.get_rate(profile), hz)

    def get_sleep(self):
        r = self.get(G_SLEEP)
        return [r[i + 1] | r[i + 2] << 8 for i in (0, 2, 4, 6)] if r else None

    def get_options(self):
        """B1..B5(5바이트). 프로필 인자는 항상 0 을 쓴다."""
        r = self.get(G_OPTION, 0)
        return r[1:6] if r else None

    def set_options(self, **change):
        """바꿀 항목만 반영한다(해석되지 않는 비트는 보존). 되읽은 raw 를 돌려준다."""
        encode_options(bytes(5), **change)  # 읽기 전에 인자부터 검사
        raw = self.get_options()
        if raw is None:
            raise OSError("Could not read the options")
        return self._write_options(encode_options(raw, **change), raw)

    def _write_options(self, cmd, raw):
        self.send(cmd, wait=0.3)
        want = bytes([raw[0], cmd[2], cmd[3], cmd[4], raw[4]])
        return self._settle(self.get_options, want)

    def get_light(self):
        r = self.get(G_LED)
        return decode_light(r) if r else None

    def get_sidelight(self):
        r = self.get(G_SLED)
        return decode_light(r, True) if r else None

    def _write_light(self, cmd, read, want):
        """조명류를 쓰고, 장치가 반영할 때까지(최대 약 4초) 되읽어 마지막 읽은 값을 돌려준다."""
        want = _light_key(want)
        for _ in range(2):  # 바쁠 때 보낸 패킷은 무시되거나 다른 값으로 들어갈 수 있어 불일치면 1회 재전송
            self.send(cmd, bit8=True, wait=1.0)
            for _ in range(8):
                r = read()
                if r and _light_key(r) == want:
                    return r
                time.sleep(0.4)
        return r

    def set_light(self, effect, speed, bright, option, rgb, dazzle=False):
        check_light(effect, speed, bright, option, rgb, EFFECTS)
        return self._write_light(encode_light(effect, speed, bright, option, rgb, dazzle), self.get_light,
                                 light_expect(effect, speed, bright, option, rgb, dazzle))

    def set_sidelight(self, effect, speed, bright, option, rgb, dazzle=False):
        check_light(effect, speed, bright, option, rgb, SIDE_EFFECTS)
        return self._write_light(encode_sidelight(effect, speed, bright, option, rgb, dazzle), self.get_sidelight,
                                 light_expect(effect, speed, bright, option, rgb, dazzle, side=True))

    # ---- 키맵 / Fn: 4바이트 x 128키, 청크 8개(응답에 헤더 없음) ----
    @staticmethod
    def _stable(read):
        """응답에 이전 응답이 섞이는 일이 있어, 연속 두 번 같은 값이 나올 때까지 읽는다."""
        got = read()
        for _ in range(5):
            again = read()
            if again == got:
                break
            got = again
        return got

    def get_keymatrix(self, layer, sub=0):
        return self._stable(lambda: b"".join(self.xfer(bytes([G_KEYMATRIX, layer * 4 + sub, i])) for i in range(8)))

    def get_fn(self, layer):
        return self._stable(lambda: b"".join(self.xfer(bytes([G_FN, layer, i])) for i in range(8)))

    def _settle(self, read, want, tries=8):
        for _ in range(tries):
            got = read()
            if got == want:
                break
            time.sleep(0.4)
        return got

    @staticmethod
    def _check_key(layer, idx, item, sub=0):
        check_int("layer", layer, 0, LAYERS - 1)
        check_int("idx", idx, 0, 127)
        check_int("sub", sub, 0, 3)
        if len(item) != 4:
            raise ValueError("item must be 4 bytes")
        for x in item:
            check_int("item", x, 0, 255)

    def set_key(self, layer, idx, item, sub=0):
        """키 하나의 4바이트 항목을 쓰고, 반영될 때까지 되읽어 마지막 읽은 항목을 돌려준다."""
        self._check_key(layer, idx, item, sub)
        self.send(bytes([S_KEY, layer * 4 + sub, idx, 0, 0, 0, 0, 0, *item]), wait=0.5)
        return self._settle(lambda: self.get_keymatrix(layer, sub)[idx * 4:idx * 4 + 4], bytes(item))

    def set_fn(self, layer, idx, item):
        self._check_key(layer, idx, item)
        self.send(bytes([S_FN, layer, idx, 0, 0, 0, 0, 0, *item]), wait=0.5)
        return self._settle(lambda: self.get_fn(layer)[idx * 4:idx * 4 + 4], bytes(item))

    def write_keymap(self, layer, sub, data):
        """키맵 한 장을 다른 항목만 키별(S_KEY)로 쓴다. 청크 쓰기(S_KEYMATRIX)는 sel 을 무시하고 현재 프로필의
        서브 0 에만 써지므로(실기기 확인) 쓰지 않는다. 키 126, 127 은 다른 쓰기 경로와 같이 건드리지 않는다."""
        have = self.get_keymatrix(layer, sub)
        for idx in range(126):
            item = bytes(data[idx * 4:idx * 4 + 4])
            if have[idx * 4:idx * 4 + 4] != item and self.set_key(layer, idx, item, sub) != item:
                raise OSError("Keymap %d.%d key %d was not applied by the device" % (layer, sub, idx))

    def write_matrix(self, op, sel, data):
        """Fn 매트릭스(S_FNMATRIX, sel=레이어) 전체를 56바이트 청크 9개로 쓴다."""
        if op != S_FNMATRIX or len(data) < 9 * 56:
            raise ValueError("invalid matrix write arguments")
        want = bytes(data[:504])
        for _ in range(2):  # 장치는 마지막 청크 뒤 몇 초 동안 저장 중이라, 반영될 때까지 기다린 뒤 다음 쓰기로 넘어간다
            for k in range(9):
                self.send(bytes([op, sel, 248, 1, k, 0, 0, 0]) + bytes(data[k * 56:(k + 1) * 56]))
            time.sleep(1.5)
            if self._settle(lambda: self.get_fn(sel)[:504], want, 10) == want:
                return
        raise OSError("Matrix write (opcode %d, sel %d) was not applied by the device" % (op, sel))

    # ---- 자기 축 ----
    def get_magnet(self, typ, n=KEYS):
        """타입 typ 의 값 n개(기본: 키별 바이트 128개; DKS 표는 n=512)."""
        raw = b"".join(self.xfer(bytes([G_MAGNET, typ, 1, i])) for i in range(-(-n // 64)))
        return list(raw[:n])

    def set_magnet_key(self, idx, ops):
        """ops: [(타입, [바이트...])...]. 마지막 명령에만 '끝' 플래그를 세운다."""
        check_int("idx", idx, 0, KEYS - 1)
        for i, (typ, data) in enumerate(ops):
            self.send(bytes([S_MAGNET, typ, 0, idx, int(i == len(ops) - 1), 0, 0, 0, *data]))
        time.sleep(0.5)

    def write_magnet_all(self, types):
        """types: {타입: 값 128개, 10: DKS 표 512개}. 타입 순서는 MAG_ORDER 이고 마지막 패킷에만 '끝' 플래그를 세운다."""
        for pk in magnet_packets(types):
            self.send(bytes(pk))
        time.sleep(0.5)

    def magnet_key(self, idx):
        """키 하나의 자기 축 설정을 dict 로(거리는 mm, raw 는 장치 값)."""
        raw = {t: self.get_magnet(t)[idx] for t in (M_TRAVEL, M_LIFT, M_DEAD, M_MODE,
                                                    M_RT_PRESS, M_RT_LIFT)}
        return {"travel": byte_to_mm(raw[M_TRAVEL]), "lift": byte_to_mm(raw[M_LIFT]),
                "dead": byte_to_dead(raw[M_DEAD]), "rt": bool(raw[M_MODE] & M_RT_FLAG),
                "rt_press": byte_to_mm(raw[M_RT_PRESS]), "rt_lift": byte_to_mm(raw[M_RT_LIFT]),
                "raw": raw}

    def set_magnet(self, idx, travel=None, lift=None, dead=None, rt=None,
                   rt_press=None, rt_lift=None):
        """주어진 항목만 쓰고(거리 mm), 반영될 때까지 되읽은 설정을 돌려준다."""
        check_int("idx", idx, 0, KEYS - 1)
        for name, v in (("travel", travel), ("lift", lift), ("rt_press", rt_press), ("rt_lift", rt_lift)):
            if v is not None:
                check_mm(name, v, 0.1, 4.0)
        if dead is not None:
            check_mm("dead", dead, 0.0, 3.9)
        cur = self.magnet_key(idx)
        ops = []
        if rt is not None and rt != cur["rt"]:
            ops.append((M_MODE, [(cur["raw"][M_MODE] & 127) | (M_RT_FLAG if rt else 0)]))
        for typ, val, conv in ((M_TRAVEL, travel, mm_to_byte), (M_LIFT, lift, mm_to_byte),
                               (M_DEAD, dead, dead_to_byte), (M_RT_PRESS, rt_press, mm_to_byte),
                               (M_RT_LIFT, rt_lift, mm_to_byte)):
            if val is not None:
                ops.append((typ, [conv(val)]))
        if not ops:
            return cur
        self.set_magnet_key(idx, ops)
        want = {t: v[0] for t, v in ops}
        for _ in range(6):
            now = self.magnet_key(idx)
            if all(now["raw"][t] == v for t, v in want.items()):
                break
            time.sleep(0.4)
        return now


def magnet_packets(types):
    """자기 축 전체 쓰기 패킷 목록(타입 순서는 MAG_ORDER, DKS 는 마지막에 타입 8 을 키마다 한 개)."""
    pk, dks = [], []
    for typ in MAG_ORDER:
        if typ not in types:
            continue
        data = bytes(types[typ])
        if len(data) != KEYS:
            raise ValueError("magnetic type %d needs %d values" % (typ, KEYS))
        for k in range(-(-KEYS // 56)):
            pk.append([S_MAGNET, typ, 1, k, 0, 0, 0, 0, *data[k * 56:(k + 1) * 56]])
        if typ == M_MODE:
            dks = [i for i, v in enumerate(data) if v & 127 == 2]
    if dks:
        table = bytes(types.get(M_DKS_DATA, ()))
        if len(table) != 4 * KEYS:
            raise ValueError("DKS keys present but the DKS table (type 10) is missing")
        pk += [[S_MAGNET, 8, 0, i, 0, 0, 0, 0, *(table[v * KEYS + i] for v in range(4))] for i in dks]
    if pk:
        pk[-1][4] = 1
    return pk


def dump(dev, all_profiles=False):
    """현재 설정 전체를 dict 로(응답 원문 포함). all_profiles 는 프로필을 바꿔 가며 읽으므로 쓰기가 생긴다."""
    cur = dev.get_profile()

    def magnet():
        m = {t: dev.get_magnet(t) for t in MAG_ORDER}
        if any(v & 127 == 2 for v in m[M_MODE]):  # DKS 키가 있을 때만 표를 읽는다
            m[M_DKS_DATA] = dev.get_magnet(M_DKS_DATA, 4 * KEYS)
        return m

    if all_profiles:
        mag = {}
        try:
            for pr in range(LAYERS):
                dev.select_profile(pr)
                mag[pr] = magnet()
        finally:
            dev.select_profile(cur)
    else:
        mag = {cur: magnet()}
    out = {"version": 2, "device_id": dev.device_id(), "revision": dev.revision(), "profile": cur,
           "debounce": dev.get_debounce(), "sleep": dev.get_sleep(),
           "options": list(dev.get_options() or []), "rate": {l: dev.get_rate(l) for l in range(LAYERS)},
           "light": dev.get_light(),
           "sidelight": dev.get_sidelight(),
           "keymatrix": {l: {s: dev.get_keymatrix(l, s).hex() for s in range(4)} for l in range(LAYERS)},
           "fn": {l: dev.get_fn(l).hex() for l in range(LAYERS)}, "magnet": mag}
    out["raw"] = [{"sent": s, "recv": r} for s, r in dev.log]
    return out


def _legacy_keys(b):
    """옛 백업의 옵션 항목 이름(kboption)을 지금 이름으로 바꾼다."""
    if isinstance(b, dict) and "kboption" in b:
        b = {**b, "options": b["kboption"]}
        del b["kboption"]
    return b


def _check_backup(b):
    """쓰기 전에 백업 구조를 전부 검사한다. 문제가 있으면 ValueError."""
    try:
        if b.get("version") != 2:
            raise MsgError("restore.old")
        check_int("profile", b["profile"], 0, LAYERS - 1)
        for l in range(LAYERS):
            for s in range(4):
                if len(bytes.fromhex(b["keymatrix"][str(l)][str(s)])) != 4 * KEYS:
                    raise MsgError("restore.keymap_len")
            if len(bytes.fromhex(b["fn"][str(l)])) != 4 * KEYS:
                raise MsgError("restore.fn_len")
        if not b["magnet"]:
            raise MsgError("restore.no_magnet")
        for pr, types in b["magnet"].items():
            check_int("magnet profile", int(pr), 0, LAYERS - 1)
            magnet_packets({int(t): v for t, v in types.items()})  # 길이·DKS 표 검사
        for name, effects in (("light", EFFECTS), ("sidelight", SIDE_EFFECTS)):
            d = b.get(name)
            if d and d["effect"] in effects:  # 표에 없는 효과는 restore 가 건너뛴다
                check_light(d["effect"], d["speed"], d["bright"], d["option"], d["rgb"], effects)
        for pr, hz in b.get("rate", {}).items():  # 없으면 옛 백업. 표 밖 값은 restore 가 건너뛴다
            check_int("rate profile", int(pr), 0, LAYERS - 1)
            if hz is not None:
                check_int("rate", hz, 0, 1 << 31)
        if len(b["options"]) != 5:
            raise MsgError("restore.options")
        for v in b["options"]:
            check_int("options", v, 0, 255)
        if b["debounce"] is not None:
            check_int("debounce", b["debounce"], 0, 255)
    except (KeyError, TypeError, AttributeError, IndexError) as e:
        raise MsgError("restore.format", reason=e)


class RestoreError(Msg, OSError):
    """복원 도중 실패. 앞 단계는 이미 장치에 써졌다(원인은 __cause__)."""


def restore(dev, backup):
    """백업(dump 결과 또는 그 JSON)을 장치에 쓴다. 건너뛴 항목 목록을 돌려준다. 실기기 쓰기가 많다.

    순서: 키맵 -> Fn -> 자기 축(프로필별) -> 조명 -> 측면 조명 -> 옵션 -> 디바운스 -> 폴링레이트 -> 백업 때의 프로필 선택.
    쓰기 중 실패하면 복원 전 프로필로 되돌리기를 시도한 뒤 RestoreError 를 올린다(검증 오류는 ValueError 그대로).
    """
    b = _legacy_keys(json.loads(json.dumps(backup)))  # 키를 문자열로 통일
    _check_backup(b)
    orig, stage, done, skipped = dev.get_profile(), "", [], []
    try:
        for stage, step in (("keymap", _restore_keymap), ("fn", _restore_fn), ("magnet", _restore_magnet),
                            ("light", _restore_lights), ("options", _restore_options), ("rate", _restore_rate)):
            r = step(dev, b)
            skipped += r or []
            done.append(stage)
        stage = "profile"
        dev.select_profile(b["profile"])
    except Exception as e:
        back = False
        if orig is not None:
            try:
                dev.select_profile(orig)
                back = True
            except Exception:
                pass
        raise RestoreError("restore.partial", stage=Msg("restore.stage." + stage),
                           done=[Msg("restore.stage." + d) for d in done] or Msg("common.none"),
                           back=Msg("restore.back_ok" if back else "restore.back_fail"), cause=e) from e
    return skipped


def _restore_keymap(dev, b):
    for l in range(LAYERS):
        for s in range(4):
            dev.write_keymap(l, s, bytes.fromhex(b["keymatrix"][str(l)][str(s)]))


def _restore_fn(dev, b):
    for l in range(LAYERS):
        dev.write_matrix(S_FNMATRIX, l, bytes.fromhex(b["fn"][str(l)]))


def _restore_magnet(dev, b):
    sel = dev.get_profile()
    for pr, types in sorted(b["magnet"].items()):
        if int(pr) != sel:
            dev.select_profile(int(pr))
            sel = int(pr)
        if dev.get_profile() != int(pr):  # 자기 축은 현재 프로필에 써지므로 쓰기 직전에 다시 확인한다
            raise OSError("Profile is not %d before writing the magnetic data" % int(pr))
        dev.write_magnet_all({int(t): v for t, v in types.items()})


def _restore_lights(dev, b):
    skipped = []
    for name, effects, setter in (("light", EFFECTS, dev.set_light), ("sidelight", SIDE_EFFECTS, dev.set_sidelight)):
        d = b.get(name)
        if d and d["effect"] in effects:
            setter(d["effect"], d["speed"], d["bright"], d["option"], d["rgb"], d["dazzle"])
        else:
            skipped.append(name)
    return skipped


def _restore_options(dev, b):
    raw = b["options"]
    dev._write_options(bytes([S_OPTION, 0, raw[1], raw[2], raw[3]]), bytes(raw))
    if b["debounce"] is not None:
        dev.set_debounce(b["debounce"])


def _restore_rate(dev, b):
    for pr, hz in sorted(b.get("rate", {}).items()):
        if hz in RATE_CODES and dev.get_rate(int(pr)) != hz and dev.set_rate(hz, int(pr)) != hz:
            raise OSError("Polling rate of profile %s was not applied" % pr)


def diff_backup(want, got):
    """복원 결과 비교: want(백업)와 got(복원 뒤 되읽은 dump)에서 다른 항목 이름 목록."""
    want, got = _legacy_keys(json.loads(json.dumps(want))), json.loads(json.dumps(got))
    out = []

    def leaf(path, x, y):
        if isinstance(x, str) and isinstance(y, str):  # 키맵/Fn hex: 쓰지 않는 끝 8바이트(키 126,127)는 제외
            x, y = x[:1008], y[:1008]
        if x != y:
            at = [i for i, (p, q) in enumerate(zip(x, y)) if p != q][:8] if isinstance(x, list) and isinstance(y, list) else []
            out.append(path + (" @" + ",".join(map(str, at)) if at else ""))

    def walk(path, x, y):
        if isinstance(x, dict) and isinstance(y, dict):
            for k in x:
                walk(path + "." + k, x[k], y.get(k))
        else:
            leaf(path, x, y)

    for k in ("profile", "debounce", "light", "sidelight", "keymatrix", "fn", "magnet"):
        walk(k, want.get(k), got.get(k))
    if want.get("rate"):  # 옛 백업에는 없다. 복원하지 않는 값(None, 표 밖)은 비교하지 않는다
        walk("rate", {k: v for k, v in want["rate"].items() if v in RATE_CODES}, got.get("rate") or {})
    leaf("options", want["options"][1:4], got["options"][1:4])
    return out
