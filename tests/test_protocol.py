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
    for op in (1, 2, 12, 28, 30, 44, 127, 172, 186):
        assert op not in p.ALLOWED


def test_rate_opcodes_allowed():
    assert {p.G_RATE, p.S_RATE} == {132, 4} and {132, 4} <= p.ALLOWED
    assert p.RATE_CODES == {8000: 0, 4000: 1, 2000: 2, 1000: 3, 500: 4, 250: 5}  # 코드 6 은 쓰지 않는다


def test_send_rejects_disallowed_opcode_before_io():
    dev = p.Device.__new__(p.Device)  # 하드웨어 없이 검사만
    for op in (172, 127, 186):
        with pytest.raises(ValueError):
            dev.send(bytes([op]))


DEFAULT_FN = {  # 기본 Fn 레이어: 키 번호 -> 4바이트 항목, (한국어 이름, 영어 이름, 중국어 이름)
    0: ((10, 2, 0, 0), "초기화 (설정이 지워질 수 있음)", "Reset (may erase settings)", "初始化（可能清除设置）"),
    6: ((3, 0, 112, 0), "화면 밝기 −", "Screen brightness −", "屏幕亮度 −"),
    12: ((3, 0, 111, 0), "화면 밝기 +", "Screen brightness +", "屏幕亮度 +"),
    18: ((0, 0, 227, 43), "Win+Tab", "Win+Tab", "Win+Tab"),
    24: ((3, 0, 182, 0), "이전 곡", "Previous track", "上一曲"),
    30: ((3, 0, 205, 0), "재생/일시정지", "Play/Pause", "播放/暂停"),
    36: ((3, 0, 181, 0), "다음 곡", "Next track", "下一曲"),
    42: ((0, 0, 227, 8), "Win+E", "Win+E", "Win+E"),
    48: ((3, 0, 138, 1), "메일", "Mail", "邮件"),
    54: ((3, 0, 35, 2), "웹 홈", "Web home", "网页主页"),
    60: ((3, 0, 226, 0), "음소거", "Mute", "静音"),
    66: ((3, 0, 234, 0), "볼륨 −", "Volume −", "音量 −"),
    72: ((3, 0, 233, 0), "볼륨 +", "Volume +", "音量 +"),
    8: ((14, 0, 0, 0), "블루투스 1", "Bluetooth 1", "蓝牙 1"),
    14: ((14, 0, 1, 0), "블루투스 2", "Bluetooth 2", "蓝牙 2"),
    20: ((14, 0, 2, 0), "블루투스 3", "Bluetooth 3", "蓝牙 3"),
    26: ((14, 0, 5, 0), "2.4G 무선", "2.4G wireless", "2.4G 无线"),
    32: ((14, 0, 6, 0), "유선", "Wired", "有线"),
    52: ((10, 5, 3, 0), "시스템 전환", "Switch OS mode", "系统切换"),
    17: ((10, 3, 0, 0), "Win 키 잠금", "Win key lock", "Win 键锁定"),
    78: ((10, 9, 0, 0), "LED 켜기/끄기", "LED on/off", "LED 开/关"),
    79: ((10, 8, 0, 0), "배터리 확인", "Check battery", "查看电量"),
    82: ((13, 2, 1, 0), "LED 밝기 +", "LED brightness +", "LED 亮度 +"),
    83: ((13, 2, 2, 0), "LED 밝기 −", "LED brightness −", "LED 亮度 −"),
    84: ((13, 1, 0, 0), "효과 순환", "Next effect", "切换灯效"),
    85: ((13, 5, 1, 0), "색 순환", "Next color", "切换颜色"),
    86: ((13, 3, 2, 0), "LED 속도 −", "LED speed −", "LED 速度 −"),
    87: ((13, 3, 1, 0), "LED 속도 +", "LED speed +", "LED 速度 +"),
    77: ((13, 5, 0, 2), "효과 방향 ←", "Effect direction ←", "灯效方向 ←"),
    89: ((13, 5, 0, 1), "효과 방향 →", "Effect direction →", "灯效方向 →"),
}


def test_default_fn_table_names_in_three_languages():
    from agk75 import i18n
    for _idx, (item, *names) in DEFAULT_FN.items():
        for lang, want in zip(("ko", "en", "zh"), names):
            with i18n.use(lang):
                assert p.item_label(bytes(item)) == want, (item, lang)
                assert p.item_label(bytes(item), True)


def test_unknown_code_shows_raw_value_and_blank_is_none():
    from agk75 import i18n
    with i18n.use("ko"):
        assert p.item_label(bytes([0x0a, 0x63, 0, 0x07])) == "특수 [0a 63 00 07]"
        assert p.item_label(bytes([0x0a, 0x63, 0, 0x07]), True) == "0a63 0007"
        assert p.item_label(bytes(4)) == "없음"
        assert p.item_label(p.key_item(4)) == "A" and p.item_label(bytes([0, 230, 0, 0])) == "Alt"
    with i18n.use("en"):
        assert p.item_label(bytes([0x0a, 0x63, 0, 0x07])) == "Special [0a 63 00 07]"


def test_every_fn_name_has_three_languages_and_short_form():
    from agk75 import i18n
    for fid in p.FN_CODES:
        for lang in i18n.LANGS:
            assert i18n.MSG[lang]["fnaction." + fid] and i18n.MSG[lang]["fnaction." + fid + ".s"], (fid, lang)
