"""화면 스모크 시험: QT_QPA_PLATFORM=offscreen(보이는 창 없음)에서 가짜 키보드로 돌린다."""
import re
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QFrame, QLabel  # noqa: E402

from agk75 import i18n  # noqa: E402
from agk75 import service as s  # noqa: E402
from agk75.ui import keys_page  # noqa: E402
from agk75.ui.app import make_app  # noqa: E402
from agk75.ui.main_window import MainWindow  # noqa: E402

from fakedev import FakeKeyboard  # noqa: E402

UI = Path(s.__file__).parent / "ui"
PAGES = ("keys", "light", "magnet", "misc", "backup")


def pump(app, cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return False


def toasts(win):
    lay = win.toasts.layout()
    return [lay.itemAt(i).widget().text() for i in range(lay.count())]


@pytest.fixture
def env(tmp_path):
    app = make_app()
    dev = FakeKeyboard()
    state = {"plugged": True}

    def opener():
        if not state["plugged"]:
            raise OSError("AGK75 not found")
        return dev
    svc = s.Service(opener=opener, backup_dir=tmp_path, factory_dir=tmp_path)
    win = MainWindow(svc, QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat), poll_ms=600000)
    assert pump(app, lambda: win.s is not None), "상태를 읽지 못했습니다"
    win.confirm = lambda text: True  # 확인 대화상자는 항상 승낙
    yield app, win, dev, state
    win.close()
    app.processEvents()


def test_five_pages_build_and_three_languages_redraw(env):
    app, win, dev, _ = env
    for lang in ("ko", "en", "zh", "en"):
        win.set_lang(lang)
        assert i18n.lang() == lang and win.windowTitle() == i18n.t("app.title")
        for name in PAGES:
            win.show_view(name)
            assert pump(app, lambda: True)
            assert win.stack.currentWidget() is win.scrolls[name]
            assert win.nav[name].text().replace("&&", "&").replace("\n", " ") == i18n.t("nav." + name)
        assert win.settings.value("lang") == lang  # QSettings 에 기억한다
    assert win.lang_seg.buttons["en"].isChecked()
    assert win.stage.isHidden() is True  # 마지막 화면(backup)은 키보드 그림이 없다


def test_language_choice_is_restored_from_settings(tmp_path):
    make_app()
    ini = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    ini.setValue("lang", "zh")
    win = MainWindow(s.Service(opener=FakeKeyboard, backup_dir=tmp_path, factory_dir=tmp_path), ini, poll_ms=600000)
    try:
        assert i18n.lang() == "zh" and win.lang_seg.buttons["zh"].isChecked()
    finally:
        win.close()


def test_every_device_call_runs_on_the_worker_thread(env):
    app, win, dev, _ = env
    win.select(8, False, False)
    win.pages["keys"].apply(20)
    win.run(win.svc.poll, lambda *a: None)
    assert pump(app, lambda: ("key", 0, 8, bytes([0, 0, 20, 0])) in dev.writes)
    assert pump(app, lambda: not win.worker.busy())
    assert dev.threads and threading.get_ident() not in dev.threads
    assert len(dev.threads) == 1  # 단일 작업 스레드가 전부 직렬로 처리한다
    assert win.s["keymap"][0][8] == [0, 0, 20, 0]


def test_invalid_input_is_rejected_with_translated_red_toast(env):
    app, win, dev, _ = env
    win.set_lang("en")
    res = []
    win.run(lambda: win.svc.key(layer=9, idx=8, hid=20), lambda r, e: res.append(win.report(r, e)))
    assert pump(app, lambda: res)
    assert res == [False] and dev.writes == []
    assert "layer must be an integer from 0 to 3" in toasts(win)[-1]
    kinds = [win.toasts.layout().itemAt(i).widget().property("kind") for i in range(win.toasts.layout().count())]
    assert kinds[-1] == "bad"


def test_readback_mismatch_shows_red_banner(env):
    app, win, dev, _ = env
    assert win.report({"applied": False}, None) is False
    assert win.banner.isHidden() is False and win.banner.text() == i18n.t("banner.mismatch")
    assert win.report({"applied": True}, None) is True and win.banner.isHidden()


def test_light_changes_are_debounced_and_sent_once(env):
    app, win, dev, _ = env
    win.show_view("light")
    zone = win.pages["light"].main
    for v in (1, 2, 4):
        zone._set("bright", v)
    assert not [w for w in dev.writes if w[0] == "light"]  # 300ms 안에는 보내지 않는다
    assert pump(app, lambda: [w for w in dev.writes if w[0] == "light"])
    pump(app, lambda: False, 0.4)
    assert len([w for w in dev.writes if w[0] == "light"]) == 1
    assert win.s["light"]["bright"] == 4


def test_magnet_apply_selected_and_all_with_progress(env):
    app, win, dev, _ = env
    win.show_view("magnet")
    page = win.pages["magnet"]
    page._select({0, 1})
    page.rows["travel"].slider.setValue(15)  # 사용자가 슬라이더를 움직인 것과 같다
    page.apply_keys()
    assert pump(app, lambda: len([w for w in dev.writes if w[0] == "magnet"]) == 2)
    assert pump(app, lambda: not page.busy)
    assert {w[1] for w in dev.writes if w[0] == "magnet"} == {0, 1} and win.s["magnet"][1]["travel"] == 1.5
    page.rows["lift"].slider.setValue(20)
    page.apply_everything()
    assert pump(app, lambda: not page.busy and win.long_jobs == 0)
    assert len([w for w in dev.writes if w[0] == "magnet"]) == 2 + 128
    assert page.bar.value() == 100 and win.s["magnet"][127]["lift"] == 2.0


def test_disconnect_then_reconnect_reloads_state(env):
    app, win, dev, plugged = env
    plugged["plugged"] = False
    win.svc.drop()
    win._poll()
    assert pump(app, lambda: win.conn is False)
    plugged["plugged"] = True
    win._poll()
    assert pump(app, lambda: win.conn is True and win.reconn == 1 and win.s is not None and not win.loading)
    win.s = None  # 읽기에 실패한 상태에서 연결이 돌아오면 다시 읽는다
    win.svc.drop()
    win._poll()
    assert pump(app, lambda: win.s is not None)


def test_write_failure_marks_disconnected_and_shows_error(env):
    app, win, dev, plugged = env
    plugged["plugged"] = False
    win.svc.drop()
    win.select(8, False, False)
    win.pages["keys"].apply(20)
    assert pump(app, lambda: win.conn is False)
    assert any("장치 통신 오류" in t or "Device communication" in t for t in toasts(win))


def test_close_stops_worker_and_closes_device(env):
    app, win, dev, _ = env
    assert win.close() is True
    assert win.worker.isFinished() and dev.closed  # 장치는 작업 스레드가 닫는다


def test_close_asks_for_confirmation_while_restore_job_runs(env):
    app, win, dev, _ = env
    win.long_start()
    win.confirm = lambda text: False
    assert win.close() is False and win.worker.isRunning()
    win.confirm = lambda text: text == i18n.t("close.busy")
    assert win.close() is True and win.worker.isFinished()


def test_restore_runs_on_worker_and_reports_result(env, monkeypatch):
    app, win, dev, _ = env
    (win.svc.backup_dir / "backup_20260101_000000.json").write_text("{}", "utf-8")
    monkeypatch.setattr(win.svc, "restore", lambda **kw: {"applied": True, "skipped": [], "diff": []})
    win.show_view("backup")
    page = win.pages["backup"]
    assert pump(app, lambda: page.listw.count() == 1)
    page.listw.setCurrentRow(0)
    assert page.restore_btn.isEnabled()
    page.restore()
    assert win.long_jobs == 1
    assert pump(app, lambda: win.long_jobs == 0)
    assert pump(app, lambda: page.state_lbl.text() == i18n.t("backup.verified"))


def test_rate_card_shows_current_value_and_applies_through_worker(env):
    app, win, dev, _ = env
    win.show_view("keys")
    card = win.pages["keys"].rate
    seg = next(w for w in card.frame.findChildren(QFrame) if w.property("seg"))
    assert list(seg.buttons) == [8000, 4000, 2000, 1000, 500, 250] and seg.buttons[8000].isChecked()
    texts = [w.text() for w in card.frame.findChildren(QLabel)]
    assert i18n.t("rate.note") in texts and i18n.t("rate.cur", n=1, hz=8000) in texts
    assert not any(re.search(r"드라이버|재부팅|안티치트", x) for x in texts)
    card.apply(500)
    assert pump(app, lambda: ("rate", 500, 0) in dev.writes and not card.busy)
    assert win.s["rate"] == 500 and threading.get_ident() not in dev.threads  # 작업 스레드에서 썼다
    assert i18n.t("rate.ok", hz=500) in toasts(win)
    seg = next(w for w in card.frame.findChildren(QFrame) if w.property("seg"))
    assert seg.buttons[500].isChecked()


def test_rate_card_reports_mismatch_and_profile_switch_refreshes_value(env, monkeypatch):
    app, win, dev, _ = env
    win.show_view("keys")
    card = win.pages["keys"].rate
    monkeypatch.setattr(dev, "set_rate", lambda hz, profile=0: 8000)
    card.apply(250)
    assert pump(app, lambda: not card.busy and win.s["rate"] == 8000)
    assert any(i18n.t("rate.mismatch", want=250, got=8000) == x for x in toasts(win))
    dev.rates[1] = 1000
    win._set_profile(1)
    assert pump(app, lambda: win.s["profile"] == 1 and win.s["rate"] == 1000)
    assert i18n.t("rate.cur", n=2, hz=1000) in [w.text() for w in card.frame.findChildren(QLabel)]
    dev.profile, dev.rates[3] = 3, 250  # 키보드에서 직접 프로필을 바꾼 경우(폴링)
    win._poll()
    assert pump(app, lambda: win.s["profile"] == 3 and win.s["rate"] == 250)


def test_key_press_mapping_uses_physical_scan_codes():
    h = keys_page.hid_from_scan
    assert h(0x10) == 20 and h(0x1E) == 4 and h(0x2C) == 29 and h(0x02) == 30 and h(0x0B) == 39
    assert h(0x2A) == 225 and h(0x36) == 229 and h(0x1D) == 224 and h(0x11D) == 228 and h(0x138) == 230
    assert h(0x3B) == 58 and h(0x58) == 69 and h(0x148) == 82
    assert h(0, 0x01000000 + 0) is None


def test_screen_code_never_touches_device_threads_directly():
    for f in UI.glob("*.py"):
        src = f.read_text(encoding="utf-8")
        assert not re.search(r"time\.sleep|import hid|subprocess|ctypes", src), f.name
        assert len(src.splitlines()) <= 400, f.name


def _center(win, idx):
    from PySide6.QtCore import QPoint
    from agk75.ui.layout import LAYOUT
    _, x, y, w = next(k for k in LAYOUT if k[0] == idx)
    r = win.kb._rect(x, y, w)
    return QPoint(int(r.center().x()), int(r.center().y()))


def test_keyboard_click_ctrl_click_and_drag_select_keys(env):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    app, win, dev, _ = env
    win.show()
    win.show_view("magnet")
    assert win.sel == {0}
    QTest.mouseClick(win.kb, Qt.LeftButton, Qt.NoModifier, _center(win, 8))
    assert win.sel == {8}
    QTest.mouseClick(win.kb, Qt.LeftButton, Qt.ControlModifier, _center(win, 9))
    assert win.sel == {8, 9}
    QTest.mouseClick(win.kb, Qt.LeftButton, Qt.ControlModifier, _center(win, 8))
    assert win.sel == {9}
    QTest.mousePress(win.kb, Qt.LeftButton, Qt.NoModifier, _center(win, 7))
    for idx in (13, 19):  # 끌면서 지나가는 키가 추가된다
        QTest.mouseMove(win.kb, _center(win, idx))
    QTest.mouseRelease(win.kb, Qt.LeftButton, Qt.NoModifier, _center(win, 19))
    assert win.sel == {7, 13, 19}
    win.show_view("keys")
    QTest.mouseClick(win.kb, Qt.LeftButton, Qt.NoModifier, QPoint(1, 1))  # 빈 곳 클릭은 무시
    assert win.sel == set()
    QTest.mouseClick(win.kb, Qt.LeftButton, Qt.NoModifier, _center(win, 65))  # Fn 키는 흐리게 잠겨 있다
    assert win.sel == set()
    QTest.mouseClick(win.kb, Qt.LeftButton, Qt.NoModifier, _center(win, 8))
    assert win.sel == {8}


@pytest.mark.parametrize("size,min_u", [((1280, 800), 44), ((1100, 700), 30)])
def test_whole_keyboard_is_visible_without_scrolling(env, size, min_u):
    app, win, dev, _ = env
    win.resize(*size)
    win.show()
    for name in ("keys", "light", "magnet"):
        win.show_view(name)
        pump(app, lambda: False, 0.1)
        assert win.kb.u >= min_u
        assert win.kb.width() >= win.kb.u * 16 and win.kb.geometry().bottom() <= win.stage.height()
        assert win.kb.mapTo(win, win.kb.rect().bottomRight()).y() < win.height()


def test_measure_card_draws_result_phases_and_errors_in_three_languages(env):
    from agk75 import usbtrace
    app, win, dev, _ = env
    win.show_view("misc")
    page = win.pages["misc"]
    ep = usbtrace.analyze_gaps([0.12] * 100 + [0.25] * 30)
    ep.update(ep=0x81, events=130, hist=usbtrace.histogram([0.12] * 100))
    none = usbtrace.analyze_gaps([])
    none.update(ep=0x82, events=0, hist=usbtrace.histogram([]))
    result = {"endpoints": [ep, none], "best": ep}
    base = {"running": False, "phase": "", "seconds": 15, "remaining": 0.0, "error": None}

    def text():
        lay = page.mres.layout()
        return " | ".join(lay.itemAt(i).widget().text() for i in range(lay.count()) if lay.itemAt(i).widget()
                          and hasattr(lay.itemAt(i).widget(), "text"))
    for lang in ("ko", "en", "zh"):
        win.set_lang(lang)
        win.show_view("misc")
        page = win.pages["misc"]
        page.draw_measure({**base, "result": result})
        out = text()
        assert "8000" in out and "0x81" in out and "0x82" in out and "{" not in out, out
        assert ("8000Hz" in out) and ("%dHz" % win.s["rate"] in out)  # 설정값과의 비교 줄
        for state in ({"running": True, "phase": "uac", "remaining": 15.0, "result": None},
                      {"running": True, "phase": "capture", "remaining": 7.2, "result": None},
                      {"running": True, "phase": "analyze", "remaining": 0.0, "result": None},
                      {"result": {"endpoints": [], "best": None}},
                      {"result": {"endpoints": [none], "best": none}},
                      {"result": None, "error": "boom"}):
            page.draw_measure({**base, **state})
            assert "{" not in text()
    page.draw_measure({**base, "result": None, "error": "boom"})
    assert text() == "boom"
