import json

from agk75 import protocol as P
from agk75 import server as s

from test_server import Fake, hub


class SnapFake(Fake):
    """첫 연결 스냅샷 시험용: 읽기 값을 돌려주는 가짜 장치(쓰기는 기록만)."""

    fn0 = bytes([10, 2, 0, 0]) + bytes(508)

    def device_id(self):
        return 1846

    def get_keymatrix(self, layer, sub=0):
        return bytes(512)

    def get_fn(self, layer):
        return self.fn0

    def __getattr__(self, name):
        if name in ("revision", "get_profile", "get_debounce", "get_sleep", "get_light", "get_sidelight",
                    "get_options"):
            return lambda: None
        if name == "get_magnet":
            return lambda t: [0] * 128
        raise AttributeError(name)


def test_state_saves_snapshot_once_and_factory_restore_uses_it(tmp_path, monkeypatch):
    monkeypatch.setattr(s.usbinfo, "read", lambda: {})
    dev = SnapFake()
    h = s.Hub(opener=lambda: dev, backup_dir=tmp_path, factory_dir=tmp_path)
    assert s.handle(h, "POST", "/api/fn", {"layer": 1, "idx": 0, "default": True})[0] == 400  # 스냅샷 없음
    assert s.handle(h, "GET", "/api/state")[1]["factory"] is True
    assert (tmp_path / "factory_1846.json").exists() and "default_fn" not in s.handle(h, "GET", "/api/state")[1]["meta"]
    dev.fn0 = bytes(512)  # 이후 장치 값이 바뀌어도 스냅샷은 그대로
    s.handle(h, "GET", "/api/state")
    code, r = s.handle(h, "POST", "/api/fn", {"layer": 1, "idx": 0, "default": True})
    assert code == 200 and r["applied"] is True and r["item"] == [10, 2, 0, 0]
    code, r = s.handle(h, "POST", "/api/key", {"layer": 0, "idx": 8, "default": True})
    assert code == 200 and r["item"] == [0, 0, 0, 0]
    code, r = s.handle(h, "POST", "/api/fn", {"layer": 1, "idx": 8, "hid": 20})
    assert r["item"] == [0, 0, 20, 0]
    assert s.handle(h, "POST", "/api/fn", {"layer": 1, "idx": 65, "default": True})[0] == 400  # Fn 키 보호
    assert s.handle(h, "POST", "/api/fn", {"layer": 4, "idx": 0, "default": True})[0] == 400


def test_options_endpoint():
    h = hub(Fake())
    code, r = s.handle(h, "POST", "/api/options", {"wasd_arrow": True})
    assert code == 200 and r["applied"] is True and r["options"]["wasd_arrow"] is True
    assert s.handle(h, "POST", "/api/options", {})[0] == 400


def write_backup(tmp_path, name="backup_20260101_000000.json"):
    (tmp_path / name).write_text(json.dumps({"magnet": {"0": {}}, "options": [0] * 5}), encoding="utf-8")
    return name


def test_restore_endpoint_validates_file_name_without_dropping_device(tmp_path):
    dev = Fake()
    h = s.Hub(opener=lambda: dev, backup_dir=tmp_path)
    for name in ("../backup_x.json", "other.json", "backup_missing.json", "", None, 3):
        code, r = s.handle(h, "POST", "/api/restore", {"file": name})
        assert code == 400 and r["ok"] is False
    assert h.dev is dev  # 파일 문제는 장치 오류(503)로 처리되지 않는다


def test_restore_endpoint_reports_diff_and_skipped(tmp_path, monkeypatch):
    name = write_backup(tmp_path)
    h = s.Hub(opener=Fake, backup_dir=tmp_path)
    monkeypatch.setattr(s.P, "restore", lambda dev, b: ["sidelight"])
    monkeypatch.setattr(s.P, "dump", lambda dev, all_profiles=False: json.loads((tmp_path / name).read_text("utf-8")))
    code, r = s.handle(h, "POST", "/api/restore", {"file": name})
    assert code == 200 and r["applied"] is True and r["skipped"] == ["sidelight"] and r["diff"] == []
    monkeypatch.setattr(s.P, "dump", lambda dev, all_profiles=False: {"magnet": {"0": {}}, "options": [0, 0, 0, 9, 0]})
    code, r = s.handle(h, "POST", "/api/restore", {"file": name})
    assert r["applied"] is False and r["diff"] == ["options @2"]


def test_restore_rejects_old_format_file(tmp_path):
    (tmp_path / "backup_old.json").write_text(json.dumps({"device_id": 1846, "magnet": {"0": [0] * 126}}), "utf-8")
    h = s.Hub(opener=Fake, backup_dir=tmp_path)
    code, r = s.handle(h, "POST", "/api/restore", {"file": "backup_old.json"})
    assert code == 400 and "버전 2" in r["error"]


class FakeMeasure:
    def __init__(self):
        self.running = False

    def start(self, seconds):
        if self.running:
            raise ValueError("이미 측정 중입니다")
        self.running, self.seconds = True, seconds

    def status(self):
        return {"running": self.running, "result": None}


def test_measure_endpoints():
    h = hub(Fake())
    h.measure = FakeMeasure()
    assert s.handle(h, "POST", "/api/measure/start", {"seconds": 1})[0] == 400
    assert s.handle(h, "POST", "/api/measure/start", {"seconds": 61})[0] == 400
    code, r = s.handle(h, "POST", "/api/measure/start", {})
    assert code == 200 and r["seconds"] == 10 and h.measure.seconds == 10
    assert s.handle(h, "POST", "/api/measure/start", {"seconds": 10})[0] == 400  # 이미 측정 중
    code, r = s.handle(h, "GET", "/api/measure/status")
    assert code == 200 and r["running"] is True


def test_magnet_range_and_index_use_128_keys():
    h = hub(Fake())
    assert s.handle(h, "POST", "/api/magnet", {"idx": 127, "travel": 1.0})[0] == 200
    assert s.handle(h, "POST", "/api/magnet", {"idx": 128, "travel": 1.0})[0] == 400
    assert P.KEYS == 128


# ---------- 요청 검사 / 부분 복원 ----------
def test_state_has_fresh_usb_and_no_rate(monkeypatch):
    reads = iter([{"max_hz": 8000}, {"max_hz": 1000}])
    monkeypatch.setattr(s.usbinfo, "read", lambda: next(reads))

    class StateFake(Fake):
        def __getattr__(self, name):  # 읽기 메서드는 빈 값으로
            if name in ("device_id", "revision", "get_profile", "get_debounce", "get_sleep", "get_light",
                        "get_sidelight", "get_options"):
                return lambda: None
            if name in ("get_magnet",):
                return lambda t: [0] * 128
            if name in ("get_keymatrix", "get_fn"):
                return lambda l: bytes(512)
            raise AttributeError(name)

    h = hub(StateFake())
    a = s.handle(h, "GET", "/api/state")[1]
    b = s.handle(h, "GET", "/api/state")[1]
    assert "rate_code" not in a and a["usb"]["max_hz"] == 8000 and b["usb"]["max_hz"] == 1000  # 캐시하지 않는다
    assert s.handle(h, "POST", "/api/rate", {"hz": 8000})[0] != 200


def test_json_content_type_is_exact():
    ok = ("application/json", "application/json; charset=utf-8", "Application/JSON;charset=UTF-8")
    bad = ("text/plain; x=application/json", "application/jsonp", "application/json; boundary=x", "", "x/application/json")
    assert all(s.json_content_type(v) for v in ok) and not any(s.json_content_type(v) for v in bad)


def test_restore_endpoint_reports_partial_restore(tmp_path, monkeypatch):
    name = write_backup(tmp_path)
    dev = Fake()
    h = s.Hub(opener=lambda: dev, backup_dir=tmp_path)

    def boom(d, b):
        try:
            raise OSError("끊김")
        except OSError as e:
            raise s.P.RestoreError("부분 복원됨: 조명 단계에서 중단") from e

    monkeypatch.setattr(s.P, "restore", boom)
    code, r = s.handle(h, "POST", "/api/restore", {"file": name})
    assert code == 200 and r["applied"] is False and r["partial"] is True and "부분 복원됨" in r["message"]
    assert h.dev is None  # 통신 오류가 원인이면 다음 요청에서 다시 연결한다
