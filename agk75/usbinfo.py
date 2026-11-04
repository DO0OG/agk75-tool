"""USB 협상 정보(속도, 엔드포인트 bInterval)를 허브에서 읽어 폴링 간격을 계산한다. 읽기 전용, ctypes 만 쓴다."""
import ctypes
import struct
from ctypes import wintypes

VID_PID = "VID_3151&PID_5009"
IOCTL_GET_NODE_CONNECTION_INFORMATION_EX = 0x220448
HUB_GUID = "{f18a0e88-c30c-11d0-8815-00a0c906bed8}"
SPEEDS = ["Low", "Full", "High", "Super"]
BS = chr(92)
BUF_SIZE = 35 + 11 * 30


def parse_connection_info(buf):
    """IOCTL 응답 바이트 -> {"speed", "endpoints", "poll_us", "max_hz"}."""
    if len(buf) < 35:
        raise ValueError("response too short")
    speed = buf[23]
    n = struct.unpack_from("<l", buf, 27)[0]  # NumberOfOpenPipes (ConnectionStatus 는 31)
    eps = []
    for i in range(max(0, min(n, (len(buf) - 35) // 11))):
        _, _, addr, attr, mps, interval = struct.unpack_from("<BBBBHB", buf, 35 + 11 * i)
        eps.append({"address": "0x%02x" % addr, "interval": interval, "max_packet": mps, "attr": attr})
    # 인터럽트 IN 엔드포인트(속성 3, 방향 비트 0x80) 중 가장 짧은 주기를 쓴다
    ins = [e for e in eps if e["attr"] & 3 == 3 and int(e["address"], 16) & 0x80 and e["interval"]]
    out = {"speed": SPEEDS[speed] if speed < len(SPEEDS) else str(speed),
           "endpoints": [{k: e[k] for k in ("address", "interval", "max_packet")} for e in eps]}
    if ins and speed >= 2:
        us = min(125 * 2 ** (e["interval"] - 1) for e in ins)
    elif ins:
        us = min(e["interval"] for e in ins) * 1000
    else:
        return {**out, "error": "usb.no_endpoint"}
    return {**out, "poll_us": us, "max_hz": round(1_000_000 / us)}


def _find(cm):
    """연결된 장치(복합 장치 본체)의 인스턴스 ID 를 찾는다."""
    buf = ctypes.create_unicode_buffer(65536)
    # 필터: 열거자 이름 + 현재 존재하는 것만
    if cm.CM_Get_Device_ID_ListW("USB", buf, len(buf), 0x1 | 0x100):
        return None
    ids = ctypes.wstring_at(ctypes.addressof(buf), len(buf)).split("\0")
    for i in ids:
        if i.upper().startswith("USB" + BS + VID_PID + BS):
            return i
    return None


def read():
    try:
        cm = ctypes.WinDLL("cfgmgr32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        dev_id = _find(cm)
        if not dev_id:
            return {"error": "usb.no_device"}
        inst, parent = wintypes.DWORD(), wintypes.DWORD()
        if cm.CM_Locate_DevNodeW(ctypes.byref(inst), dev_id, 0):
            return {"error": "usb.no_node"}
        # 포트 번호 = DEVPKEY_Device_Address
        key = (ctypes.c_byte * 20)(*(bytes.fromhex("4e255ca4" "1cdf" "fd4e" "8020" "67d146a850e0") + (30).to_bytes(4, "little")))
        typ, size, port = wintypes.ULONG(), wintypes.ULONG(4), wintypes.ULONG()
        if cm.CM_Get_DevNode_PropertyW(inst, key, ctypes.byref(typ), ctypes.byref(port), ctypes.byref(size), 0):
            return {"error": "usb.no_port"}
        if cm.CM_Get_Parent(ctypes.byref(parent), inst, 0):
            return {"error": "usb.no_hub"}
        pid = ctypes.create_unicode_buffer(512)
        if cm.CM_Get_Device_IDW(parent, pid, len(pid), 0):
            return {"error": "usb.no_hub_id"}
        path = BS * 2 + "?" + BS + pid.value.replace(BS, "#") + "#" + HUB_GUID
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL
        h = k32.CreateFileW(path, 0xC0000000, 3, None, 3, 0, None)
        if h in (None, wintypes.HANDLE(-1).value):
            return {"error": "usb.hub_open", "error_params": {"code": ctypes.get_last_error()}}
        try:
            buf = ctypes.create_string_buffer(BUF_SIZE)
            struct.pack_into("<L", buf, 0, port.value)
            ret = wintypes.DWORD()
            k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                            wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
            if not k32.DeviceIoControl(h, IOCTL_GET_NODE_CONNECTION_INFORMATION_EX, buf, BUF_SIZE, buf, BUF_SIZE,
                                       ctypes.byref(ret), None):
                return {"error": "usb.hub_query", "error_params": {"code": ctypes.get_last_error()}}
            return parse_connection_info(buf.raw[:ret.value])
        finally:
            if not k32.CloseHandle(h):
                raise OSError("Could not close the hub handle (error %d)" % ctypes.get_last_error())
    except (OSError, AttributeError, ValueError) as e:
        return {"error": str(e)}
