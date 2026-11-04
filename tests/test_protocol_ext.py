import pytest

from agk75 import protocol as p


# ---------- 조명 디코드/인코드 ----------
def test_light_music_and_screen_effects_decode():
    # 20: 무지개 판정은 니블 0, 프리셋 치환은 함
    d = p.decode_light(bytes([135, 20, 1, 4, 0x00, 9, 9, 9]))
    assert d["dazzle"] is True and d["rgb"] == p.PRESET_COLORS[0]
    d = p.decode_light(bytes([135, 20, 1, 4, 0x04, 9, 9, 9]))
    assert d["dazzle"] is False and d["rgb"] == p.PRESET_COLORS[4]
    # 21: 무지개는 니블 8, 프리셋 치환 안 함
    d = p.decode_light(bytes([135, 21, 1, 4, 0x03, 7, 8, 9]))
    assert d["dazzle"] is False and d["rgb"] == (7, 8, 9)
    assert p.decode_light(bytes([135, 21, 1, 4, 0x08, 7, 8, 9]))["dazzle"] is True
    # 22: 무지개는 니블 0, 프리셋 치환 안 함
    d = p.decode_light(bytes([135, 22, 1, 4, 0x00, 7, 8, 9]))
    assert d["dazzle"] is True and d["rgb"] == (7, 8, 9)
    # 일반 효과는 니블 8 이 무지개
    assert p.decode_light(bytes([135, 4, 1, 4, 0x08, 7, 8, 9]))["dazzle"] is True


def test_sidelight_decode_always_substitutes_preset():
    d = p.decode_light(bytes([136, 21, 3, 4, 0x02, 7, 8, 9]), side=True)
    assert d["rgb"] == p.PRESET_COLORS[2] and d["speed"] == 3
    assert p.decode_light(bytes([136, 22, 3, 4, 0x00, 7, 8, 9]), side=True)["dazzle"] is True


def test_light_mode_byte_for_music_and_screen_effects():
    assert p.encode_light(20, 2, 4, 1, (1, 2, 3), dazzle=True)[4] == 1 << 4
    assert p.encode_light(22, 2, 4, 1, (1, 2, 3))[4] == 1 << 4 | 4
    assert p.encode_light(21, 2, 4, 3, (1, 2, 3))[4] == 0
    assert p.encode_light(3, 2, 4, 1, (1, 2, 3))[4] == 1 << 4 | p.NORMAL  # 본체 Neon 은 일반 모드


def test_sidelight_encode():
    b = p.encode_sidelight(4, 3, 2, 1, (255, 255, 255))
    assert b[:8] == bytes([8, 4, 3, 2, 1 << 4 | 7, 0xFA, 0xFF, 0xFA])  # 속도 반전 없음, 흰색은 FAFFFA
    assert b[8] == 255 - (sum(b[:8]) & 0xFF)
    assert p.encode_sidelight(3, 1, 4, 2, (9, 9, 9))[4] == 8  # Neon 은 byte4 = 8
    assert p.encode_sidelight(4, 1, 4, 0, (9, 9, 9), dazzle=True)[4] == 8
    assert p.encode_sidelight(21, 1, 4, 2, (9, 9, 9))[4] == 0
    assert p.encode_sidelight(20, 1, 4, 2, (9, 9, 9))[4] == 2 << 4 | 4


def test_light_expect_roundtrips_every_effect():
    for side, effects in ((False, p.EFFECTS), (True, p.SIDE_EFFECTS)):
        for e in effects:
            got = p.light_expect(e, 2, 3, 1, (10, 20, 30), False, side)
            assert got["effect"] == e and got["speed"] == 2 and got["bright"] == 3


def test_effect_tables_match_vendor_names():
    assert p.EFFECTS[20] == "Music3" and p.EFFECTS[21] == "ScreenColor" and p.EFFECTS[22] == "Music2"
    assert p.SIDE_EFFECTS == {0: "Off", 1: "AlwaysOn", 2: "Breath", 3: "Neon", 4: "Wave", 5: "Snake",
                              20: "Music3", 21: "ScreenColor", 22: "Music2"}


# ---------- 키 수 ----------
def test_magnet_table_has_128_keys():
    assert p.KEYS == 128


# ---------- 옵션 ----------
def test_options_decode_encode():
    raw = bytes([0, 0b10101011, 1, 5, 0])  # B1..B5
    d = p.decode_options(raw)
    assert d == {"win_lock": True, "mac": True, "wasd_arrow": True, "led_off": False, "side_led_off": True,
                 "keyboard_lock": True, "fn_matrix": True, "power_save": True}
    cmd = p.encode_options(raw, wasd_arrow=False, power_save=False)
    assert cmd == bytes([6, 0, 0b10100011, 1, 0])  # 해석 안 되는 비트와 Fn 비트는 그대로
    with pytest.raises(ValueError):
        p.encode_options(raw, led_off=1)
    with pytest.raises(ValueError):
        p.encode_options(raw, nope=True)


# ---------- 가짜 장치(전송 바이트 기록) ----------
class RecHid:
    """send_feature_report 를 기록하고, GET 에는 opcode 만 채운 응답을 준다."""

    def __init__(self, stuck=False):
        self.sent, self.last, self.profile, self.stuck, self.ret = [], b"", 0, stuck, 65
        self.mem, self.led = {}, {7: bytes(7), 8: bytes(7)}  # 청크로 쓴 행렬, 마지막 조명 SET

    def send_feature_report(self, data):
        self.sent.append(bytes(data[1:]))
        self.last = bytes(data[1:])
        if self.last[0] == 16:  # Fn 청크 쓰기
            buf, k = self.mem.setdefault((16, self.last[1]), bytearray(512)), self.last[4] * 56
            buf[k:k + 56] = self.last[8:64]
        if self.last[0] == 19:  # 키 하나 쓰기
            buf, k = self.mem.setdefault((9, self.last[1]), bytearray(512)), self.last[2] * 4
            buf[k:k + 4] = self.last[8:12]
        if self.last[0] in (7, 8):
            self.led[self.last[0]] = self.last[1:8]
        if self.last[0] == 5 and not self.stuck:
            self.profile = self.last[1] // 4
        return self.ret

    def get_feature_report(self, rid, n):
        op = self.last[0]
        if op in (137, 144):  # 행렬 청크 읽기: 헤더 없이 64바이트
            buf = self.mem.get((9 if op == 137 else 16, self.last[1]), bytearray(512))
            return b"\0" + bytes(buf[self.last[2] * 64:][:64])
        if op in (135, 136):  # 조명: 마지막으로 쓴 값을 되돌려 준다
            return b"\0" + bytes([op]) + self.led[op - 128] + bytes(56)
        return b"\0" + bytes([op, self.profile * 4]) + bytes(62)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(p.time, "sleep", lambda s: None)


def fake_device():
    dev = p.Device.__new__(p.Device)
    dev.dev, dev.log = RecHid(), []
    return dev


def writes(dev):
    return [x for x in dev.dev.sent if x[0] < 128]  # GET(128 이상)을 뺀 쓰기 패킷


def test_device_setters_validate_before_any_write():
    dev = fake_device()
    bad = [lambda: dev.set_profile(4), lambda: dev.set_debounce(256), lambda: dev.set_key(4, 8, bytes(4)),
           lambda: dev.set_key(0, 128, bytes(4)), lambda: dev.set_key(0, 8, bytes(3)),
           lambda: dev.set_fn(0, -1, bytes(4)),
           lambda: dev.set_light(13, 0, 0, 0, (0, 0, 0)), lambda: dev.set_light(1, 5, 0, 0, (0, 0, 0)),
           lambda: dev.set_light(1, 0, 5, 0, (0, 0, 0)), lambda: dev.set_light(1, 0, 0, 16, (0, 0, 0)),
           lambda: dev.set_light(1, 0, 0, 0, (0, 0, 256)), lambda: dev.set_light(1, 0, 0, 0, (0, 0)),
           lambda: dev.set_sidelight(6, 0, 0, 0, (0, 0, 0)), lambda: dev.set_magnet(128, travel=1.0),
           lambda: dev.set_magnet(0, travel=0.0), lambda: dev.set_magnet(0, lift=4.1),
           lambda: dev.set_magnet(0, dead=4.0), lambda: dev.set_magnet(0, rt_press=True),
           lambda: dev.set_options(led_off=1)]
    for f in bad:
        with pytest.raises(ValueError):
            f()
    assert dev.dev.sent == []  # 검증에서 막혀 장치에는 아무것도 가지 않았다


def test_set_sidelight_sends_side_report():
    dev = fake_device()
    dev.set_sidelight(3, 2, 4, 1, (255, 255, 255))
    out = dev.dev.sent[0]
    assert out[:8] == bytes([8, 3, 2, 4, 8, 0xFA, 0xFF, 0xFA]) and out[8] == 255 - (sum(out[:8]) & 0xFF)


def test_opcodes_for_restore_allowed_but_dangerous_still_blocked():
    assert {6, 9, 16} <= p.ALLOWED
    for op in (1, 2, 3, 12, 28, 30, 44, 127, 172, 186):
        assert op not in p.ALLOWED


def test_magnet_packets_order_and_last_flag():
    types = {t: [t] * 128 for t in p.MAG_ORDER}
    types[7] = [0] * 128
    types[7][5] = 2  # DKS 키
    types[10] = [(i * 7) & 255 for i in range(512)]
    pk = p.magnet_packets(types)
    seq = [x[1] for x in pk]
    assert [t for i, t in enumerate(seq) if i == 0 or seq[i - 1] != t] == [7, 0, 1, 2, 3, 6, 4, 5, 9, 8]
    assert [x[3] for x in pk if x[1] == 7] == [0, 1, 2]  # 56 + 56 + 16 바이트
    assert [x[4] for x in pk[:-1]] == [0] * (len(pk) - 1) and pk[-1][4] == 1
    assert pk[-1][:8] == [101, 8, 0, 5, 1, 0, 0, 0] and pk[-1][8:] == [types[10][v * 128 + 5] for v in range(4)]
    with pytest.raises(ValueError):
        p.magnet_packets({7: types[7]})  # DKS 키가 있는데 표가 없음


def sample_backup():
    return {"version": 2, "device_id": 1846, "revision": 513, "profile": 0, "debounce": 1, "sleep": [1, 2, 3, 4],
            "options": [0, 0b00010001, 1, 0, 0],
            "light": {"effect": 8, "speed": 2, "bright": 4, "option": 0, "dazzle": False, "mode": 7, "rgb": [255, 0, 0]},
            "sidelight": {"effect": 4, "speed": 3, "bright": 4, "option": 0, "dazzle": True, "mode": 8,
                          "rgb": [255, 255, 255]},
            "keymatrix": {l: {s: bytes(512).hex() for s in range(4)} for l in range(4)},
            "fn": {l: bytes([100 + l]).hex() * 512 for l in range(4)},
            "magnet": {0: {t: [t] * 128 for t in p.MAG_ORDER}}}


def test_restore_sends_documented_sequence():
    dev = fake_device()
    b = sample_backup()
    b["keymatrix"][1][2] = bytes([0, 0, 0x2c, 0]).hex() + bytes(508).hex()  # 장치(전부 0)와 다른 키 하나
    assert p.restore(dev, b) == []
    out = writes(dev)
    # 다른 키 1개(S_KEY, 키맵 쓰기는 청크가 아니라 키별), Fn 4 x 9, 자기 축 27(9타입 x 3), 조명, 측면 조명, 옵션, 디바운스, 프로필
    assert [x[0] for x in out] == [19] + [16] * 36 + [101] * 27 + [7, 8, 6, 17, 5]
    assert out[0][1:3] == bytes([1 * 4 + 2, 0]) and out[0][8:12] == bytes([0, 0, 0x2c, 0])
    for l in range(4):
        pk = out[1 + l * 9:1 + (l + 1) * 9]
        assert [x[1] for x in pk] == [l] * 9 and [x[4] for x in pk] == list(range(9))
        assert all(x[2] == 248 and x[3] == 1 for x in pk) and pk[8][8:64] == bytes([100 + l]) * 56
    mag = out[37:64]
    assert [x[1] for x in mag[::3]] == [7, 0, 1, 2, 3, 6, 4, 5, 9]
    assert [x[4] for x in mag] == [0] * 26 + [1]  # 마지막 패킷만 '끝'
    assert out[64][1:5] == bytes([8, 2, 4, 7]) and out[65][1:5] == bytes([4, 3, 4, 8])
    assert out[66][:5] == bytes([6, 0, 0b00010001, 1, 0]) and out[67][:3] == bytes([17, 0, 1])
    assert out[68][:2] == bytes([5, 0])
    for x in out:  # 체크섬: 조명류는 byte 8, 나머지는 byte 7
        n = 8 if x[0] in (7, 8) else 7
        assert x[n] == 255 - (sum(x[:n]) & 0xFF)


def test_restore_switches_profile_for_other_profiles_and_ends_on_backup_profile():
    b = sample_backup()
    b["magnet"] = {pr: {t: [pr + 10] * 128 for t in p.MAG_ORDER} for pr in range(4)}
    b["profile"] = 2
    dev = fake_device()
    p.restore(dev, b)
    # 장치는 프로필 0 에서 시작하므로 1,2,3 으로 전환한 뒤 백업의 프로필 2 로 끝낸다
    assert [x[1] // 4 for x in writes(dev) if x[0] == 5] == [1, 2, 3, 2]


def test_restore_rejects_bad_backup_before_any_write():
    dev = fake_device()
    old = {"device_id": 1846, "keymatrix": {"0": "00" * 512}, "magnet": {"0": [0] * 126}}
    for bad in (old, {**sample_backup(), "version": 1}, {**sample_backup(), "fn": {}},
                {**sample_backup(), "options": [1, 2]}, {**sample_backup(), "profile": 9}, []):
        with pytest.raises(ValueError):
            p.restore(dev, bad)
    assert dev.dev.sent == []


def test_dump_structure_and_diff():
    dev = fake_device()
    d = p.dump(dev)
    assert d["version"] == 2 and list(d["magnet"]) == [0] and sorted(d["magnet"][0]) == sorted(p.MAG_ORDER)
    assert len(d["magnet"][0][0]) == 128 and len(d["keymatrix"][3][3]) == 1024 and len(d["fn"][3]) == 1024
    assert p.diff_backup(d, d) == []
    other = p.dump(dev)
    other["magnet"][0][0][5] = 9
    other["keymatrix"][1][2] = "ff" + other["keymatrix"][1][2][2:]
    assert p.diff_backup(d, other) == ["keymatrix.1.2", "magnet.0.0 @5"]


def test_restore_aborts_without_axis_writes_when_profile_switch_fails():
    b = sample_backup()
    b["magnet"] = {pr: {t: [1] * 128 for t in p.MAG_ORDER} for pr in range(1, 4)}  # 현재 프로필(0)과 달라 전환이 필요하다
    dev = fake_device()
    dev.dev.stuck = True  # set_profile 이 늘 0 을 되돌려 준다
    with pytest.raises(OSError):
        p.restore(dev, b)
    assert not [x for x in writes(dev) if x[0] == 101]  # 자기 축 패킷은 전송되지 않았다
    assert [x[0] for x in writes(dev)][-1] == 5  # 전환 시도 뒤 아무것도 더 쓰지 않았다


def test_restore_rechecks_profile_before_axis_write():
    dev = fake_device()
    b = sample_backup()
    b["profile"] = 0
    dev.get_profile = lambda: 3  # 백업은 프로필 0 인데 장치가 다른 프로필을 가리킴
    with pytest.raises(OSError):
        p.restore(dev, b)
    assert not [x for x in writes(dev) if x[0] == 101]


def test_dump_all_profiles_selects_each_and_returns_to_original():
    dev = fake_device()
    dev.dev.profile = 2
    d = p.dump(dev, all_profiles=True)
    assert sorted(d["magnet"]) == [0, 1, 2, 3] and dev.dev.profile == 2
    assert [x[1] // 4 for x in writes(dev)] == [0, 1, 2, 3, 2]
    dev = fake_device()
    dev.dev.stuck = True
    with pytest.raises(OSError):
        p.dump(dev, all_profiles=True)


def test_send_raises_on_failed_feature_report():
    for bad in (-1, None):
        dev = fake_device()
        dev.dev.ret = bad
        with pytest.raises(OSError):
            dev.send(bytes([5, 0]))


def test_get_retries_when_response_opcode_is_stale():
    dev = fake_device()
    calls = []
    real = dev.dev.get_feature_report
    dev.dev.get_feature_report = lambda rid, n: (calls.append(1), bytes(65) if len(calls) < 3 else real(rid, n))[1]
    assert dev.get_profile() == 0 and len(calls) == 3


def test_select_profile_waits_then_resends_once():
    dev = fake_device()
    reads = iter([None] * 5)  # 첫 전송 뒤 되읽기 5번은 전환 전, 이후 반영
    dev.get_profile = lambda: next(reads, 2)
    dev.select_profile(2)
    assert [x[1] // 4 for x in writes(dev)] == [2, 2]


class _Sink(dict):
    """쓰기를 저장하지 않는 장치 메모리."""

    def setdefault(self, key, default=None):
        return bytearray(512)


def test_write_matrix_raises_when_device_never_applies():
    dev = fake_device()
    dev.dev.mem = _Sink()
    with pytest.raises(OSError):
        dev.write_matrix(p.S_FNMATRIX, 1, bytes([5]) * 504)
    assert len([x for x in writes(dev) if x[0] == 16]) == 18  # 2회 시도


def test_set_light_resends_once_when_readback_differs():
    dev = fake_device()
    real = dev.dev.send_feature_report
    seen = []

    def send(data):  # 첫 조명 패킷은 장치가 무시한다
        if data[1] == 7 and not seen:
            seen.append(1)
            dev.dev.sent.append(bytes(data[1:]))
            return 65
        return real(data)

    dev.dev.send_feature_report = send
    got = dev.set_light(8, 2, 4, 0, (255, 0, 0))
    assert len([x for x in writes(dev) if x[0] == 7]) == 2 and got["effect"] == 8


def test_get_survives_empty_response():
    dev = fake_device()
    calls, real = [], dev.dev.get_feature_report
    dev.dev.get_feature_report = lambda rid, n: (calls.append(1), b"" if len(calls) == 1 else real(rid, n))[1]
    assert dev.get_profile() == 0 and len(calls) == 2


# ---------- 복원 사전 검증 / 실패 시 프로필 복귀 ----------
def test_restore_prechecks_light_values_before_any_write():
    for key, bad in (("light", {"speed": 5}), ("light", {"bright": 9}), ("light", {"option": 16}),
                     ("light", {"rgb": [0, 0, 256]}), ("sidelight", {"speed": -1})):
        b = sample_backup()
        b[key] = {**b[key], **bad}
        dev = fake_device()
        with pytest.raises(ValueError):
            p.restore(dev, b)
        assert dev.dev.sent == []
    b = sample_backup()
    b["light"] = {**b["light"], "effect": 13}  # 표에 없는 효과는 건너뛰기 대상이라 검증하지 않는다
    assert p.restore(fake_device(), b) == ["light"]


def test_restore_failure_returns_to_original_profile_and_reports_stage():
    dev = fake_device()
    dev.dev.profile = 2  # 복원 전 프로필
    b = sample_backup()
    b["profile"] = 1
    dev.set_light = lambda *a: (_ for _ in ()).throw(OSError("조명 실패"))
    with pytest.raises(p.RestoreError) as e:
        p.restore(dev, b)
    assert "Lighting" in str(e.value) and "Keymap, Fn, Magnetic switches" in str(e.value) and "Switched back" in str(e.value)
    assert isinstance(e.value.__cause__, OSError)
    assert dev.dev.profile == 2  # 백업 시점(1)이 아니라 복원 전 프로필로 돌아간다
