"""사용자에게 보이는 서버 문구 사전(ko/en/zh). web/i18n.js 와 같은 점(.) 구분 키 체계를 쓴다.

예외는 Msg(key, **params) 로 올리고, 응답을 만들 때 요청 언어(X-Lang)로 번역한다.
str(Msg) 는 항상 영어라서 로그와 내부 문구는 영어로 남는다. 사전에 없는 키는 키 문자열 그대로 보여 준다.
"""
import contextlib
import threading

LANGS = ("ko", "en", "zh")
DEFAULT = "ko"
_local = threading.local()

MSG = {
    "ko": {
        "common.none": "없음",
        "key.none": "없음",
        "key.special": "특수[{hex}]",
        "err.int_range": "{name} 는 {lo}~{hi} 정수여야 합니다",
        "err.mm_range": "{name} 는 {lo}~{hi} mm 범위여야 합니다",
        "err.bool": "{name} 는 true/false 여야 합니다",
        "err.unknown_option": "알 수 없는 옵션 {name}",
        "err.no_change": "바꿀 항목이 없습니다",
        "err.key_locked": "이 번호는 바꿀 수 없는 키입니다(Fn 키 포함)",
        "err.rgb": "rgb 는 [r,g,b] 여야 합니다",
        "err.effect": "알 수 없는 효과 {effect}",
        "err.no_factory": "첫 연결 때 저장된 기본값이 없습니다",
        "err.backup_name": "백업 파일 이름이 올바르지 않습니다",
        "err.backup_open": "백업 파일을 열 수 없습니다: {reason}",
        "err.rate_busy": "다른 폴링레이트 작업이 진행 중입니다",
        "err.admin_busy": "이전 관리자 작업이 아직 진행 중입니다",
        "err.hz_choice": "hz 는 {list} 중 하나여야 합니다",
        "err.not_found": "없는 API: {path}",
        "err.host": "허용되지 않은 호스트",
        "err.request": "허용되지 않은 요청",
        "err.body": "본문이 JSON 객체가 아닙니다",
        "err.device": "장치 통신 오류: {reason}",
        "err.measure_busy": "이미 측정 중입니다",
        "restore.old": "옛 형식의 백업이라 복원할 수 없습니다(버전 2 필요)",
        "restore.keymap_len": "키맵 길이가 맞지 않습니다",
        "restore.fn_len": "Fn 길이가 맞지 않습니다",
        "restore.no_magnet": "자기 축 데이터가 없습니다",
        "restore.options": "옵션 데이터가 맞지 않습니다",
        "restore.format": "백업 파일 형식이 올바르지 않습니다: {reason}",
        "restore.partial": "부분 복원됨: {stage} 단계에서 중단(완료: {done}). {back}. 원인: {cause}",
        "restore.back_ok": "복원 전 프로필로 되돌림",
        "restore.back_fail": "복원 전 프로필로 되돌리지 못함",
        "restore.stage.keymap": "키맵",
        "restore.stage.fn": "Fn",
        "restore.stage.magnet": "자기 축",
        "restore.stage.light": "조명",
        "restore.stage.options": "옵션",
        "restore.stage.profile": "프로필",
        "rate.multi_device": "같은 키보드가 {n}개 연결돼 있어 대상을 정할 수 없습니다. 하나만 연결해 주세요: {ids}",
        "rate.device_missing": "키보드 USB 장치를 찾지 못했습니다",
        "rate.dir_not_empty": "대상 폴더가 비어 있지 않습니다: {path}",
        "rate.download_fail": "드라이버를 내려받지 못했습니다: {reason}",
        "rate.too_big": "내려받은 파일이 너무 큽니다",
        "rate.not_zip": "내려받은 파일이 zip 이 아닙니다",
        "rate.zip_big": "압축 파일이 너무 크거나 파일이 너무 많습니다",
        "rate.zip_path": "압축 파일 경로가 안전하지 않습니다: {name}",
        "rate.inf_missing": "{name} 를 찾지 못했습니다",
        "rate.files_missing": "HIDUSBFU.INF 또는 AMD64_AS\\hidusbf.sys 를 찾지 못했습니다",
        "rate.sig_fail": "드라이버 서명 확인 실패(상태 {status}, 서명자 {signer})",
        "rate.unsupported": "지원하지 않는 폴링레이트입니다: {hz}",
        "rate.prepare_first": "드라이버를 먼저 준비해 주세요",
        "rate.admin_denied": "관리자 권한 요청이 거부되었거나 실행하지 못했습니다(코드 {code})",
        "rate.admin_timeout": "관리자 작업 결과를 {sec}초 안에 받지 못했습니다(UAC 창 확인)",
        "rate.staged_missing": "준비된 파일이 없거나 너무 큽니다: {rel}",
        "rate.sig_bad": "드라이버 서명이 올바르지 않습니다(상태 {status})",
        "rate.svc_missing": "설치 뒤에도 hidusbf 서비스가 등록되지 않았습니다",
        "rate.pnputil": "pnputil 실패(코드 {rc}): {out}",
        "rate.sh_fail": "{cmd} 실패(코드 {rc}): {out}",
        "rate.installed": "설치됨",
        "rate.done": "완료",
        "rate.restart_reboot": "{out}\n다시 부팅해야 적용됩니다",
        "rate.step.preparing": "준비 중…",
        "rate.step.admin": "관리자 권한으로 적용 중… (권한 확인 창이 뜨면 허용해 주세요)",
        "rate.step.wait": "장치가 다시 연결되길 기다리는 중…",
        "rate.step.download": "드라이버를 내려받고 서명을 확인하는 중…",
        "measure.note": "PC 메시지 처리 기준 추정치",
        "usb.no_device": "USB 장치를 찾지 못했습니다",
        "usb.no_node": "장치 노드를 찾지 못했습니다",
        "usb.no_port": "포트 번호를 읽지 못했습니다",
        "usb.no_hub": "부모 허브를 찾지 못했습니다",
        "usb.no_hub_id": "허브 ID 를 읽지 못했습니다",
        "usb.hub_open": "허브를 열지 못했습니다 (오류 {code})",
        "usb.hub_query": "허브 조회 실패 (오류 {code})",
        "usb.no_endpoint": "인터럽트 IN 엔드포인트가 없습니다",
        "cli.url": "AGK75 설정: {url} (창을 닫으면 종료됩니다)",
        "cli.already": "이미 원래 상태입니다",
        "cli.done": "복구 완료",
        "cli.fail": "복구 실패: {reason}",
        "cli.saved": "저장: {path}",
    },
    "en": {
        "common.none": "none",
        "key.none": "None",
        "key.special": "Special [{hex}]",
        "err.int_range": "{name} must be an integer from {lo} to {hi}",
        "err.mm_range": "{name} must be within {lo} to {hi} mm",
        "err.bool": "{name} must be true or false",
        "err.unknown_option": "Unknown option {name}",
        "err.no_change": "Nothing to change",
        "err.key_locked": "This key number cannot be changed (the Fn key is protected)",
        "err.rgb": "rgb must be [r, g, b]",
        "err.effect": "Unknown effect {effect}",
        "err.no_factory": "No defaults were saved on the first connection",
        "err.backup_name": "Invalid backup file name",
        "err.backup_open": "Cannot open the backup file: {reason}",
        "err.rate_busy": "Another polling rate task is in progress",
        "err.admin_busy": "The previous administrator task is still running",
        "err.hz_choice": "hz must be one of {list}",
        "err.not_found": "Unknown API: {path}",
        "err.host": "Host not allowed",
        "err.request": "Request not allowed",
        "err.body": "The request body is not a JSON object",
        "err.device": "Device communication error: {reason}",
        "err.measure_busy": "A measurement is already running",
        "restore.old": "This backup uses an old format and cannot be restored (version 2 required)",
        "restore.keymap_len": "Keymap length does not match",
        "restore.fn_len": "Fn layer length does not match",
        "restore.no_magnet": "The backup has no magnetic switch data",
        "restore.options": "Option data does not match",
        "restore.format": "Invalid backup file format: {reason}",
        "restore.partial": "Partially restored: stopped at the {stage} step (done: {done}). {back}. Cause: {cause}",
        "restore.back_ok": "Switched back to the pre-restore profile",
        "restore.back_fail": "Could not switch back to the pre-restore profile",
        "restore.stage.keymap": "Keymap",
        "restore.stage.fn": "Fn",
        "restore.stage.magnet": "Magnetic switches",
        "restore.stage.light": "Lighting",
        "restore.stage.options": "Options",
        "restore.stage.profile": "Profile",
        "rate.multi_device": "{n} identical keyboards are connected, so the target cannot be determined. Connect only one: {ids}",
        "rate.device_missing": "The keyboard USB device was not found",
        "rate.dir_not_empty": "The target folder is not empty: {path}",
        "rate.download_fail": "Failed to download the driver: {reason}",
        "rate.too_big": "The downloaded file is too large",
        "rate.not_zip": "The downloaded file is not a zip",
        "rate.zip_big": "The archive is too large or has too many files",
        "rate.zip_path": "Unsafe path in the archive: {name}",
        "rate.inf_missing": "{name} was not found",
        "rate.files_missing": "HIDUSBFU.INF or AMD64_AS\\hidusbf.sys was not found",
        "rate.sig_fail": "Driver signature check failed (status {status}, signer {signer})",
        "rate.unsupported": "Unsupported polling rate: {hz}",
        "rate.prepare_first": "Prepare the driver first",
        "rate.admin_denied": "The administrator permission request was denied or could not start (code {code})",
        "rate.admin_timeout": "No administrator task result within {sec} seconds (check the UAC prompt)",
        "rate.staged_missing": "A prepared file is missing or too large: {rel}",
        "rate.sig_bad": "The driver signature is not valid (status {status})",
        "rate.svc_missing": "The hidusbf service is still not registered after installation",
        "rate.pnputil": "pnputil failed (code {rc}): {out}",
        "rate.sh_fail": "{cmd} failed (code {rc}): {out}",
        "rate.installed": "Installed",
        "rate.done": "Done",
        "rate.restart_reboot": "{out}\nReboot required to apply",
        "rate.step.preparing": "Preparing…",
        "rate.step.admin": "Applying with administrator rights… (allow the permission prompt if it appears)",
        "rate.step.wait": "Waiting for the device to reconnect…",
        "rate.step.download": "Downloading the driver and checking its signature…",
        "measure.note": "Estimate based on PC message handling",
        "usb.no_device": "USB device not found",
        "usb.no_node": "Device node not found",
        "usb.no_port": "Could not read the port number",
        "usb.no_hub": "Parent hub not found",
        "usb.no_hub_id": "Could not read the hub ID",
        "usb.hub_open": "Could not open the hub (error {code})",
        "usb.hub_query": "Hub query failed (error {code})",
        "usb.no_endpoint": "No interrupt IN endpoint",
        "cli.url": "AGK75 settings: {url} (exits when the window is closed)",
        "cli.already": "Already in the original state",
        "cli.done": "Recovery complete",
        "cli.fail": "Recovery failed: {reason}",
        "cli.saved": "Saved: {path}",
    },
    "zh": {
        "common.none": "无",
        "key.none": "无",
        "key.special": "特殊[{hex}]",
        "err.int_range": "{name} 必须是 {lo}~{hi} 之间的整数",
        "err.mm_range": "{name} 必须在 {lo}~{hi} mm 范围内",
        "err.bool": "{name} 必须是 true 或 false",
        "err.unknown_option": "未知选项 {name}",
        "err.no_change": "没有要修改的项目",
        "err.key_locked": "该键位无法修改（包括 Fn 键）",
        "err.rgb": "rgb 必须是 [r,g,b]",
        "err.effect": "未知灯效 {effect}",
        "err.no_factory": "首次连接时没有保存默认值",
        "err.backup_name": "备份文件名无效",
        "err.backup_open": "无法打开备份文件：{reason}",
        "err.rate_busy": "另一个回报率任务正在进行",
        "err.admin_busy": "上一个管理员任务仍在进行",
        "err.hz_choice": "hz 必须是 {list} 之一",
        "err.not_found": "不存在的 API:{path}",
        "err.host": "不允许的主机",
        "err.request": "不允许的请求",
        "err.body": "请求内容不是 JSON 对象",
        "err.device": "设备通信错误：{reason}",
        "err.measure_busy": "正在测量中",
        "restore.old": "这是旧格式的备份，无法恢复（需要版本 2）",
        "restore.keymap_len": "键位表长度不匹配",
        "restore.fn_len": "Fn 层长度不匹配",
        "restore.no_magnet": "备份中没有磁轴数据",
        "restore.options": "选项数据不匹配",
        "restore.format": "备份文件格式无效：{reason}",
        "restore.partial": "部分恢复：在“{stage}”步骤中断（已完成：{done}）。{back}。原因：{cause}",
        "restore.back_ok": "已切换回恢复前的配置",
        "restore.back_fail": "未能切换回恢复前的配置",
        "restore.stage.keymap": "键位表",
        "restore.stage.fn": "Fn 层",
        "restore.stage.magnet": "磁轴",
        "restore.stage.light": "灯光",
        "restore.stage.options": "选项",
        "restore.stage.profile": "配置",
        "rate.multi_device": "连接了 {n} 个相同的键盘，无法确定目标。请只连接一个：{ids}",
        "rate.device_missing": "未找到键盘 USB 设备",
        "rate.dir_not_empty": "目标文件夹不为空：{path}",
        "rate.download_fail": "驱动下载失败：{reason}",
        "rate.too_big": "下载的文件过大",
        "rate.not_zip": "下载的文件不是 zip",
        "rate.zip_big": "压缩包过大或文件过多",
        "rate.zip_path": "压缩包中的路径不安全：{name}",
        "rate.inf_missing": "未找到 {name}",
        "rate.files_missing": "未找到 HIDUSBFU.INF 或 AMD64_AS\\hidusbf.sys",
        "rate.sig_fail": "驱动签名验证失败（状态 {status}，签名者 {signer}）",
        "rate.unsupported": "不支持的回报率：{hz}",
        "rate.prepare_first": "请先准备驱动",
        "rate.admin_denied": "管理员权限请求被拒绝或无法启动（代码 {code}）",
        "rate.admin_timeout": "{sec} 秒内未收到管理员任务结果（请查看 UAC 窗口）",
        "rate.staged_missing": "准备好的文件缺失或过大：{rel}",
        "rate.sig_bad": "驱动签名无效（状态 {status}）",
        "rate.svc_missing": "安装后仍未注册 hidusbf 服务",
        "rate.pnputil": "pnputil 失败（代码 {rc}）：{out}",
        "rate.sh_fail": "{cmd} 失败（代码 {rc}）：{out}",
        "rate.installed": "已安装",
        "rate.done": "完成",
        "rate.restart_reboot": "{out}\n需要重新启动电脑才能生效",
        "rate.step.preparing": "准备中…",
        "rate.step.admin": "正在以管理员权限应用…（如出现权限确认窗口请允许）",
        "rate.step.wait": "正在等待设备重新连接…",
        "rate.step.download": "正在下载驱动并验证签名…",
        "measure.note": "基于 PC 消息处理的估算值",
        "usb.no_device": "未找到 USB 设备",
        "usb.no_node": "未找到设备节点",
        "usb.no_port": "无法读取端口号",
        "usb.no_hub": "未找到上级集线器",
        "usb.no_hub_id": "无法读取集线器 ID",
        "usb.hub_open": "无法打开集线器（错误 {code}）",
        "usb.hub_query": "集线器查询失败（错误 {code}）",
        "usb.no_endpoint": "没有中断 IN 端点",
        "cli.url": "AGK75 设置：{url}（关闭窗口后退出）",
        "cli.already": "已是初始状态",
        "cli.done": "恢复完成",
        "cli.fail": "恢复失败：{reason}",
        "cli.saved": "已保存：{path}",
    },
}


def norm(lang):
    """X-Lang 값(ko/en/zh, zh-CN 같은 변형 허용) -> 지원 언어. 모르면 기본(ko)."""
    code = str(lang or "").strip().lower()[:2]
    return code if code in LANGS else DEFAULT


def _val(lang, v):
    if isinstance(v, Msg):
        return render(lang, v.key, v.params)
    if isinstance(v, (list, tuple)):
        return ", ".join(str(_val(lang, x)) for x in v)
    return v


def render(lang, key, params=None):
    s = MSG[norm(lang)].get(key)
    if s is None:
        return key  # 사전에 없으면 영어 원문(내부 문구)을 그대로 쓴다
    p = {k: _val(lang, v) for k, v in (params or {}).items()}
    try:
        return s.format(**p)
    except (KeyError, IndexError, ValueError):
        return s


class Msg(Exception):
    """번역할 수 있는 오류. str() 은 영어다."""

    def __init__(self, key, **params):
        super().__init__(key)
        self.key, self.params = key, params

    def __str__(self):
        return render("en", self.key, self.params)


class MsgError(Msg, ValueError):
    """입력 검사 실패(서버가 400 으로 돌려준다)."""


def to_json(m):
    return {"key": m.key, "params": {k: _val("en", v) for k, v in m.params.items()}}


def from_json(d):
    return Msg(d["key"], **d.get("params", {}))


def lang():
    return getattr(_local, "lang", DEFAULT)


@contextlib.contextmanager
def use(lang_code):
    prev = getattr(_local, "lang", DEFAULT)
    _local.lang = norm(lang_code)
    try:
        yield
    finally:
        _local.lang = prev


def t(key, **params):
    return render(lang(), key, params)


def msg(exc):
    """예외 -> 현재 언어 문구(Msg 가 아니면 str)."""
    return render(lang(), exc.key, exc.params) if isinstance(exc, Msg) else str(exc)


def system_lang():
    """콘솔 출력용: Windows 사용자 UI 언어(ko/zh, 그 밖은 en)."""
    try:
        import ctypes
        primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
    except (AttributeError, OSError):
        return "en"
    return {0x12: "ko", 0x04: "zh"}.get(primary, "en")
