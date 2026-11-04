import io
import json
import uuid
import zipfile
from pathlib import Path

import pytest

from agk75 import ratectl as r

INST = r"USB\VID_3151&PID_5009\7&10FBF3BC&0&2"
KEY = r"SYSTEM\CurrentControlSet\Enum\USB\VID_3151&PID_5009\7&10FBF3BC&0&2"
SIG_OK = "Status=Valid\nSubject=" + r.SIGNER_SUBJECT + "\n"


class Run:
    """_run 대신 쓰는 가짜: 호출을 기록하고 미리 정한 (코드, 출력)을 돌려준다."""

    def __init__(self, replies=None, default=(0, "")):
        self.calls, self.replies, self.default = [], replies or {}, default

    def __call__(self, args, timeout=60):
        self.calls.append(list(args))
        for head, reply in self.replies.items():
            if args[0] == head:
                return reply
        return self.default


@pytest.fixture
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    return tmp_path / "appdata" / "AGK75Tool"


def make_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


class FakeResp:
    def __init__(self, data):
        self.data = data

    def read(self, n=-1):
        return self.data[:n] if n >= 0 else self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_rate_table_is_hypothesis_a_and_8000_is_default_interval():
    assert r.RATE_TABLE == {8000: 1, 4000: 2, 2000: 3, 1000: 4}
    assert r.INF_SET == "HIDUSBF_AS.INF"


# ---------- 열거·상태 ----------
def test_find_instance_parses_connected_only_in_any_language(monkeypatch):
    out = "인스턴스 ID:  %s\n설명: USB 복합 장치\n인스턴스 ID:  USB\\VID_3151&PID_5009&MI_00\\8&1&0&0000\n" % INST
    run = Run({"pnputil": (0, out)})
    monkeypatch.setattr(r, "_run", run)
    assert r.find_device_instance() == INST
    assert run.calls[0][:3] == ["pnputil", "/enum-devices", "/connected"] and r.USB_CLASS in run.calls[0]


def test_find_instance_ignores_registry_leftovers_when_nothing_is_connected(monkeypatch):
    monkeypatch.setattr(r, "_run", Run({"pnputil": (0, "일치하는 장치 없음")}))
    monkeypatch.setattr(r, "_reg_subkeys", lambda sub: ["7&10FBF3BC&0&2"])
    assert r.find_device_instance() is None
    monkeypatch.setattr(r, "_run", Run({"pnputil": (1, "")}))
    assert r.find_device_instance() is None


def test_two_connected_instances_is_an_error_shown_in_state_and_plan(monkeypatch):
    other = INST.replace("7&10FBF3BC&0&2", "7&AAAA&0&3")
    monkeypatch.setattr(r, "_run", Run({"pnputil": (0, "ID: %s\nID: %s\n" % (INST, other))}))
    with pytest.raises(r.RateError, match="2 identical keyboards"):
        r.find_device_instance()
    monkeypatch.setattr(r, "_reg_read", lambda sub, name: None)
    s = r.driver_state()
    assert s["device"] is None and "2 identical keyboards" in s["device_error"]
    with pytest.raises(r.RateError, match="2 identical keyboards"):
        r.plan_set(4000, s)


def test_driver_state_reads_only(monkeypatch, appdata):
    vals = {(r.SERVICE, "ImagePath"): "system32\\drivers\\hidusbf.sys", (KEY, "LowerFilters"): ["HIDUSBF"],
            (KEY + "\\Device Parameters", "bInterval"): 2, (r.HVCI, "Enabled"): 1}
    monkeypatch.setattr(r, "_reg_read", lambda sub, name: vals.get((sub, name)))
    monkeypatch.setattr(r, "find_device_instance", lambda: INST)
    s = r.driver_state()
    assert s["device"] == INST and s["service"] and s["filter"] and s["binterval"] == 2
    assert s["configured_hz"] == 4000 and s["hvci"] is True and s["secure_boot"] is False and s["package"] is False


def test_driver_state_without_filter_has_no_configured_hz(monkeypatch, appdata):
    monkeypatch.setattr(r, "_reg_read", lambda sub, name: None)
    monkeypatch.setattr(r, "find_device_instance", lambda: INST)
    s = r.driver_state()
    assert not s["service"] and not s["filter"] and s["configured_hz"] is None and s["binterval"] is None


# ---------- 서명 ----------
def test_verify_signature_requires_exact_subject(monkeypatch):
    for subj in (r.SIGNER_SUBJECT + ", E=x@y", "CN=Evil, OU=" + r.SIGNER_SUBJECT, r.SIGNER_SUBJECT.replace("C=US", "C=KR"),
                 "CN=Microsoft Windows Hardware Compatibility Publisher"):
        monkeypatch.setattr(r, "_run", Run({"powershell": (0, "Status=Valid\nSubject=%s\n" % subj)}))
        assert r.verify_signature("a")["ok"] is False


def test_verify_signature_valid_invalid_and_other_signer(monkeypatch):
    run = Run({"powershell": (0, SIG_OK)})
    monkeypatch.setattr(r, "_run", run)
    assert r.verify_signature("C:\\x\\it's.sys")["ok"] is True
    assert "it''s.sys" in run.calls[0][-1] and "Get-AuthenticodeSignature" in run.calls[0][-1]
    monkeypatch.setattr(r, "_run", Run({"powershell": (0, "Status=HashMismatch\nSubject=" + r.SIGNER_SUBJECT + "\n")}))
    v = r.verify_signature("a")
    assert v["ok"] is False and v["status"] == "HashMismatch"
    monkeypatch.setattr(r, "_run", Run({"powershell": (0, "Status=Valid\nSubject=CN=SweetLow\n")}))
    assert r.verify_signature("a")["ok"] is False
    monkeypatch.setattr(r, "_run", Run({"powershell": (0, "Status=NotSigned\nSubject=\n")}))
    assert r.verify_signature("a")["status"] == "NotSigned"
    monkeypatch.setattr(r, "_run", Run({"powershell": (1, SIG_OK)}))
    assert r.verify_signature("a")["ok"] is False


# ---------- 내려받기 ----------
def test_download_extracts_only_inf_and_sys(monkeypatch, tmp_path):
    z = make_zip({"DRIVER/HIDUSBF_AS.INF": "x", "DRIVER/AMD64_AS/hidusbf.sys": "s", "DRIVER/Setup.exe": "bad",
                  "DRIVER/sx64.exe": "bad", "README.TXT": "r"})
    monkeypatch.setattr(r, "_urlopen", lambda url: FakeResp(z))
    dest = r.download_package(tmp_path / "dl")
    names = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
    assert names == ["DRIVER/AMD64_AS/hidusbf.sys", "DRIVER/HIDUSBF_AS.INF"]


@pytest.mark.parametrize("bad", ["../evil.inf", "a/../../evil.inf", "/abs/evil.inf", "C:/evil.inf", "..\\evil.inf"])
def test_download_rejects_zip_path_escape(monkeypatch, tmp_path, bad):
    z = make_zip({"ok/HIDUSBF_AS.INF": "x", bad: "e"})
    monkeypatch.setattr(r, "_urlopen", lambda url: FakeResp(z))
    with pytest.raises(r.RateError, match="Unsafe path"):
        r.download_package(tmp_path / "dl")
    assert not (tmp_path / "evil.inf").exists() and not list((tmp_path / "dl").rglob("*.inf"))


def test_download_rejects_too_many_files_and_too_much_data(monkeypatch, tmp_path):
    many = make_zip({"d/f%d.txt" % i: "x" for i in range(r.MAX_FILES + 1)})
    monkeypatch.setattr(r, "_urlopen", lambda url: FakeResp(many))
    with pytest.raises(r.RateError, match="too large or has too many"):
        r.download_package(tmp_path / "a")
    monkeypatch.setattr(r, "MAX_UNPACK", 100)
    big = make_zip({"d/HIDUSBF_AS.INF": "x" * 60, "d/b.txt": "y" * 60})
    monkeypatch.setattr(r, "_urlopen", lambda url: FakeResp(big))
    with pytest.raises(r.RateError, match="too large or has too many"):
        r.download_package(tmp_path / "b")
    assert not list((tmp_path / "b").rglob("*.INF"))


def test_download_requires_empty_dest_and_reports_network_errors(monkeypatch, tmp_path):
    (tmp_path / "used").mkdir()
    (tmp_path / "used" / "f").write_text("x")
    with pytest.raises(r.RateError, match="not empty"):
        r.download_package(tmp_path / "used")

    def boom(url):
        raise OSError("offline")
    monkeypatch.setattr(r, "_urlopen", boom)
    with pytest.raises(r.RateError, match="Failed to download"):
        r.download_package(tmp_path / "new")
    monkeypatch.setattr(r, "_urlopen", lambda url: FakeResp(b"not a zip"))
    with pytest.raises(r.RateError, match="zip"):
        r.download_package(tmp_path / "new2")


# ---------- 준비(스테이징) ----------
def tree(tmp_path, nopatch=True):
    d = tmp_path / "pkg" / "DRIVER"
    for rel, data in {"HIDUSBF_AS.INF": "i", "HIDUSBFU.INF": "u", "AMD64_AS/hidusbf.sys": "patched",
                      **({"AMD64_AS/NoPatch/hidusbf.sys": "nopatch"} if nopatch else {})}.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(data)
    return tmp_path / "pkg"


def test_stage_prefers_nopatch_and_uses_inf_layout(monkeypatch, tmp_path):
    monkeypatch.setattr(r, "_run", Run({"powershell": (0, SIG_OK)}))
    info = r.stage_package(tree(tmp_path), tmp_path / "stage")
    st = tmp_path / "stage"
    assert info["nopatch"] is True and info["inf"] == str(st / "HIDUSBF_AS.INF")
    assert (st / "amd64_as" / "hidusbf.sys").read_text() == "nopatch" and (st / "HIDUSBFU.INF").is_file()
    r.stage_package(tree(tmp_path / "b", nopatch=False), tmp_path / "stage2")
    assert (tmp_path / "stage2" / "amd64_as" / "hidusbf.sys").read_text() == "patched"


def test_stage_removes_files_when_signature_is_bad(monkeypatch, tmp_path):
    monkeypatch.setattr(r, "_run", Run({"powershell": (0, "Status=NotSigned\nSubject=\n")}))
    with pytest.raises(r.RateError, match="signature check failed"):
        r.stage_package(tree(tmp_path), tmp_path / "stage")
    assert not (tmp_path / "stage").exists()
    with pytest.raises(r.RateError):
        r.stage_package(tmp_path / "empty", tmp_path / "stage")


def test_prepare_downloads_stages_and_cleans_temp(monkeypatch, tmp_path):
    z = make_zip({"DRIVER/HIDUSBF_AS.INF": "i", "DRIVER/HIDUSBFU.INF": "u", "DRIVER/AMD64_AS/hidusbf.sys": "s",
                  "DRIVER/AMD64_AS/NoPatch/hidusbf.sys": "n"})
    monkeypatch.setattr(r, "_urlopen", lambda url: FakeResp(z))
    monkeypatch.setattr(r, "_run", Run({"powershell": (0, SIG_OK)}))
    info = r.prepare(tmp_path / "base")
    assert info["nopatch"] and sorted(p.name for p in (tmp_path / "base").iterdir()) == ["stage"]


# ---------- 작업 계획 ----------
def state(**kw):
    return {"device": INST, "service": True, "sys": True, "filter": False, "binterval": None,
            "configured_hz": None, "hvci": False, "secure_boot": True, "package": False, **kw}


def test_plan_set_installed_adds_filter_interval_and_restart():
    assert r.plan_set(4000, state()) == [{"op": "filter_add", "instance": INST},
                                         {"op": "binterval", "instance": INST, "value": 2},
                                         {"op": "restart", "instance": INST}]
    assert r.plan_set(1000, state(filter=True))[0]["value"] == 4
    assert r.plan_set(2000, state(filter=True))[0] == {"op": "binterval", "instance": INST, "value": 3}


def test_plan_set_installs_first_only_with_prepared_package(appdata):
    with pytest.raises(r.RateError, match="Prepare the driver first"):
        r.plan_set(1000, state(service=False))
    ops = r.plan_set(1000, state(service=False, package=True))
    assert ops[0] == {"op": "install", "inf": str(appdata / "hidusbf" / "stage" / "HIDUSBF_AS.INF")}
    assert [o["op"] for o in ops] == ["install", "filter_add", "binterval", "restart"]


def fake_registry(monkeypatch, instances, connected):
    """instances: {레지스트리 하위 키: (LowerFilters, bInterval)}, connected: 지금 연결된 인스턴스 ID 목록."""
    monkeypatch.setattr(r, "_reg_subkeys", lambda sub: list(instances) if sub == r.ENUM else [])

    def read(sub, name):
        for k, (flt, iv) in instances.items():
            if sub == r.ENUM + "\\" + k:
                return flt if name == "LowerFilters" else None
            if sub == r.ENUM + "\\" + k + "\\Device Parameters":
                return iv
        return None
    monkeypatch.setattr(r, "_reg_read", read)
    monkeypatch.setattr(r, "_run", Run({"pnputil": (0, "\n".join("ID: " + c for c in connected))}))


def test_plan_reset_and_8000_and_errors(monkeypatch):
    want = [{"op": "binterval_del", "instance": INST}, {"op": "filter_remove", "instance": INST},
            {"op": "restart", "instance": INST}]
    fake_registry(monkeypatch, {"7&10FBF3BC&0&2": (["hidusbf"], 2)}, [INST])
    assert r.plan_reset() == want
    assert r.plan_set(8000, state(filter=True)) == want
    fake_registry(monkeypatch, {"7&10FBF3BC&0&2": ([], None)}, [INST])
    assert r.plan_reset() == []  # 이미 원래 상태
    with pytest.raises(r.RateError):
        r.plan_set(3000, state())
    with pytest.raises(r.RateError, match="USB device was not found"):
        r.plan_set(4000, state(device=None))


def test_reset_covers_every_instance_even_when_not_connected(monkeypatch):
    other = r"USB\VID_3151&PID_5009\7&AAAA&0&3"
    third = r"USB\VID_3151&PID_5009\7&BBBB&0&4"
    fake_registry(monkeypatch, {"7&10FBF3BC&0&2": (["hidusbf"], 2), "7&AAAA&0&3": (["HIDUSBF", "x"], None),
                                "7&BBBB&0&4": ([], None), "bad key": (["hidusbf"], 1)}, [INST.lower()])
    ops = r.plan_reset()
    assert [(o["op"], o["instance"]) for o in ops] == [
        ("binterval_del", INST), ("filter_remove", INST), ("binterval_del", other), ("filter_remove", other),
        ("restart", INST)]  # 연결 안 된 other 는 정리만 하고 재시작하지 않는다
    assert third not in [o["instance"] for o in ops]
    fake_registry(monkeypatch, {"7&AAAA&0&3": (["hidusbf"], None)}, [])
    assert [o["op"] for o in r.plan_reset()] == ["binterval_del", "filter_remove"]


# ---------- 관리자 실행(요청 쪽) ----------
def test_run_admin_launches_runas_and_reads_result(monkeypatch, appdata):
    seen = []

    def shell(exe, args, cwd):
        seen.append((exe, args, cwd))
        jobf = Path(args.split('"')[1])
        spec = json.loads(jobf.read_text(encoding="utf-8"))
        assert "result" not in spec  # 결과 경로는 관리자 쪽이 스스로 정한다
        jobf.with_name(jobf.name[:-len(".ops.json")] + ".json").write_text(
            json.dumps({"ok": True, "ops": [{"op": "restart", "ok": True}]}), encoding="utf-8")
        return 42
    monkeypatch.setattr(r, "_shell_execute", shell)
    res = r.run_admin([{"op": "restart", "instance": INST}])
    assert res["ok"] is True and "-m agk75 --admin" in seen[0][1] and seen[0][2]
    assert Path(seen[0][1].split('"')[1]).parent == appdata / "admin"


def test_run_admin_denied_and_timeout_leaves_job_pending(monkeypatch, appdata):
    monkeypatch.setattr(r, "_shell_execute", lambda *a: 5)
    assert "denied" in r.run_admin([])["error"]
    monkeypatch.setattr(r, "_shell_execute", lambda *a: 42)
    monkeypatch.setattr(r, "_sleep", lambda s: None)
    res = r.run_admin([], timeout=0.01)
    assert res["ok"] is False and "No administrator task result" in res["error"]
    assert r.admin_pending(res["pending"]) is True
    Path(res["pending"]).write_text("{}")
    assert r.admin_pending(res["pending"]) is False and r.admin_pending(None) is False


def test_run_admin_waits_up_to_ten_minutes_by_default():
    import inspect
    assert inspect.signature(r.run_admin).parameters["timeout"].default == 600


def test_reread_usb_waits_until_device_is_back(monkeypatch):
    answers = iter([{"error": "x"}, {"error": "x"}, {"max_hz": 4000}])
    monkeypatch.setattr(r.usbinfo, "read", lambda: next(answers))
    monkeypatch.setattr(r, "_sleep", lambda s: None)
    assert r.reread_usb() == {"max_hz": 4000}


# ---------- 관리자 쪽 ----------
def job(appdata, ops, name=None, extra=None):
    d = appdata / "admin"
    d.mkdir(parents=True, exist_ok=True)
    name = name or uuid.uuid4().hex
    f = d / (name + ".ops.json")
    f.write_text(json.dumps({"ops": ops, **(extra or {})}), encoding="utf-8")
    return f, d / (name + ".json")


def test_admin_main_backs_up_then_runs_ops_in_order(monkeypatch, appdata):
    run = Run()
    monkeypatch.setattr(r, "_run", run)
    reg = {(KEY, "LowerFilters"): ["other"], (KEY + "\\Device Parameters", "bInterval"): None}
    monkeypatch.setattr(r, "_reg_read", lambda sub, name: reg.get((sub, name)))
    f, res = job(appdata, [{"op": "filter_add", "instance": INST}, {"op": "binterval", "instance": INST, "value": 2},
                           {"op": "restart", "instance": INST}])
    assert r.admin_main(str(f)) == 0
    full = "HKLM\\" + KEY
    assert run.calls == [
        ["reg", "export", full, str(res.with_suffix(".reg")), "/y"],
        ["reg", "add", full, "/v", "LowerFilters", "/t", "REG_MULTI_SZ", "/d", "other\\0hidusbf", "/f"],
        ["reg", "add", full + "\\Device Parameters", "/v", "bInterval", "/t", "REG_DWORD", "/d", "2", "/f"],
        ["pnputil", "/restart-device", INST]]
    out = json.loads(res.read_text(encoding="utf-8"))
    assert out["ok"] is True and out["backup"] == str(res.with_suffix(".reg")) and [o["op"] for o in out["ops"]] == [
        "filter_add", "binterval", "restart"]
    assert not list(res.parent.glob("*.tmp"))


def test_admin_reset_removes_interval_and_filter_then_restarts(monkeypatch, appdata):
    run = Run()
    monkeypatch.setattr(r, "_run", run)
    reg = {(KEY, "LowerFilters"): ["hidusbf"], (KEY + "\\Device Parameters", "bInterval"): 2}
    monkeypatch.setattr(r, "_reg_read", lambda sub, name: reg.get((sub, name)))
    f, res = job(appdata, [{"op": "binterval_del", "instance": INST}, {"op": "filter_remove", "instance": INST},
                           {"op": "restart", "instance": INST}])
    assert r.admin_main(str(f)) == 0
    full = "HKLM\\" + KEY
    assert run.calls[1:] == [["reg", "delete", full + "\\Device Parameters", "/v", "bInterval", "/f"],
                             ["reg", "delete", full, "/v", "LowerFilters", "/f"],
                             ["pnputil", "/restart-device", INST]]


def test_admin_reset_may_touch_several_instances_but_set_may_not(monkeypatch, appdata):
    other = r"USB\VID_3151&PID_5009\7&AAAA&0&3"
    run = Run()
    monkeypatch.setattr(r, "_run", run)
    monkeypatch.setattr(r, "_reg_read", lambda sub, name: None)
    f, res = job(appdata, [{"op": "binterval_del", "instance": INST}, {"op": "filter_remove", "instance": other}])
    assert r.admin_main(str(f)) == 0
    assert [c[1] for c in run.calls if c[0] == "reg"].count("export") == 2
    run.calls.clear()
    f, res = job(appdata, [{"op": "filter_add", "instance": INST}, {"op": "binterval", "instance": other, "value": 2}])
    assert r.admin_main(str(f)) == 1 and run.calls == []


def test_admin_restart_reboot_pending_text_is_reported(monkeypatch, appdata):
    monkeypatch.setattr(r, "_run", Run({"pnputil": (3010, "장치를 다시 시작했습니다.")}))
    monkeypatch.setattr(r, "_reg_read", lambda sub, name: None)
    f, res = job(appdata, [{"op": "restart", "instance": INST}])
    assert r.admin_main(str(f)) == 0
    out = json.loads(res.read_text(encoding="utf-8"))
    assert "Reboot" in out["ops"][0]["detail"] and r.needs_reboot(out) is True


def test_needs_reboot_matches_korean_and_english_pnputil_text():
    ok = lambda d: {"ops": [{"op": "restart", "ok": True, "detail": d}]}
    assert r.needs_reboot(ok("장치를 다시 부팅해야 합니다")) and r.needs_reboot(ok("System reboot is required"))
    assert r.needs_reboot(ok("재부팅 필요"))
    assert not r.needs_reboot(ok("Device restarted successfully")) and not r.needs_reboot({"ops": []})


def test_admin_stops_at_first_failure_and_reports(monkeypatch, appdata):
    calls = []

    def fake(args, timeout=60):
        calls.append(args[:2])
        return (1, "access denied") if args[1] == "add" else (0, "")
    monkeypatch.setattr(r, "_run", fake)
    monkeypatch.setattr(r, "_reg_read", lambda sub, name: None)
    f, res = job(appdata, [{"op": "binterval", "instance": INST, "value": 3}, {"op": "restart", "instance": INST}])
    assert r.admin_main(str(f)) == 1
    out = json.loads(res.read_text(encoding="utf-8"))
    assert out["ok"] is False and out["ops"][-1]["ok"] is False and len(out["ops"]) == 1 and "access denied" in out["error"]
    assert ["pnputil", "/restart-device"] not in calls


@pytest.mark.parametrize("bad", [{"op": "shell", "cmd": "calc"}, {"op": "restart", "instance": r"USB\VID_1&PID_2\x"},
                                 {"op": "restart", "instance": INST + "\\..\\x"}, {"op": "binterval", "instance": INST, "value": 9},
                                 {"op": "install", "inf": "C:\\x\\evil.inf"}, {"op": "install", "inf": "C:\\x\\HIDUSBF_AS.INF"},
                                 "restart"])
def test_admin_rejects_unknown_ops_before_any_change(monkeypatch, appdata, bad):
    run = Run()
    monkeypatch.setattr(r, "_run", run)
    f, res = job(appdata, [{"op": "restart", "instance": INST}, bad])
    assert r.admin_main(str(f)) == 1 and run.calls == []
    assert json.loads(res.read_text(encoding="utf-8"))["ok"] is False


def test_admin_ignores_result_path_in_json_and_writes_beside_job(monkeypatch, appdata, tmp_path):
    monkeypatch.setattr(r, "_run", Run())
    f, res = job(appdata, [], extra={"result": str(tmp_path / "elsewhere.json")})
    assert r.admin_main(str(f)) == 0
    assert res.is_file() and not (tmp_path / "elsewhere.json").exists()


def test_admin_writes_nothing_when_job_is_outside_admin_dir_or_misnamed(monkeypatch, appdata, tmp_path):
    run = Run()
    monkeypatch.setattr(r, "_run", run)
    (tmp_path / "other").mkdir()
    outside = tmp_path / "other" / (uuid.uuid4().hex + ".ops.json")
    outside.write_text(json.dumps({"ops": []}), encoding="utf-8")
    f, res = job(appdata, [], name="notauuid")
    for bad in (outside, f, tmp_path / "missing.ops.json"):
        before = sorted(p.name for p in tmp_path.rglob("*"))
        assert r.admin_main(str(bad)) == 2
        assert sorted(p.name for p in tmp_path.rglob("*")) == before  # 결과·임시·백업 파일 모두 없다
    assert run.calls == []
    g, res = job(appdata, [])
    g.write_text("not json", encoding="utf-8")
    assert r.admin_main(str(g)) == 2 and not res.exists()


# ---------- INF 검사 ----------
GOOD_INF = """; sample
[Version]
Signature="$Windows NT$"
Class=HIDClass
ClassGuid={745a17a0-74d3-11d0-b6fe-00a0c90f57da}
Provider=%Mfg%
DriverVer=01/01/2020,1.0.0.0
CatalogFile=hidusbf.cat

[DestinationDirs]
DefaultDestDir=12
DriverCopyFiles=12

[DefaultInstall.NTamd64]
CopyFiles=DriverCopyFiles

[DefaultInstall.NTamd64.Services]
AddService=hidusbf,,hidusbf_Service_Inst

[DriverCopyFiles]
hidusbf.sys

[SourceDisksNames]
1=%Disk%,,,amd64_as

[SourceDisksFiles]
hidusbf.sys=1

[hidusbf_Service_Inst]
DisplayName=%Svc%
ServiceType=1 ; kernel driver
StartType=3
ErrorControl=1
ServiceBinary=%12%\\hidusbf.sys

[Strings]
Mfg="x"
Disk="HIDUSBF Disk"
Svc="hidusbf"
"""
GOOD_UNINF = """[Version]
Signature="$Windows NT$"

[DefaultInstall]
DelFiles=DriverDelFiles

[DefaultInstall.Services]
DelService=hidusbf,0x200

[DriverDelFiles]
hidusbf.sys

[DestinationDirs]
DefaultDestDir=12
"""


def test_inf_whitelist_accepts_expected_install_and_uninstall_files():
    r.check_inf(GOOD_INF)
    r.check_inf(GOOD_INF.replace("DefaultInstall.NTamd64", "DefaultInstall"))
    r.check_inf(GOOD_UNINF, uninstall=True)


@pytest.mark.parametrize("old,new", [
    ("CopyFiles=DriverCopyFiles", "CopyFiles=DriverCopyFiles\nRegisterDlls=Evil"),
    ("CopyFiles=DriverCopyFiles", "CopyFiles=DriverCopyFiles\nRunPostSetupCommands=Cmd"),
    ("CopyFiles=DriverCopyFiles", "CopyFiles=DriverCopyFiles\nRunPreSetupCommands=Cmd"),
    ("CopyFiles=DriverCopyFiles", "CopyFiles=DriverCopyFiles\nAddReg=Reg"),
    ("CopyFiles=DriverCopyFiles", "CopyFiles=DriverCopyFiles\nDelReg=Reg"),
    ("CopyFiles=DriverCopyFiles", "CopyFiles=DriverCopyFiles\nCopyINF=other.inf"),
    ("CopyFiles=DriverCopyFiles", "CopyFiles=DriverCopyFiles\nInclude=machine.inf\nNeeds=x"),
    ("CopyFiles=DriverCopyFiles", "CopyFiles=EvilFiles"),
    ("CopyFiles=DriverCopyFiles", "CopyFiles=@evil.dll"),
    ("CopyFiles=DriverCopyFiles", "CopyFiles=DriverCopyFiles\\\nRegisterDlls=x"),
    ("hidusbf.sys\n\n[SourceDisksNames]", "hidusbf.sys\nevil.dll\n\n[SourceDisksNames]"),
    ("[Strings]", "[MyRegSection]\nHKLM,Software,x,0,1\n\n[Strings]"),
    ("DefaultDestDir=12", "DefaultDestDir=11"),
    ("ServiceBinary=%12%\\hidusbf.sys", "ServiceBinary=%12%\\evil.sys"),
    ("StartType=3", "StartType=2"),
    ("ServiceType=1 ; kernel driver", "ServiceType=16"),
    ("ErrorControl=1", "ErrorControl=1\nStartName=LocalSystem"),
    ("AddService=hidusbf,,hidusbf_Service_Inst", "AddService=evil,,hidusbf_Service_Inst"),
    ("AddService=hidusbf,,hidusbf_Service_Inst", "AddService=hidusbf,,Other"),
    ("1=%Disk%,,,amd64_as", "1=%Disk%,,,..\\..\\x"),
    ("hidusbf.sys=1", "evil.dll=1"),
    ("CatalogFile=hidusbf.cat", "CatalogFile=hidusbf.cat\nUnknown=1"),
    ("Mfg=\"x\"", "Mfg=\"x\x00\""),
])
def test_inf_whitelist_rejects_dangerous_content(old, new):
    assert old in GOOD_INF
    with pytest.raises(r.RateError):
        r.check_inf(GOOD_INF.replace(old, new))


def test_inf_requires_default_install_and_service_binary():
    with pytest.raises(r.RateError, match="required"):
        r.check_inf(GOOD_INF.replace("ServiceBinary=%12%\\hidusbf.sys", ""))
    with pytest.raises(r.RateError):
        r.check_inf("[Version]\nSignature=\"$Windows NT$\"\n")


@pytest.mark.parametrize("old,new", [
    ("DelFiles=DriverDelFiles", "DelFiles=DriverDelFiles\nCopyFiles=DriverDelFiles"),
    ("DelFiles=DriverDelFiles", "DelFiles=DriverDelFiles\nDelReg=Reg"),
    ("DelFiles=DriverDelFiles", "DelFiles=DriverDelFiles\nRegisterDlls=x"),
    ("DelService=hidusbf,0x200", "DelService=other,0x200"),
    ("hidusbf.sys\n\n[DestinationDirs]", "hidusbf.sys\nuser32.dll\n\n[DestinationDirs]"),
    ("[DestinationDirs]", "[DriverCopyFiles]\nhidusbf.sys\n\n[DestinationDirs]"),
])
def test_uninstall_inf_allows_only_delete_directives(old, new):
    assert old in GOOD_UNINF
    with pytest.raises(r.RateError):
        r.check_inf(GOOD_UNINF.replace(old, new), uninstall=True)


def test_install_inf_cannot_pass_as_uninstall_and_vice_versa():
    with pytest.raises(r.RateError):
        r.check_inf(GOOD_INF, uninstall=True)
    with pytest.raises(r.RateError):
        r.check_inf(GOOD_UNINF)


def test_read_inf_handles_utf16_and_rejects_huge(tmp_path):
    f = tmp_path / "a.inf"
    f.write_bytes(GOOD_INF.encode("utf-16"))
    assert r._read_inf(f) == GOOD_INF
    f.write_bytes(b"x" * (r.MAX_INF + 1))
    with pytest.raises(r.RateError, match="too large"):
        r._read_inf(f)


# ---------- 설치(관리자 전용 폴더에 복사한 뒤 검사) ----------
@pytest.fixture
def progdata(tmp_path, monkeypatch):
    monkeypatch.setenv("ProgramData", str(tmp_path / "pd"))
    return tmp_path / "pd" / "AGK75Tool" / "stage"


def prepared(appdata, inf=GOOD_INF, uninf=GOOD_UNINF):
    st = appdata / "hidusbf" / "stage"
    (st / "amd64_as").mkdir(parents=True)
    (st / "HIDUSBF_AS.INF").write_text(inf, encoding="utf-8")
    (st / "HIDUSBFU.INF").write_text(uninf, encoding="utf-8")
    (st / "amd64_as" / "hidusbf.sys").write_bytes(b"sys")
    return st


def test_admin_install_copies_to_locked_folder_checks_copy_then_installs(monkeypatch, appdata, progdata):
    st = prepared(appdata)
    seen = {}

    def fake(args, timeout=60):
        if args[0] == "powershell":
            seen["sig"] = args[-1]
            return 0, SIG_OK
        if args[0] == "rundll32":
            seen["inf_text"] = Path(args[-1]).read_text(encoding="utf-8")
            seen["inf"] = args[-1]
        seen.setdefault("cmds", []).append(args[0])
        return 0, ""
    monkeypatch.setattr(r, "_run", fake)
    monkeypatch.setattr(r, "_reg_read", lambda sub, name: "ok" if sub == r.SERVICE else None)
    f, res = job(appdata, [{"op": "install", "inf": str(st / "HIDUSBF_AS.INF")}])
    assert r.admin_main(str(f)) == 0
    # 서명 검사와 설치 INF 모두 사용자 쓰기 폴더가 아니라 복사본(관리자 전용)을 가리킨다
    assert str(progdata) in seen["inf"] and str(st) not in seen["inf"] and str(progdata) in seen["sig"]
    assert seen["inf_text"] == GOOD_INF
    assert seen["cmds"].count("icacls") == 3 and seen["cmds"][-1] == "rundll32"
    assert not any(progdata.iterdir())  # 설치가 끝나면 복사본을 지운다


def test_admin_install_icacls_removes_inheritance_for_admins_and_system_only(monkeypatch, appdata, progdata):
    prepared(appdata)
    run = Run({"powershell": (0, SIG_OK)})
    monkeypatch.setattr(r, "_run", run)
    monkeypatch.setattr(r, "_reg_read", lambda sub, name: "ok" if sub == r.SERVICE else None)
    f, res = job(appdata, [{"op": "install", "inf": str(appdata / "hidusbf" / "stage" / "HIDUSBF_AS.INF")}])
    assert r.admin_main(str(f)) == 0
    ic = [c for c in run.calls if c[0] == "icacls"]
    assert all("/inheritance:r" in c and "*S-1-5-32-544:(OI)(CI)F" in c and "*S-1-5-18:(OI)(CI)F" in c for c in ic)
    assert ic[-1][1].startswith(str(progdata)) and len(Path(ic[-1][1]).name) == 32  # 새 uuid 폴더


def test_admin_install_swapped_inf_after_request_is_still_inspected(monkeypatch, appdata, progdata):
    # 요청 뒤 사용자가 준비 폴더의 INF 를 바꿔치기해도 복사본 검사에서 걸린다
    st = prepared(appdata, inf=GOOD_INF.replace("CopyFiles=DriverCopyFiles", "CopyFiles=DriverCopyFiles\nRegisterDlls=Evil"))
    run = Run({"powershell": (0, SIG_OK)})
    monkeypatch.setattr(r, "_run", run)
    monkeypatch.setattr(r, "_reg_read", lambda sub, name: None)
    f, res = job(appdata, [{"op": "install", "inf": str(st / "HIDUSBF_AS.INF")}])
    assert r.admin_main(str(f)) == 1
    assert "rundll32" not in [c[0] for c in run.calls] and not any(progdata.iterdir())
    assert "RegisterDlls" in json.loads(res.read_text(encoding="utf-8"))["error"]


def test_admin_install_rejects_bad_signature_bad_uninstall_inf_and_missing_files(monkeypatch, appdata, progdata):
    st = prepared(appdata)
    run = Run({"powershell": (0, "Status=Valid\nSubject=CN=Microsoft Windows Hardware Compatibility Publisher\n")})
    monkeypatch.setattr(r, "_run", run)
    monkeypatch.setattr(r, "_reg_read", lambda sub, name: None)
    f, res = job(appdata, [{"op": "install", "inf": str(st / "HIDUSBF_AS.INF")}])
    assert r.admin_main(str(f)) == 1 and "signature" in json.loads(res.read_text(encoding="utf-8"))["error"]
    run.replies["powershell"] = (0, SIG_OK)
    (st / "HIDUSBFU.INF").write_text(GOOD_UNINF + "\n[DefaultInstall.Add]\nAddReg=x\n", encoding="utf-8")
    f, res = job(appdata, [{"op": "install", "inf": str(st / "HIDUSBF_AS.INF")}])
    assert r.admin_main(str(f)) == 1
    (st / "amd64_as" / "hidusbf.sys").unlink()
    f, res = job(appdata, [{"op": "install", "inf": str(st / "HIDUSBF_AS.INF")}])
    assert r.admin_main(str(f)) == 1 and "missing or too large" in json.loads(res.read_text(encoding="utf-8"))["error"]
    assert "rundll32" not in [c[0] for c in run.calls] and not any(progdata.iterdir())


# ---------- 실제 배포 INF 그대로(줄바꿈만 LF) ----------
REAL_INF = """;Install File and Service for HIDUSBF lower filter
;Win 98+, Win 2000+, Win x64+ supported

[Version]
Signature=$CHICAGO$
Provider=%MFGNAME%

[SourceDisksNames]
1=%INSTDISK%,,,

[SourceDisksFiles]
hidusbf.sys=1,98me

[SourceDisksFiles.x86]
hidusbf.sys=1,ntx86_as

[SourceDisksFiles.amd64]
hidusbf.sys=1,amd64_as

[DestinationDirs]
DefaultDestDir=10,system32\\drivers
DriverCopyFiles=10,system32\\drivers
DriverCopyFilesNT=12

[DriverCopyFiles]
hidusbf.sys,,,0x04

[DriverCopyFilesNT]
hidusbf.sys,,,0x04

[hidusbfService]
ServiceType=1
StartType=3
ErrorControl=1
ServiceBinary=%12%\\hidusbf.sys
DisplayName=%Description%

;------------------------------------------------------------------------------
;  Windows 2000+ Sections
;------------------------------------------------------------------------------

[DefaultInstall.nt]
CopyFiles=DriverCopyFilesNT

[DefaultInstall.nt.services]
AddService=hidusbf,,hidusbfService

;------------------------------------------------------------------------------
;  Windows 98+ Sections
;------------------------------------------------------------------------------

[DefaultInstall]
CopyFiles=DriverCopyFiles

;------------------------------------------------------------------------------
;  String Definitions
;------------------------------------------------------------------------------

[Strings]
MFGNAME="SweetLow"
INSTDISK="USB Mouse Rate Adjuster"
DESCRIPTION="USB Mouse Rate Adjuster Lower Filter by SweetLow"
"""
REAL_UNINF = """;Uninstall File and Service for HIDUSBF lower filter
;Win 98+, Win 2000+, Win x64+ supported

[Version]
Signature=$CHICAGO$
Provider=%MFGNAME%

[DestinationDirs]
DefaultDestDir=10,system32\\drivers
DriverDelFiles=10,system32\\drivers
DriverDelFilesNT=12

[DriverDelFiles]
hidusbf.sys

[DriverDelFilesNT]
hidusbf.sys

;------------------------------------------------------------------------------
;  Windows 2000+ Sections
;------------------------------------------------------------------------------

[DefaultInstall.nt]
DelFiles=DriverDelFilesNT

[DefaultInstall.nt.services]
DelService=hidusbf

;------------------------------------------------------------------------------
;  Windows 98+ Sections
;------------------------------------------------------------------------------

[DefaultInstall]
DelFiles=DriverDelFiles

;------------------------------------------------------------------------------
;  String Definitions
;------------------------------------------------------------------------------

[Strings]
MFGNAME="SweetLow"
"""


def test_real_inf_files_pass_in_their_own_mode_and_fail_in_the_other():
    r.check_inf(REAL_INF)
    r.check_inf(REAL_UNINF, uninstall=True)
    with pytest.raises(r.RateError):
        r.check_inf(REAL_INF, uninstall=True)
    with pytest.raises(r.RateError):
        r.check_inf(REAL_UNINF)
    r.check_inf(REAL_INF.replace("\n", "\r\n"))  # 원본은 CRLF


@pytest.mark.parametrize("old,new", [
    ("CopyFiles=DriverCopyFilesNT", "CopyFiles=DriverCopyFilesNT\nRegisterDlls=Evil"),
    ("CopyFiles=DriverCopyFiles\n", "CopyFiles=DriverCopyFiles\nRunPostSetupCommands=Cmd\n"),
    ("[Strings]", "[DefaultInstall.nt.addreg]\nAddReg=Reg\n\n[Strings]"),
    ("hidusbf.sys,,,0x04\n\n[DriverCopyFilesNT]", "evil.sys,,,0x04\n\n[DriverCopyFilesNT]"),
    ("hidusbf.sys,,,0x04\n\n[hidusbfService]", "hidusbf.sys,,evil.sys,0x04\n\n[hidusbfService]"),
    ("hidusbf.sys=1,amd64_as", "evil.sys=1,amd64_as"),
    ("DriverCopyFilesNT=12", "DriverCopyFilesNT=11"),
    ("DefaultDestDir=10,system32\\drivers", "DefaultDestDir=10,system32"),
    ("DefaultDestDir=10,system32\\drivers", "DefaultDestDir=16422"),
    ("AddService=hidusbf,,hidusbfService", "AddService=evil,,hidusbfService"),
    ("ServiceBinary=%12%\\hidusbf.sys", "ServiceBinary=%12%\\evil.sys"),
    ("StartType=3", "StartType=0"),
])
def test_real_install_inf_variants_are_rejected(old, new):
    assert old in REAL_INF
    with pytest.raises(r.RateError):
        r.check_inf(REAL_INF.replace(old, new))


@pytest.mark.parametrize("old,new", [
    ("DelFiles=DriverDelFilesNT", "DelFiles=DriverDelFilesNT\nRegisterDlls=Evil"),
    ("DelService=hidusbf", "DelService=otherservice"),
    ("[DriverDelFilesNT]\nhidusbf.sys", "[DriverDelFilesNT]\nhidusbf.sys\nkernel32.dll"),
    ("DriverDelFilesNT=12", "DriverDelFilesNT=11"),
    ("[Strings]", "[DefaultInstall.nt.addreg]\nDelReg=Reg\n\n[Strings]"),
])
def test_real_uninstall_inf_variants_are_rejected(old, new):
    assert old in REAL_UNINF
    with pytest.raises(r.RateError):
        r.check_inf(REAL_UNINF.replace(old, new), uninstall=True)


@pytest.mark.parametrize("enc", ["ascii", "utf-8", "utf-8-sig", "utf-16"])
def test_read_inf_decodes_ascii_utf8_and_utf16_with_bom(tmp_path, enc):
    f = tmp_path / "a.inf"
    f.write_bytes(REAL_INF.encode(enc))
    assert r._read_inf(f) == REAL_INF
    r.check_inf(r._read_inf(f))


def test_utf16_without_bom_is_refused(tmp_path):
    f = tmp_path / "a.inf"
    f.write_bytes(REAL_INF.encode("utf-16-le"))
    with pytest.raises(r.RateError, match="NUL"):
        r.check_inf(r._read_inf(f))
