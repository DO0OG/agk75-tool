import sys
from pathlib import Path

import pytest

from agk75 import __main__ as entry
from agk75 import ratectl
from agk75 import server as s

from test_server import hub
from test_ratectl import INST, state


@pytest.fixture
def fake_rate(monkeypatch):
    log = {"ops": []}
    monkeypatch.setattr(ratectl, "driver_state", lambda: state(filter=True, binterval=2, configured_hz=4000))
    monkeypatch.setattr(ratectl, "run_admin", lambda ops: log["ops"].append(ops) or {"ok": True, "ops": []})
    monkeypatch.setattr(ratectl, "reread_usb", lambda: {"max_hz": log.get("hz", 4000), "speed": "High"})
    monkeypatch.setattr(s.usbinfo, "read", lambda: {"max_hz": 8000})
    return log


def test_state_endpoint(fake_rate):
    code, r = s.handle(hub(None), "GET", "/api/rate/state")
    assert code == 200 and r["state"]["device"] == INST and r["usb"]["max_hz"] == 8000 and r["table"][8000] == 1


def test_set_runs_plan_and_reports_reread_usb(fake_rate):
    h = hub(None)
    code, r = s.handle(h, "POST", "/api/rate/set", {"hz": 4000})
    assert code == 200 and r["applied"] is True and r["verified"] is True and r["usb"]["max_hz"] == 4000
    assert [o["op"] for o in fake_rate["ops"][0]] == ["binterval", "restart"]  # 필터는 이미 있음
    assert h.rate["running"] is False and h.dev is None and not h.lock.locked() and not h.rate_lock.locked()
    fake_rate["hz"] = 8000
    r = s.handle(h, "POST", "/api/rate/set", {"hz": 4000})[1]
    assert r["applied"] is True and r["verified"] is False  # 작업은 끝났지만 협상값이 다르다


def test_reset_and_admin_failure_and_unreadable_usb(fake_rate, monkeypatch):
    code, r = s.handle(hub(None), "POST", "/api/rate/reset")
    assert code == 200 and [o["op"] for o in fake_rate["ops"][0]] == ["binterval_del", "filter_remove", "restart"]
    monkeypatch.setattr(ratectl, "run_admin", lambda ops: {"ok": False, "ops": [], "error": "거부됨"})
    monkeypatch.setattr(ratectl, "reread_usb", lambda: {"error": "x"})
    r = s.handle(hub(None), "POST", "/api/rate/set", {"hz": 2000})[1]
    assert r["applied"] is False and r["message"] == "거부됨" and r["verified"] is None


def test_bad_hz_rejected_before_admin(fake_rate):
    for body in ({"hz": 3000}, {"hz": "8000"}, {}, {"hz": True}):
        assert s.handle(hub(None), "POST", "/api/rate/set", body)[0] == 400
    assert fake_rate["ops"] == []


def test_prepare_errors_are_shown_and_second_job_is_refused(monkeypatch, fake_rate):
    def fail():
        raise ratectl.RateError("서명 확인 실패")
    monkeypatch.setattr(ratectl, "prepare", fail)
    h = hub(None)
    code, r = s.handle(h, "POST", "/api/rate/prepare")
    assert code == 400 and "서명" in r["error"] and not h.rate_lock.locked()
    monkeypatch.setattr(ratectl, "prepare", lambda: {"nopatch": True, "signer": "CN=x"})
    assert s.handle(h, "POST", "/api/rate/prepare")[1]["nopatch"] is True
    assert h.rate_lock.acquire(blocking=False)
    assert s.handle(h, "POST", "/api/rate/set", {"hz": 4000})[0] == 400  # 이미 진행 중
    h.rate_lock.release()


def test_progress_endpoint_reports_running_step(fake_rate, monkeypatch):
    h = hub(None)
    seen = []
    monkeypatch.setattr(ratectl, "run_admin", lambda ops: seen.append(s.handle(h, "GET", "/api/rate/progress")[1]) or {"ok": True})
    s.handle(h, "POST", "/api/rate/set", {"hz": 4000})
    assert seen[0]["running"] is True and "관리자" in seen[0]["step"]
    assert s.handle(h, "GET", "/api/rate/progress")[1]["running"] is False


def test_main_dispatches_admin_and_rate_reset(monkeypatch):
    got = []
    monkeypatch.setattr(ratectl, "admin_main", lambda p: got.append(p) or 0)
    monkeypatch.setattr(sys, "argv", ["agk75", "--admin", "C:/job.json"])
    with pytest.raises(SystemExit) as e:
        entry.main()
    assert got == ["C:/job.json"] and e.value.code == 0
    monkeypatch.setattr(ratectl, "plan_reset", lambda: [{"op": "restart", "instance": INST}])
    monkeypatch.setattr(ratectl, "run_admin", lambda ops: {"ok": True})
    monkeypatch.setattr(sys, "argv", ["agk75", "--rate-reset"])
    with pytest.raises(SystemExit) as e:
        entry.main()
    assert e.value.code == 0
    monkeypatch.setattr(ratectl, "run_admin", lambda ops: {"ok": False, "error": "x"})
    with pytest.raises(SystemExit) as e:
        entry.main()
    assert e.value.code == 1


def test_rate_lock_is_held_while_admin_job_runs(fake_rate, monkeypatch):
    h = hub(None)
    held = []
    monkeypatch.setattr(ratectl, "run_admin", lambda ops: held.append(h.rate_lock.locked()) or {"ok": True, "ops": []})
    s.handle(h, "POST", "/api/rate/set", {"hz": 4000})
    assert held == [True] and not h.rate_lock.locked()


def test_unfinished_admin_job_blocks_new_requests_until_result_file_appears(fake_rate, monkeypatch, tmp_path):
    result = tmp_path / "job.json"
    monkeypatch.setattr(ratectl, "run_admin", lambda ops: {"ok": False, "ops": [], "pending": str(result), "error": "시간 초과"})
    h = hub(None)
    r = s.handle(h, "POST", "/api/rate/set", {"hz": 4000})[1]
    assert r["applied"] is False and h.rate_pending == str(result) and not h.rate_lock.locked()
    monkeypatch.setattr(ratectl, "run_admin", lambda ops: pytest.fail("관리자 작업을 또 띄우면 안 됩니다"))
    for path, body in (("/api/rate/set", {"hz": 2000}), ("/api/rate/reset", None), ("/api/rate/prepare", None)):
        code, r = s.handle(h, "POST", path, body)
        assert code == 400 and "이전 관리자 작업이 아직 진행 중" in r["error"]
    assert not h.rate_lock.locked() and h.rate["running"] is False
    result.write_text("{}")
    monkeypatch.setattr(ratectl, "run_admin", lambda ops: {"ok": True, "ops": []})
    assert s.handle(h, "POST", "/api/rate/set", {"hz": 2000})[0] == 200 and h.rate_pending is None


def test_set_reports_reboot_needed_from_restart_output(fake_rate, monkeypatch):
    res = {"ok": True, "ops": [{"op": "restart", "ok": True, "detail": "장치를 다시 부팅해야 합니다"}]}
    monkeypatch.setattr(ratectl, "run_admin", lambda ops: res)
    assert s.handle(hub(None), "POST", "/api/rate/set", {"hz": 4000})[1]["reboot_needed"] is True
    monkeypatch.setattr(ratectl, "run_admin", lambda ops: {"ok": True, "ops": [{"op": "restart", "detail": "ok"}]})
    assert s.handle(hub(None), "POST", "/api/rate/set", {"hz": 4000})[1]["reboot_needed"] is False


def test_card_shows_unverified_table_notice_and_reboot_message():
    web = Path(s.__file__).parent / "web"
    js, words = (web / "keys.js").read_text(encoding="utf-8"), (web / "i18n.js").read_text(encoding="utf-8")
    assert "rate.table_warn" in js and "rate.res.reboot" in js and "j.reboot_needed" in js
    assert "대응표는 실기기 확인 전" in words and "재부팅 후 적용됩니다" in words
