"""화면·서비스 시험용 가짜 키보드: 쓴 값을 기억했다가 읽기 명령으로 돌려준다. 실제 장치는 건드리지 않는다."""
import functools
import threading

from agk75 import protocol as P


class FakeKeyboard:
    def __init__(self):
        keymap = bytearray(4 * P.KEYS)
        for idx, hid in P.DEFAULT_HID.items():
            keymap[idx * 4 + 2] = hid
        self.keymap = {l: bytes(keymap) for l in range(P.LAYERS)}
        self.fn = {l: bytes(4 * P.KEYS) for l in range(P.LAYERS)}
        self.profile, self.debounce, self.opts = 0, 3, bytearray([134, 0, 0, 0, 0])
        self.rates = {l: 8000 for l in range(P.LAYERS)}
        self.light = P.light_expect(4, 2, 3, 1, (255, 90, 31))
        self.sidelight = P.light_expect(3, 2, 4, 1, (1, 2, 3), side=True)
        self.mag = {i: dict(travel=1.9, lift=1.9, dead=0.3, rt=False, rt_press=0.3, rt_lift=0.3) for i in range(P.KEYS)}
        self.writes, self.closed, self.threads = [], False, set()
        for name in dir(self):  # 어느 스레드에서 장치를 불렀는지 기록한다
            fn = getattr(self, name)
            if callable(fn) and not name.startswith("_"):
                setattr(self, name, self._tracked(fn))

    def _tracked(self, fn):
        @functools.wraps(fn)
        def call(*a, **kw):
            self.threads.add(threading.get_ident())
            return fn(*a, **kw)
        return call

    # ---- 읽기 ----
    def device_id(self):
        return 1846

    def revision(self):
        return 0x0103

    def get_profile(self):
        return self.profile

    def get_debounce(self):
        return self.debounce

    def get_rate(self, profile=0):
        return self.rates[profile]

    def get_sleep(self):
        return [60, 300, 600, 1800]

    def get_options(self):
        return bytes(self.opts)

    def get_light(self):
        return dict(self.light)

    def get_sidelight(self):
        return dict(self.sidelight)

    def get_keymatrix(self, layer, sub=0):
        return self.keymap[layer]

    def get_fn(self, layer):
        return self.fn[layer]

    def get_magnet(self, typ):
        key = {P.M_TRAVEL: "travel", P.M_LIFT: "lift", P.M_RT_PRESS: "rt_press", P.M_RT_LIFT: "rt_lift"}.get(typ)
        if typ == P.M_DEAD:
            return [P.dead_to_byte(self.mag[i]["dead"]) for i in range(P.KEYS)]
        if typ == P.M_MODE:
            return [P.M_RT_FLAG if self.mag[i]["rt"] else 0 for i in range(P.KEYS)]
        return [P.mm_to_byte(self.mag[i][key]) for i in range(P.KEYS)]

    # ---- 쓰기(기록을 남긴다) ----
    def set_profile(self, layer):
        self.writes.append(("profile", layer))
        self.profile = layer
        return layer

    def set_debounce(self, ms):
        self.writes.append(("debounce", ms))
        self.debounce = ms
        return ms

    def set_rate(self, hz, profile=0):
        self.writes.append(("rate", hz, profile))
        self.rates[profile] = hz
        return hz

    def set_options(self, **kw):
        self.writes.append(("options", kw))
        if "wasd_arrow" in kw:
            self.opts[1] = self.opts[1] & ~8 | (8 if kw["wasd_arrow"] else 0)
        return bytes(self.opts)

    def set_light(self, effect, speed, bright, option, rgb, dazzle=False):
        self.writes.append(("light", effect))
        self.light = P.light_expect(effect, speed, bright, option, rgb, dazzle)
        return dict(self.light)

    def set_sidelight(self, effect, speed, bright, option, rgb, dazzle=False):
        self.writes.append(("sidelight", effect))
        self.sidelight = P.light_expect(effect, speed, bright, option, rgb, dazzle, side=True)
        return dict(self.sidelight)

    def set_key(self, layer, idx, item):
        self.writes.append(("key", layer, idx, bytes(item)))
        self.keymap[layer] = self.keymap[layer][:idx * 4] + bytes(item) + self.keymap[layer][idx * 4 + 4:]
        return bytes(item)

    def set_fn(self, layer, idx, item):
        self.writes.append(("fn", layer, idx, bytes(item)))
        self.fn[layer] = self.fn[layer][:idx * 4] + bytes(item) + self.fn[layer][idx * 4 + 4:]
        return bytes(item)

    def set_magnet(self, idx, **kw):
        self.writes.append(("magnet", idx, kw))
        self.mag[idx].update({k: v for k, v in kw.items() if v is not None})
        return {**self.mag[idx], "raw": {}}

    def close(self):
        self.closed = True
