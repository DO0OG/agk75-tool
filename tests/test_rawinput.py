import sys

import pytest

from agk75 import rawinput as r


def test_analyze_cluster_estimate_and_lower_bound():
    res = r.analyze([0.125] * 40 + [0.5] * 20 + [3.0])
    assert res["hz_estimate"] == 8000 and res["hz_at_least"] == 8000 and res["cluster_n"] == 40
    assert [h["count"] for h in res["hist"]] == [0, 40, 0, 20, 0, 1]
    assert r.analyze([1.0] * 60)["hz_estimate"] == 1000
    assert r.analyze([8.0] * 60)["hz_at_least"] == 125
    jit = [k * 1.0 + 0.04 * ((i * 7) % 5 - 2) / 2 for i, k in enumerate([1, 2, 1, 3, 1, 4, 1, 2] * 10)]
    assert r.analyze(jit)["hz_estimate"] == 1000


def test_analyze_needs_enough_samples_and_drops_same_report_events():
    res = r.analyze([1.0] * 49)
    assert res["enough"] is False and res["hz_estimate"] is None
    res = r.analyze([0.01] * 100 + [1.0] * 50)  # 한 리포트에 든 이벤트(0.05ms 미만)는 버린다
    assert res["samples"] == 50 and res["min_ms"] == 1.0
    assert r.analyze([])["min_ms"] is None


def test_analyze_real_measurement_is_not_1000hz():
    xs = [2.5 + i * 0.01 for i in range(412)] + [1.1 + i * 0.05 for i in range(18)]
    xs += [0.5 + i * 0.04 for i in range(12)] + [0.297, 0.31, 0.33, 0.36, 0.4, 0.42, 0.45, 0.49]
    res = r.analyze(xs)
    assert res["min_ms"] == 0.297 and res["hz_estimate"] != 1000 and res["hz_at_least"] >= 2000


def test_analyze_lone_outlier_is_not_enough():
    res = r.analyze([8.0] * 99 + [0.06])  # 이상치 하나로 8000Hz 가 되거나 8ms 묶음으로 넘어가면 안 된다
    assert res["cluster_n"] == 0 and res["hz_at_least"] is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 전용")
def test_message_window_create_and_destroy_without_registering_raw_input():
    assert r.probe() is True  # RegisterRawInputDevices 는 호출하지 않는다
