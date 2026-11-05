import json

import pytest

from agk75 import protocol as P
from agk75 import service as s

from test_service import Fake, hub


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
                    "get_options", "get_rate"):
            return lambda: None
        if name == "get_magnet":
            return lambda t: [0] * 128
        raise AttributeError(name)


def test_state_saves_snapshot_once_and_factory_restore_uses_it(tmp_path):
    dev = SnapFake()
    h = s.Service(opener=lambda: dev, backup_dir=tmp_path, factory_dir=tmp_path)
    with pytest.raises(ValueError):
        h.fn(layer=1, idx=0, default=True)  # 스냅샷 없음
    assert h.state()["factory"] is True
    assert (tmp_path / "factory_1846.json").exists()
    dev.fn0 = bytes(512)  # 이후 장치 값이 바뀌어도 스냅샷은 그대로
    h.state()
    r = h.fn(layer=1, idx=0, default=True)
    assert r["applied"] is True and r["item"] == [10, 2, 0, 0]
    assert h.key(layer=0, idx=8, default=True)["item"] == [0, 0, 0, 0]
    assert h.fn(layer=1, idx=8, hid=20)["item"] == [0, 0, 20, 0]
    for bad in ({"layer": 1, "idx": 65, "default": True}, {"layer": 4, "idx": 0, "default": True}):
        with pytest.raises(ValueError):  # Fn 키 보호 / 레이어 범위
            h.fn(**bad)


def test_options_write():
    h = hub(Fake())
    r = h.options(wasd_arrow=True)
    assert r["applied"] is True and r["options"]["wasd_arrow"] is True
    with pytest.raises(ValueError):
        h.options()


def write_backup(tmp_path, name="backup_20260101_000000.json"):
    (tmp_path / name).write_text(json.dumps({"magnet": {"0": {}}, "options": [0] * 5}), encoding="utf-8")
    return name


def test_restore_validates_file_name_without_dropping_device(tmp_path):
    dev = Fake()
    h = s.Service(opener=lambda: dev, backup_dir=tmp_path)
    for name in ("../backup_x.json", "other.json", "backup_missing.json", "", None, 3):
        with pytest.raises(ValueError):
            h.restore(file=name)
    assert h.dev is dev  # 파일 문제는 장치 오류로 처리되지 않는다


def test_restore_reports_diff_and_skipped(tmp_path, monkeypatch):
    name = write_backup(tmp_path)
    h = s.Service(opener=Fake, backup_dir=tmp_path)
    monkeypatch.setattr(s.P, "restore", lambda dev, b: ["sidelight"])
    monkeypatch.setattr(s.P, "dump", lambda dev, all_profiles=False: json.loads((tmp_path / name).read_text("utf-8")))
    r = h.restore(file=name)
    assert r["applied"] is True and r["skipped"] == ["sidelight"] and r["diff"] == []
    monkeypatch.setattr(s.P, "dump", lambda dev, all_profiles=False: {"magnet": {"0": {}}, "options": [0, 0, 0, 9, 0]})
    r = h.restore(file=name)
    assert r["applied"] is False and r["diff"] == ["options @2"]


def test_restore_rejects_old_format_file(tmp_path):
    (tmp_path / "backup_old.json").write_text(json.dumps({"device_id": 1846, "magnet": {"0": [0] * 126}}), "utf-8")
    h = s.Service(opener=Fake, backup_dir=tmp_path)
    with pytest.raises(ValueError) as e:
        h.restore(file="backup_old.json")
    assert "버전 2" in s.describe_error(e.value)


def test_backup_writes_file_and_lists_it(tmp_path, monkeypatch):
    monkeypatch.setattr(s.P, "dump", lambda dev, all_profiles=False: {"all": all_profiles})
    h = s.Service(opener=Fake, backup_dir=tmp_path)
    name = h.backup(all_profiles=True)["name"]
    assert json.loads((tmp_path / name).read_text("utf-8")) == {"all": True}
    assert [b["name"] for b in h.backups()["backups"]] == [name]
    with pytest.raises(ValueError):
        h.backup(all_profiles="yes")


class FakeMeasure:
    def __init__(self):
        self.running = False

    def start(self, seconds):
        if self.running:
            raise ValueError("이미 측정 중입니다")
        self.running, self.seconds = True, seconds

    def status(self):
        return {"running": self.running, "result": None}


def test_measure_start_and_status():
    h = hub(Fake())
    h.measure = FakeMeasure()
    for bad in (1, 61):
        with pytest.raises(ValueError):
            h.measure_start(seconds=bad)
    r = h.measure_start()
    assert r["seconds"] == 15 and h.measure.seconds == 15
    with pytest.raises(ValueError):
        h.measure_start(seconds=10)  # 이미 측정 중
    assert h.measure_status()["running"] is True


def test_magnet_range_and_index_use_128_keys():
    h = hub(Fake())
    assert h.magnet(idx=127, travel=1.0)["applied"] is True
    with pytest.raises(ValueError):
        h.magnet(idx=128, travel=1.0)
    assert P.KEYS == 128


def test_state_has_current_profile_rate_and_no_usb():
    class StateFake(Fake):
        def __getattr__(self, name):  # 읽기 메서드는 빈 값으로
            if name in ("device_id", "revision", "get_debounce", "get_sleep", "get_light",
                        "get_sidelight", "get_options"):
                return lambda: None
            if name in ("get_magnet",):
                return lambda t: [0] * 128
            if name in ("get_keymatrix", "get_fn"):
                return lambda l: bytes(512)
            raise AttributeError(name)

    dev = StateFake()
    dev.rate = {2: 500}
    a = hub(dev).state()
    assert a["profile"] == 2 and a["rate"] == 500 and "usb" not in a


def test_restore_reports_partial_restore(tmp_path, monkeypatch):
    name = write_backup(tmp_path)
    dev = Fake()
    h = s.Service(opener=lambda: dev, backup_dir=tmp_path)

    def boom(d, b):
        try:
            raise OSError("끊김")
        except OSError as e:
            raise s.P.RestoreError("부분 복원됨: 조명 단계에서 중단") from e

    monkeypatch.setattr(s.P, "restore", boom)
    r = h.restore(file=name)
    assert r["applied"] is False and r["partial"] is True and "부분 복원됨" in r["message"]
    assert h.dev is None  # 통신 오류가 원인이면 다음 작업에서 다시 연결한다
