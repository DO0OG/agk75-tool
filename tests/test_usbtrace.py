import json
import os
import random
import threading

import pytest

from agk75 import i18n, usbtrace as u

JOB = "3f2b8c1e-5a7d-4e6f-9a0b-1c2d3e4f5a6b"

# 실측 표(코드별 약 1000건): 대역 안 간격 + 이론 주기의 배수 + 앞 패킷 완료 기록이 늦어 생기는 이상치
TABLE = {
    3: (1000, 1.0, (0.96, 1.0), (0.868, 0.929)),
    2: (2000, 0.5, (0.47, 0.50), (0.394,)),
    1: (4000, 0.25, (0.22, 0.25), (0.043, 0.077, 0.148, 0.188)),
    0: (8000, 0.125, (0.117, 0.122), (0.032, 0.066, 0.090)),
}


def fixture(period, band, outliers, n=1000, seed=3):
    rnd = random.Random(seed)
    gaps = [rnd.uniform(*band) for _ in range(n - 60)]
    gaps += [period * rnd.randint(2, 4) + rnd.uniform(-0.01, 0.01) for _ in range(60 - len(outliers))]
    gaps += list(outliers) + [rnd.uniform(5, 300) for _ in range(40)]  # 키를 뗀 뒤 긴 간격
    rnd.shuffle(gaps)
    return gaps


@pytest.mark.parametrize("code", sorted(TABLE))
def test_measured_distributions_give_exact_rate(code):
    hz, period, band, outliers = TABLE[code]
    r = u.analyze_gaps(fixture(period, band, outliers))
    assert (r["hz"], r["period_ms"], r["note"]) == (hz, period, "ok"), r
    assert r["band_count"] > 800 and 0.85 * period <= r["min_ms"] <= r["max_ms"] <= band[1] + 1e-9


def test_slow_rates_from_earlier_period_measurement():
    for hz, period in ((500, 2.0), (250, 4.0)):
        gaps = [period] * 200 + [period * 2] * 30
        assert u.analyze_gaps(gaps)["hz"] == hz


def test_few_or_missing_short_gaps_are_not_judged():
    r = u.analyze_gaps([0.5] * 29 + [300.0] * 100)
    assert r["hz"] is None and r["note"] == "insufficient" and r["samples"] == 29
    assert u.analyze_gaps([])["note"] == "insufficient" and u.analyze_gaps([50.0] * 99)["min_ms"] is None
    rnd = random.Random(5)  # 짧은 간격은 충분하지만 어느 대역에도 몰리지 않음
    assert u.analyze_gaps([rnd.uniform(0.01, 0.1) for _ in range(300)])["hz"] is None


def test_small_band_is_reported_as_minimum():
    r = u.analyze_gaps([2.0] * 12 + [4.0] * 30)
    assert (r["hz"], r["band_count"], r["note"]) == (500, 12, "few")
    assert u.analyze_gaps([1.0] * 49 + [2.0] * 40)["note"] == "few"
    assert u.analyze_gaps([1.0] * 50 + [2.0] * 40)["note"] == "ok"


def test_many_short_outliers_reject_the_band():
    # 대역보다 짧은 간격이 상위 표본의 10% 를 넘으면 그 주기를 최소 주기로 보지 않는다
    r = u.analyze_gaps([0.5] * 100 + [0.3] * 20 + [1.0] * 40)
    assert r["period_ms"] != 0.5


def test_endpoints_are_analyzed_separately():
    hz, period, band, outliers = TABLE[0]
    data = {"endpoints": [{"ep": 0x82, "events": 40, "gaps_ms": [3.0] * 5},
                          {"ep": 0x81, "events": 1000, "gaps_ms": fixture(period, band, outliers)}]}
    s = u.summarize(data)
    assert [e["ep"] for e in s["endpoints"]] == [0x82, 0x81]
    assert s["endpoints"][0]["hz"] is None and s["best"]["ep"] == 0x81 and s["best"]["hz"] == 8000
    assert len(s["best"]["hist"]) == 16 and sum(s["best"]["hist"]) > 900
    assert u.summarize({"endpoints": []})["best"] is None
    assert u.summarize({"endpoints": data["endpoints"][:1]})["best"]["hz"] is None


def test_histogram_bins_are_0125ms_up_to_2ms():
    h = u.histogram([0.0, 0.05, 0.125, 0.2, 1.99, 2.0, 3.0])
    assert len(h) == 16 and h[0] == 1 and h[1] == 2 and h[15] == 1 and sum(h) == 4


# ---------------------------------------------------------------- 작업 파일
@pytest.fixture
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    d = u.job_dir()
    d.mkdir(parents=True)
    return d


def make_job(d, content, name=JOB + ".ops.json"):
    p = d / name
    p.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return p


def test_read_job_accepts_only_the_job_name_in_the_job_folder(appdata, tmp_path):
    p = make_job(appdata, {"seconds": 15})
    sec, res = u.read_job(str(p))
    assert sec == 15 and res == str(appdata / (JOB + ".result.json"))
    assert u.read_job(str(appdata / ".." / "admin" / p.name))[0] == 15  # 표기가 달라도 실제 위치로 비교
    for q in (tmp_path / p.name, appdata.parent / p.name):
        q.write_text('{"seconds": 15}', encoding="utf-8")
        with pytest.raises(ValueError):
            u.read_job(str(q))
    for name in ("job.json", "evil.ops.json", JOB + ".ops.json.bak", "x" + JOB + ".ops.json"):
        with pytest.raises(ValueError):
            u.read_job(str(make_job(appdata, {"seconds": 15}, name)))
    for bad in ("", str(appdata), str(appdata / "missing.ops.json")):
        with pytest.raises((ValueError, OSError)):
            u.read_job(bad)


@pytest.mark.parametrize("content", [
    {"seconds": 2}, {"seconds": 61}, {"seconds": "15"}, {"seconds": 15.0}, {"seconds": True}, {"seconds": None},
    {"seconds": 15, "cmd": "calc.exe"}, {"cmd": "calc.exe"}, {}, [15], "15", "not json", "",
    {"seconds": 15, "pad": "x" * 300}])
def test_read_job_rejects_bad_content(appdata, content):
    with pytest.raises(ValueError):
        u.read_job(str(make_job(appdata, content if isinstance(content, str) else json.dumps(content))))


def test_read_job_bounds(appdata):
    assert u.read_job(str(make_job(appdata, {"seconds": 3})))[0] == 3
    assert u.read_job(str(make_job(appdata, {"seconds": 60})))[0] == 60


# ---------------------------------------------------------------- 관리자 쪽 흐름(가짜 _run)
class World:
    def __init__(self, tmp_path, monkeypatch, fail_start=False):
        self.calls, self.fail_start = [], fail_start
        self.win = tmp_path / "win"
        (self.win / "Temp").mkdir(parents=True)
        monkeypatch.setattr(u, "_windir", lambda: str(self.win))
        monkeypatch.setattr(u, "_run", self.run)
        monkeypatch.setattr(u.time, "sleep", lambda s: self.calls.append("sleep:%s" % s))
        monkeypatch.setattr(u, "parse_etl_xml", lambda path, vid, pid: {0x81: [i * 125_000 for i in range(5)]})

    def run(self, cmd):
        assert cmd[0].startswith(str(self.win / "System32"))  # 고정 경로
        name = os.path.basename(cmd[0])
        self.calls.append("tracerpt" if name == "tracerpt.exe" else cmd[1])
        if name == "tracerpt.exe":
            assert os.path.dirname(cmd[1]).startswith(str(self.win / "Temp"))  # 새로 만든 폴더
            open(cmd[cmd.index("-o") + 1], "w").close()
        rc = 1 if self.fail_start and cmd[1] == "start" else 0
        return type("R", (), {"returncode": rc, "stdout": b"", "stderr": b"denied"})()


def test_admin_run_order_result_path_and_cleanup(appdata, tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    assert u.admin_main(str(make_job(appdata, {"seconds": 7}))) == 0
    assert w.calls == ["stop", "start", "sleep:7", "stop", "tracerpt", "stop"]
    res = json.loads((appdata / (JOB + ".result.json")).read_text("utf-8"))
    assert res == {"ok": True, "endpoints": [{"ep": 0x81, "events": 5, "gaps_ms": [0.125] * 4}]}
    assert os.listdir(w.win / "Temp") == []  # 임시 ETL·XML 폴더가 지워짐


def test_admin_failure_still_stops_session_cleans_and_reports(appdata, tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, fail_start=True)
    assert u.admin_main(str(make_job(appdata, {"seconds": 5}))) == 0
    assert w.calls == ["stop", "start", "stop"]
    res = json.loads((appdata / (JOB + ".result.json")).read_text("utf-8"))
    assert res["ok"] is False and "logman start failed" in res["error"]
    assert os.listdir(w.win / "Temp") == []


def test_admin_interrupted_wait_still_stops_session(appdata, tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)

    def boom(_):
        raise KeyboardInterrupt
    monkeypatch.setattr(u.time, "sleep", boom)
    with pytest.raises(KeyboardInterrupt):
        u.admin_main(str(make_job(appdata, {"seconds": 5})))
    assert w.calls == ["stop", "start", "stop", "stop"]
    assert os.listdir(w.win / "Temp") == [] and not list(appdata.glob("*.result.json"))


def test_admin_rejected_job_runs_and_writes_nothing(appdata, tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    assert u.admin_main(str(make_job(appdata, {"seconds": 99}))) == 2
    assert u.admin_main(str(make_job(appdata, {"seconds": 5, "cmd": "x"}, "evil.ops.json"))) == 2
    assert u.admin_main("") == 2
    assert w.calls == [] and os.listdir(w.win / "Temp") == [] and not list(appdata.glob("*.result.json"))


def test_admin_does_not_overwrite_an_existing_result(appdata, tmp_path, monkeypatch):
    World(tmp_path, monkeypatch)
    job = make_job(appdata, {"seconds": 5})
    existing = appdata / (JOB + ".result.json")
    existing.write_text("planted", encoding="utf-8")
    assert u.admin_main(str(job)) == 3
    assert existing.read_text("utf-8") == "planted"


# ---------------------------------------------------------------- 일반 권한 쪽
def test_request_cleans_files_and_returns_result(appdata, monkeypatch):
    seen = {}

    def elevate(job, on_launched, wait):
        seen["wait"] = wait
        assert job.parent == appdata and job.name.endswith(".ops.json") and json.loads(job.read_text()) == {"seconds": 15}
        on_launched()
        (job.parent / job.name.replace(".ops.", ".result.")).write_text(json.dumps({"ok": True, "endpoints": []}))
        return 0
    monkeypatch.setattr(u, "_elevate", elevate)
    launched = []
    assert u.request(15, lambda: launched.append(1)) == {"ok": True, "endpoints": []}
    assert launched == [1] and seen["wait"] > 15 and os.listdir(appdata) == []


@pytest.mark.parametrize("body,key", [(None, "err.trace_nofile"), ("garbage", "err.trace_bad"),
                                      ('{"ok": true, "endpoints": [{"ep": 1}]}', "err.trace_bad"),
                                      ('{"ok": false, "error": "RuntimeError: x"}', "err.trace_run")])
def test_request_failures_are_messages_and_files_are_removed(appdata, monkeypatch, body, key):
    def elevate(job, on_launched, wait):
        if body is not None:
            (job.parent / job.name.replace(".ops.", ".result.")).write_text(body)
        return 1
    monkeypatch.setattr(u, "_elevate", elevate)
    with pytest.raises(i18n.MsgError) as e:
        u.request(15)
    assert e.value.key == key and os.listdir(appdata) == []


def test_request_elevation_error_still_removes_job(appdata, monkeypatch):
    def elevate(job, on_launched, wait):
        raise i18n.MsgError("err.trace_uac", code=1223)
    monkeypatch.setattr(u, "_elevate", elevate)
    with pytest.raises(i18n.MsgError):
        u.request(15)
    assert os.listdir(appdata) == []


def test_tracer_status_and_errors(monkeypatch):
    t = u.Tracer()
    assert t.status()["running"] is False and t.status()["result"] is None
    go = threading.Event()

    def fake(seconds, on_launched):
        on_launched()
        go.wait(5)
        return {"endpoints": [{"ep": 0x81, "events": 1, "gaps_ms": []}]}
    monkeypatch.setattr(u, "request", fake)
    t.start(15)
    st = t.status()
    assert st["running"] and st["seconds"] == 15 and st["phase"] in ("uac", "capture")
    with pytest.raises(i18n.MsgError):
        t.start(15)  # 이미 측정 중
    go.set()
    t.thread.join(5)
    st = t.status()
    assert not st["running"] and st["error"] is None and st["result"]["best"]["ep"] == 0x81

    def bad(seconds, on_launched):
        raise i18n.MsgError("err.trace_uac", code=1223)
    monkeypatch.setattr(u, "request", bad)
    t.start(15)
    t.thread.join(5)
    assert t.status()["error"].key == "err.trace_uac" and t.status()["result"] is None


XML = '<Events xmlns="http://schemas.microsoft.com/win/2004/08/events/event">\n{}</Events>'


def ev(guid, eid, ts, **data):
    d = "".join('<Data Name="%s">%s</Data>' % kv for kv in data.items())
    return ('<Event><System><Provider Guid="%s"/><EventID>%d</EventID><TimeCreated SystemTime="%s"/></System>'
            '<EventData>%s</EventData></Event>\n' % (guid, eid, ts, d))


def test_parse_keeps_only_this_devices_interrupt_in_endpoints(tmp_path):
    x, c = "{30E1D284-5D88-459C-83FD-6345B39B19EC}", "{36DA592D-E43A-4E28-AF6F-4BC57C5A11E8}"
    t = "2026-11-05T01:02:03.%09dZ"
    rows = [ev(x, 4, t % 0, fid_UsbDevice="D1", fid_idVendor="0x3151", fid_idProduct="0x5009"),
            ev(x, 4, t % 0, fid_UsbDevice="D2", fid_idVendor="0x046d", fid_idProduct="0xc52b"),
            ev(c, 6, t % 0, fid_PipeHandle="P1", fid_UsbDevice="D1", fid_bEndpointAddress="0x81", fid_bmAttributes="0x03"),
            ev(c, 6, t % 0, fid_PipeHandle="P2", fid_UsbDevice="D1", fid_bEndpointAddress="0x02", fid_bmAttributes="0x02"),
            ev(c, 6, t % 0, fid_PipeHandle="P3", fid_UsbDevice="D2", fid_bEndpointAddress="0x81", fid_bmAttributes="0x03")]
    for ph, ud, ns in (("P1", "D1", 1000), ("P1", "D1", 126000), ("P2", "D1", 5000), ("P3", "D2", 7000), ("P9", "D1", 9000)):
        rows.append(ev(c, 27, t % ns, fid_PipeHandle=ph, fid_UsbDevice=ud))
    path = tmp_path / "t.xml"
    path.write_text(XML.format("".join(rows)), encoding="utf-8")
    eps = u.parse_etl_xml(str(path), 0x3151, 0x5009)
    assert list(eps) == [0x81] and eps[0x81][1] - eps[0x81][0] == 125000
    assert u._gaps(eps[0x81] + [eps[0x81][1] + 20_000_000]) == [0.125]  # 10ms 이상은 남기지 않음
