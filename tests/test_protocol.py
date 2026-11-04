import pytest

from agk75 import protocol as p


def test_checksum_bit7():
    b = p.encode([p.G_ID])
    assert len(b) == 64 and b[7] == 255 - p.G_ID


def test_checksum_wraps():
    b = p.encode([200, 200, 200, 0, 0, 0, 0])
    assert b[7] == 255 - ((600) & 0xFF)


def test_light_encode_uses_bit8():
    b = p.encode_light(1, 2, 4, 0, (0, 255, 0))
    assert b[:8] == bytes([7, 1, 2, 4, 7, 0, 255, 0])
    assert b[8] == 255 - (sum(b[:8]) & 0xFF)


def test_light_speed_inverted_and_white_mapped():
    b = p.encode_light(2, 3, 4, 1, (255, 255, 255), dazzle=True)
    assert b[2] == 1 and b[4] == 1 << 4 | p.DAZZLE and b[5:8] == b"\xfa\xff\xfa"


def test_light_roundtrip():
    resp = bytes([135]) + p.encode_light(8, 2, 4, 0, (255, 0, 0))[1:8]
    d = p.decode_light(resp)
    assert (d["effect"], d["speed"], d["bright"], d["rgb"], d["dazzle"]) == (8, 2, 4, (255, 0, 0), False)


def test_light_preset_color_nibble():
    d = p.decode_light(bytes([135, 1, 0, 4, 0x03, 9, 9, 9]))
    assert d["rgb"] == p.PRESET_COLORS[3]


def test_sidelight_speed_not_inverted():
    assert p.decode_light(bytes([136, 4, 3, 4, 8, 255, 255, 255]), side=True)["speed"] == 3


def test_distance_conversions():
    assert p.mm_to_byte(1.9) == 18 and p.byte_to_mm(18) == 1.9
    assert p.mm_to_byte(0.0) == 0
    assert p.dead_to_byte(0.3) == 36 and p.byte_to_dead(36) == pytest.approx(0.3)


def test_key_items():
    assert p.key_item(4) == b"\0\0\4\0" and p.hid_of(p.key_item(4)) == 4
    assert p.hid_of(b"\0\xe6\0\0") is None
    assert p.item_name(p.key_item(4)) == "A" and p.item_name(bytes(4)) == "None"


def test_default_layout_names_complete():
    assert 65 not in p.DEFAULT_HID
    assert all(h in p.HID_NAMES for h in p.DEFAULT_HID.values())


def test_dangerous_opcodes_not_allowed():
    for op in (1, 2, 4, 12, 28, 30, 44, 127, 132, 172, 186):
        assert op not in p.ALLOWED


def test_send_rejects_disallowed_opcode_before_io():
    dev = p.Device.__new__(p.Device)  # 하드웨어 없이 검사만
    for op in (172, 127, 186):
        with pytest.raises(ValueError):
            dev.send(bytes([op]))
