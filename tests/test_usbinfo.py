import struct

from agk75 import usbinfo as u


def fake(speed, eps):
    b = bytearray(35 + 11 * len(eps))
    b[23] = speed
    struct.pack_into("<l", b, 27, len(eps))  # NumberOfOpenPipes
    struct.pack_into("<l", b, 31, 1)  # ConnectionStatus(파이프 수로 읽으면 안 된다)
    for i, (addr, attr, mps, iv) in enumerate(eps):
        struct.pack_into("<BBBBHB", b, 35 + 11 * i, 7, 5, addr, attr, mps, iv)
    return bytes(b)


def test_high_speed_interval_1_is_8khz():
    r = u.parse_connection_info(fake(2, [(0x81, 3, 64, 1)]))
    assert r == {"speed": "High", "endpoints": [{"address": "0x81", "interval": 1, "max_packet": 64}],
                 "poll_us": 125, "max_hz": 8000}


def test_interval_scaling_and_full_speed():
    assert u.parse_connection_info(fake(2, [(0x81, 3, 64, 4)]))["max_hz"] == 1000
    assert u.parse_connection_info(fake(1, [(0x81, 3, 64, 1)]))["max_hz"] == 1000
    assert "error" in u.parse_connection_info(fake(2, [(0x02, 2, 64, 0)]))


def test_pipe_count_is_read_from_offset_27_and_all_pipes_parsed():
    r = u.parse_connection_info(fake(2, [(0x02, 2, 64, 0), (0x81, 3, 64, 3)]))
    assert [e["address"] for e in r["endpoints"]] == ["0x02", "0x81"] and r["poll_us"] == 500
