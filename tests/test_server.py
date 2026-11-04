import threading

from agk75 import server as s


class Fake:
    """장치 대신 쓰는 가짜 객체: 쓴 값을 그대로(또는 일부러 다르게) 돌려준다."""

    def __init__(self, drift=False):
        self.drift, self.keys, self.mag = drift, {}, {}

    def set_key(self, layer, idx, item):
        self.keys[(layer, idx)] = bytes(item)
        return b"\0\0\x05\0" if self.drift else bytes(item)

    def set_light(self, effect, speed, bright, option, rgb, dazzle=False):
        return {"effect": effect, "speed": speed, "bright": bright, "option": option, "rgb": tuple(rgb),
                "dazzle": dazzle, "mode": 7}

    def set_sidelight(self, effect, speed, bright, option, rgb, dazzle=False):
        from agk75 import protocol as P
        return P.light_expect(effect, speed, bright, option, rgb, dazzle, side=True)

    def set_fn(self, layer, idx, item):
        self.keys[("fn", layer, idx)] = bytes(item)
        return bytes(item)

    def set_options(self, **kw):
        self.opt = kw
        return bytes([0, 0b00001000 if kw.get("wasd_arrow") else 0, 0, 0, 0])

    def set_magnet(self, idx, **kw):
        self.mag[idx] = kw
        return {"travel": kw.get("travel", 1.9), "lift": 1.9, "dead": 0.3, "rt": kw.get("rt", False),
                "rt_press": 0.3, "rt_lift": 0.3, "raw": {}}

    def close(self):
        pass


def hub(dev):
    return s.Hub(opener=lambda: dev)


def test_key_write_confirmed_and_mismatch_flagged():
    dev = Fake()
    code, r = s.handle(hub(dev), "POST", "/api/key", {"layer": 0, "idx": 8, "hid": 20})
    assert code == 200 and r["applied"] is True and r["item"] == [0, 0, 20, 0] and r["name"] == "Q"
    code, r = s.handle(hub(Fake(drift=True)), "POST", "/api/key", {"layer": 0, "idx": 8, "hid": 20})
    assert code == 200 and r["applied"] is False  # 되읽은 값이 다르면 UI 가 빨간 경고를 띄운다


def test_bad_input_rejected_before_device_write():
    dev = Fake()
    h = hub(dev)
    for body in ({"layer": 4, "idx": 8, "hid": 20}, {"layer": 0, "idx": 65, "hid": 20},
                 {"layer": 0, "idx": 8, "hid": 999}, {"layer": 0, "idx": 8}):
        code, r = s.handle(h, "POST", "/api/key", body)
        assert code == 400 and r["ok"] is False
    assert dev.keys == {}


def test_light_magnet_and_sidelight():
    h = hub(Fake())
    body = {"effect": 4, "speed": 2, "bright": 4, "option": 1, "rgb": [255, 0, 0], "dazzle": False}
    code, r = s.handle(h, "POST", "/api/light", body)
    assert r["applied"] is True and r["light"]["rgb"] == (255, 0, 0)
    assert s.handle(h, "POST", "/api/light", {**body, "effect": 13})[0] == 400  # 목록에 없는 효과
    code, r = s.handle(h, "POST", "/api/magnet", {"idx": 3, "travel": 1.5})
    assert r["applied"] is True and r["magnet"]["travel"] == 1.5
    assert s.handle(h, "POST", "/api/magnet", {"idx": 3, "travel": 9})[0] == 400
    side = {"effect": 3, "speed": 2, "bright": 4, "option": 1, "rgb": [1, 2, 3], "dazzle": False}
    code, r = s.handle(h, "POST", "/api/sidelight", side)
    assert code == 200 and r["applied"] is True and r["sidelight"]["effect"] == 3
    assert s.handle(h, "POST", "/api/sidelight", {**side, "effect": 6})[0] == 400  # 측면 조명에 없는 효과
    assert s.handle(h, "POST", "/api/sidelight", {**side, "speed": 5})[0] == 400


def test_magnet_all_reports_progress():
    h = hub(Fake())
    code, r = s.handle(h, "POST", "/api/magnet_all", {"travel": 1.2})
    assert r["applied"] is True and h.progress == {"n": 128, "total": 128, "running": False}


def test_device_missing_gives_503_and_retries():
    def opener():
        raise OSError("AGK75 를 찾지 못했습니다")
    code, r = s.handle(s.Hub(opener=opener), "GET", "/api/state")
    assert code == 503 and r["ok"] is False


def test_hub_serializes_device_access():
    h = hub(Fake())
    assert h.lock.acquire(blocking=False)
    got = []
    t = threading.Thread(target=lambda: got.append(s.handle(h, "POST", "/api/key", {"layer": 0, "idx": 8, "hid": 20})))
    t.start()
    t.join(0.3)
    assert t.is_alive()  # 잠금이 풀릴 때까지 기다린다
    h.lock.release()
    t.join(2)
    assert got and got[0][0] == 200
