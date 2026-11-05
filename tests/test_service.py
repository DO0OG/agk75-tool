import threading

import pytest

from agk75 import service as s


class Fake:
    """장치 대신 쓰는 가짜 객체: 쓴 값을 그대로(또는 일부러 다르게) 돌려준다."""

    def __init__(self, drift=False):
        self.drift, self.keys, self.mag, self.rate = drift, {}, {}, {}

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

    def set_profile(self, layer):
        return layer

    def get_profile(self):
        return 2

    def get_rate(self, profile=0):
        return self.rate.get(profile, 8000)

    def set_rate(self, hz, profile=0):
        self.rate[profile] = hz if not self.drift else 8000
        return self.rate[profile]

    def close(self):
        pass


def hub(dev):
    return s.Service(opener=lambda: dev)


def test_key_write_confirmed_and_mismatch_flagged():
    r = hub(Fake()).key(layer=0, idx=8, hid=20)
    assert r["applied"] is True and r["item"] == [0, 0, 20, 0] and r["name"] == "Q"
    assert hub(Fake(drift=True)).key(layer=0, idx=8, hid=20)["applied"] is False  # 되읽은 값이 다르면 화면이 빨간 경고를 띄운다


def test_bad_input_rejected_before_device_write():
    dev = Fake()
    h = hub(dev)
    for body in ({"layer": 4, "idx": 8, "hid": 20}, {"layer": 0, "idx": 65, "hid": 20},
                 {"layer": 0, "idx": 8, "hid": 999}, {"layer": 0, "idx": 8}):
        with pytest.raises(ValueError):
            h.key(**body)
    assert dev.keys == {}


def test_light_magnet_and_sidelight():
    h = hub(Fake())
    body = {"effect": 4, "speed": 2, "bright": 4, "option": 1, "rgb": [255, 0, 0], "dazzle": False}
    r = h.light(**body)
    assert r["applied"] is True and r["light"]["rgb"] == (255, 0, 0)
    with pytest.raises(ValueError):
        h.light(**{**body, "effect": 13})  # 목록에 없는 효과
    r = h.magnet(idx=3, travel=1.5)
    assert r["applied"] is True and r["magnet"]["travel"] == 1.5
    with pytest.raises(ValueError):
        h.magnet(idx=3, travel=9)
    side = {"effect": 3, "speed": 2, "bright": 4, "option": 1, "rgb": [1, 2, 3], "dazzle": False}
    r = h.sidelight(**side)
    assert r["applied"] is True and r["sidelight"]["effect"] == 3
    for bad in ({"effect": 6}, {"speed": 5}):  # 측면 조명에 없는 효과 / 속도 범위 밖
        with pytest.raises(ValueError):
            h.sidelight(**{**side, **bad})


def test_profile_write_checks_range():
    h = hub(Fake())
    assert h.profile(layer=3) == {"applied": True, "profile": 3, "rate": 8000}
    with pytest.raises(ValueError):
        h.profile(layer=4)


def test_magnet_all_reports_progress():
    h = hub(Fake())
    seen = []
    h.on_progress = lambda n, total: seen.append((n, total))
    r = h.magnet_all(travel=1.2)
    assert r["applied"] is True and h.progress == {"n": 128, "total": 128, "running": False}
    assert seen[0] == (1, 128) and seen[-1] == (128, 128)


def test_device_missing_raises_and_retries():
    calls = []

    def opener():
        calls.append(1)
        raise OSError("AGK75 를 찾지 못했습니다")
    h = s.Service(opener=opener)
    for _ in range(2):
        with pytest.raises(OSError):
            h.state()
    assert len(calls) == 2  # 다음 작업에서 다시 연결을 시도한다


def test_device_error_drops_the_handle():
    class Broken(Fake):
        def set_key(self, *a):
            raise OSError("끊김")
    h = hub(Broken())
    with pytest.raises(OSError):
        h.key(layer=0, idx=8, hid=20)
    assert h.dev is None


def test_hub_serializes_device_access():
    h = hub(Fake())
    assert h.lock.acquire(blocking=False)
    got = []
    t = threading.Thread(target=lambda: got.append(h.key(layer=0, idx=8, hid=20)))
    t.start()
    t.join(0.3)
    assert t.is_alive()  # 잠금이 풀릴 때까지 기다린다
    h.lock.release()
    t.join(2)
    assert got and got[0]["applied"] is True


def test_rate_write_confirmed_by_readback_and_validated():
    dev = Fake()
    r = hub(dev).rate(hz=500)
    assert r == {"applied": True, "profile": 2, "rate": 500} and dev.rate == {2: 500}  # 현재 프로필(2)에 쓴다
    assert hub(Fake(drift=True)).rate(hz=500) == {"applied": False, "profile": 2, "rate": 8000}
    dev = Fake()
    for bad in (125, 0, 3000, True, "1000", None, 1000.5, 100001):
        with pytest.raises(ValueError):
            hub(dev).rate(hz=bad)
    with pytest.raises(ValueError):
        hub(dev).rate()
    assert dev.rate == {}  # 검사에서 막혀 장치에는 쓰지 않았다
    assert s.describe_error(pytest.raises(ValueError, hub(dev).rate, hz=3).value) == "hz 는 8000, 4000, 2000, 1000, 500, 250 중 하나여야 합니다"
    assert hub(Fake()).rate_read() == {"profile": 2, "rate": 8000}
    r = hub(Fake()).profile(layer=2)
    assert r["applied"] is True and r["rate"] == 8000  # 프로필을 바꾼 뒤 그 프로필의 값을 함께 돌려준다


def test_poll_reports_connection_and_profile():
    h = hub(Fake())
    assert h.poll() == {"connected": True, "profile": 2}
    assert h.lock.acquire(blocking=False)
    assert h.poll() == {"connected": True}  # 쓰기 중이면 장치를 건드리지 않고 지금 상태만 알린다
    h.lock.release()

    def opener():
        raise OSError("없음")
    assert s.Service(opener=opener).poll() == {"connected": False}


def test_describe_error_maps_exception_kinds():
    assert s.describe_error(s.MsgError("err.no_change")) == "바꿀 항목이 없습니다"
    assert s.describe_error(OSError("x")) == "장치 통신 오류: x"
    assert s.describe_error(NotImplementedError("nope")) == "nope"
    assert s.describe_error(KeyError("k")).startswith("KeyError")
