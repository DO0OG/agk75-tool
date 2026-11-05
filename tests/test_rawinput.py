import random
import sys

import pytest

from agk75 import rawinput as r


def multiples(period, n, seed=1, jitter=0.12, max_k=6):
    """period ms 의 배수 간격 + 지터(키를 번갈아 칠 때 보이는 모양)."""
    rnd = random.Random(seed)
    return [period * rnd.randint(1, max_k) + rnd.uniform(-jitter, jitter) for _ in range(n)]


def test_analyze_periodicity_picks_250_500_1000():
    for period, hz in ((4, 250), (2, 500), (1, 1000)):
        res = r.analyze([g for g in multiples(period, 300) if g >= 1.5] + [4.0] * 5)
        assert res["enough"] and res["hz"] == hz and res["faster"] is False, (period, res["r"])
    res = r.analyze([4.0 + 0.1 * ((i * 7) % 5 - 2) / 2 for i in range(80)])
    assert res["hz"] == 250 and res["r"][4] > 0.9  # 큰 주기부터 본다


def test_analyze_random_gaps_mean_faster_than_1000hz():
    rnd = random.Random(7)
    res = r.analyze([rnd.uniform(1.5, 28.0) for _ in range(300)])
    assert res["enough"] and res["hz"] is None and res["faster"] is True
    assert all(v < r.R_MIN for v in res["r"].values())


def test_analyze_needs_50_usable_gaps():
    res = r.analyze([4.0] * 49)
    assert res["enough"] is False and res["hz"] is None and res["faster"] is False and res["r"] == {}
    assert r.analyze([4.0] * 50)["hz"] == 250
    # 1.5ms 미만(메시지 처리 지연)과 28ms 이상(자동 반복 31ms 대)은 표본이 아니다
    res = r.analyze([0.3] * 100 + [31.0] * 100 + [4.0] * 49)
    assert res["samples"] == 49 and res["enough"] is False
    assert r.analyze([])["samples"] == 0


def test_analyze_histogram_is_1ms_bins_up_to_16ms():
    res = r.analyze([0.01, 0.3, 0.9, 1.0, 1.5, 3.99, 4.0, 15.99, 16.0, 31.0])
    counts = [h["count"] for h in res["hist"]]
    assert len(counts) == 16 and [h["label"] for h in res["hist"]][:2] == ["0~1", "1~2"]
    assert counts[0] == 2 and counts[1] == 2 and counts[3] == 1 and counts[4] == 1 and counts[15] == 1
    assert sum(counts) == 7  # 0.01ms(한 리포트 안의 이벤트)와 16ms 이상은 뺀다


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 전용")
def test_message_window_create_and_destroy_without_registering_raw_input():
    assert r.probe() is True  # RegisterRawInputDevices 는 호출하지 않는다
