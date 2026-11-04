import http.client
import json
import re
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from agk75 import i18n, protocol as P, ratectl
from agk75 import server as s
from test_server import Fake, hub

LIGHT = {"effect": 4, "speed": 2, "bright": 4, "option": 1, "rgb": [255, 0, 0], "dazzle": False}


def holes(text):
    return sorted(re.findall(r"\{\w+\}", text))


def test_server_dictionaries_have_same_keys_and_placeholders():
    ko = i18n.MSG["ko"]
    for lang in ("en", "zh"):
        assert set(i18n.MSG[lang]) == set(ko), lang
        for key, text in i18n.MSG[lang].items():
            assert text and holes(text) == holes(ko[key]), (lang, key)


def test_render_params_nested_messages_and_unknown_keys():
    assert i18n.render("en", "err.int_range", {"name": "idx", "lo": 0, "hi": 127}) == "idx must be an integer from 0 to 127"
    assert i18n.render("zh", "err.hz_choice", {"list": [8000, 4000]}) == "hz 必须是 8000, 4000 之一"
    nested = i18n.Msg("restore.stage.fn")
    assert i18n.render("ko", "restore.back_ok") == "복원 전 프로필로 되돌림"
    assert i18n.render("en", "restore.partial", {"stage": nested, "done": [], "back": nested, "cause": OSError("x")}) \
        .startswith("Partially restored: stopped at the Fn step")
    assert i18n.render("en", "plain English text") == "plain English text"  # 내부 문구는 그대로
    assert i18n.norm("zh-CN") == "zh" and i18n.norm("EN") == "en" and i18n.norm(None) == "ko" and i18n.norm("fr") == "ko"
    assert str(i18n.MsgError("err.no_change")) == "Nothing to change"  # str() 은 영어


def test_default_language_is_korean_and_x_lang_translates_errors():
    bad = {**LIGHT, "effect": 999}
    code, r = s.handle(hub(Fake()), "POST", "/api/light", bad)
    assert code == 400 and r["error"] == "effect 는 0~255 정수여야 합니다"
    code, r = s.handle(hub(Fake()), "POST", "/api/light", bad, lang="en")
    assert code == 400 and r["error"] == "effect must be an integer from 0 to 255"
    code, r = s.handle(hub(Fake()), "POST", "/api/light", bad, lang="zh")
    assert code == 400 and r["error"] == "effect 必须是 0~255 之间的整数"
    assert s.handle(hub(Fake()), "POST", "/api/light", {**LIGHT, "effect": 13}, lang="en")[1]["error"] == "Unknown effect 13"
    assert s.handle(hub(Fake()), "GET", "/api/none", lang="zh")[1]["error"] == "不存在的 API:/api/none"


def test_rate_errors_progress_and_restore_messages_are_translated(monkeypatch):
    h = hub(None)
    assert s.handle(h, "POST", "/api/rate/set", {"hz": 3}, lang="en")[1]["error"] == "hz must be one of 8000, 4000, 2000, 1000"
    h.rate = {"running": True, "step": "rate.step.wait"}
    assert s.handle(h, "GET", "/api/rate/progress", lang="en")[1]["step"] == "Waiting for the device to reconnect…"
    assert s.handle(h, "GET", "/api/rate/progress", lang="zh")[1]["step"] == "正在等待设备重新连接…"

    def boom(*a):
        raise ratectl.RateError("rate.prepare_first")
    monkeypatch.setattr(ratectl, "prepare", boom)
    monkeypatch.setattr(ratectl, "driver_state", lambda: {})
    assert s.handle(h, "POST", "/api/rate/prepare", {}, lang="zh")[1]["error"] == "请先准备驱动"

    monkeypatch.setattr(ratectl, "run_admin", lambda ops: {"ok": False, "ops": [], **ratectl._err("rate.admin_denied", code=5)})
    monkeypatch.setattr(ratectl, "plan_set", lambda hz: [{"op": "restart"}])
    monkeypatch.setattr(ratectl, "reread_usb", lambda: {"error": "usb.no_device"})
    monkeypatch.setattr(ratectl, "admin_pending", lambda r: False)
    code, r = s.handle(h, "POST", "/api/rate/set", {"hz": 4000}, lang="en")
    assert r["message"].startswith("The administrator permission request was denied") and r["usb"]["error"] == "USB device not found"
    assert "error_msg" not in r["admin"]

    err = P.RestoreError("restore.partial", stage=i18n.Msg("restore.stage.light"), done=[i18n.Msg("restore.stage.keymap")],
                         back=i18n.Msg("restore.back_ok"), cause=OSError("down"))
    assert "灯光" in i18n.render("zh", err.key, err.params) and "键位表" in i18n.render("zh", err.key, err.params)


def test_http_server_reads_x_lang_header():
    srv = s.make_server(hub(Fake()))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        def post(lang):
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
            headers = {"Content-Type": "application/json", **({"X-Lang": lang} if lang else {})}
            c.request("POST", "/api/light", json.dumps({**LIGHT, "effect": 999}), headers)
            r = c.getresponse()
            return r.status, json.loads(r.read())["error"]
        assert post(None) == (400, "effect 는 0~255 정수여야 합니다")
        assert post("en") == (400, "effect must be an integer from 0 to 255")
        assert post("zh") == (400, "effect 必须是 0~255 之间的整数")
        c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
        c.request("POST", "/api/light", "{}", {"Content-Type": "text/plain", "X-Lang": "en"})
        assert json.loads(c.getresponse().read())["error"] == "Request not allowed"
    finally:
        srv.shutdown()


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_web_dictionaries_match_and_code_uses_existing_keys():
    names = sorted(set(P.EFFECTS.values()) | set(P.SIDE_EFFECTS.values()))
    script = Path(__file__).parent / "i18n_check.js"
    out = subprocess.run(["node", str(script), json.dumps(names)], capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["keys"] > 150
