import re
from pathlib import Path

from agk75 import i18n, protocol as P
from agk75 import service as s

from test_service import Fake, hub

LIGHT = {"effect": 4, "speed": 2, "bright": 4, "option": 1, "rgb": [255, 0, 0], "dazzle": False}
UI = Path(s.__file__).parent / "ui"


def holes(text):
    return sorted(re.findall(r"\{\w+\}", text))


def test_dictionaries_have_same_keys_and_placeholders():
    ko = i18n.MSG["ko"]
    assert len(ko) > 200
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
    assert i18n.render("ko", "toast.profile", {"n": 3}) == "프로필 3 적용됨"
    assert i18n.render("ko", "toast.profile") == "프로필 {n} 적용됨"  # 값이 없으면 자리표시자를 그대로 둔다


def test_selected_language_translates_errors_for_every_thread():
    bad = {**LIGHT, "effect": 999}

    def message():
        try:
            hub(Fake()).light(**bad)
        except ValueError as e:
            return s.describe_error(e)
    assert message() == "effect 는 0~255 정수여야 합니다"
    i18n.set_lang("en")
    assert message() == "effect must be an integer from 0 to 255"
    i18n.set_lang("zh-CN")
    assert message() == "effect 必须是 0~255 之间的整数"
    with i18n.use("en"):  # 한 스레드만 잠시 다른 언어
        assert message() == "effect must be an integer from 0 to 255"
    assert message() == "effect 必须是 0~255 之间的整数"


def test_rate_errors_and_restore_messages_are_translated():
    h = hub(Fake())
    i18n.set_lang("en")
    try:
        h.rate(hz=3)
    except ValueError as e:
        assert s.describe_error(e) == "hz must be one of 8000, 4000, 2000, 1000, 500, 250"
    assert i18n.t("rate.ok", hz=250) == "Polling rate 250Hz applied (readback matches)"
    i18n.set_lang("zh")
    assert i18n.t("rate.ok", hz=250) == "已应用回报率 250Hz（回读一致）"

    err = P.RestoreError("restore.partial", stage=i18n.Msg("restore.stage.light"), done=[i18n.Msg("restore.stage.keymap")],
                         back=i18n.Msg("restore.back_ok"), cause=OSError("down"))
    assert "灯光" in i18n.render("zh", err.key, err.params) and "键位表" in i18n.render("zh", err.key, err.params)
    assert i18n.render("en", "restore.stage.rate") == "Polling rate"


def test_screen_code_uses_only_existing_keys():
    """ui/*.py 가 t("키") 로 부르는 키가 모두 사전에 있고, 동적으로 만드는 키도 빠짐이 없다."""
    used = set()
    for f in UI.glob("*.py"):
        src = f.read_text(encoding="utf-8")
        used |= set(re.findall(r'\bt\(\s*"([\w.]+)"', src))
        used |= set(re.findall(r'"(nav\.\w+|\w+\.legend)"', src))
        for pair in re.findall(r't\(\s*"([\w.]+)"\s+if\s[^\n]*?else\s+"([\w.]+)"', src):
            used |= set(pair)
    used = {k for k in used if not k.endswith(".")}  # t("mag." + k) 같은 이어 붙이는 키는 아래에서 따로 본다
    ko = i18n.MSG["ko"]
    assert not {k for k in used if k not in ko}, sorted(k for k in used if k not in ko)
    assert len(used) > 120
    for name in set(P.EFFECTS.values()) | set(P.SIDE_EFFECTS.values()):
        assert "fx." + name in ko, name
    for k in ("travel", "lift", "dead", "rt_press", "rt_lift"):
        assert "mag." + k in ko
    for k in ("win_lock", "mac", "wasd_arrow", "led_off", "side_led_off", "keyboard_lock", "fn_matrix", "power_save"):
        assert "opt." + k in ko
    for n in ("keys", "light", "magnet", "misc", "backup"):
        assert "nav." + n in ko


def test_no_leftover_web_server_texts():
    for lang in i18n.LANGS:
        for key in ("cli.url", "err.host", "err.request", "err.body", "err.not_found", "err.network"):
            assert key not in i18n.MSG[lang]
