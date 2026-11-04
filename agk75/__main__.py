import json
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

from . import i18n
from .protocol import Device, dump
from .server import data_dir

START_GRACE = 30  # 창이 처음 뜨기까지 기다리는 시간(초)
BEAT_TIMEOUT = 15  # 마지막 heartbeat 후 이 시간이 지나면 창이 닫힌 것으로 본다(초)


def find_browser():
    for env, rel in (("ProgramFiles(x86)", r"Microsoft\Edge\Application\msedge.exe"),
                     ("ProgramFiles", r"Microsoft\Edge\Application\msedge.exe"),
                     ("ProgramFiles", r"Google\Chrome\Application\chrome.exe"),
                     ("LocalAppData", r"Google\Chrome\Application\chrome.exe")):
        path = os.path.join(os.environ.get(env, ""), rel)
        if os.path.isfile(path):
            return path
    return shutil.which("msedge") or shutil.which("chrome")


def open_window(url):
    exe = find_browser()
    if exe:  # 주소창·탭 없는 앱 창
        subprocess.Popen([exe, "--app=" + url, "--window-size=1280,800"])
    else:
        webbrowser.open(url)


def serve(open_browser=True):
    from .server import Hub, make_server
    hub = Hub()
    srv = make_server(hub)
    url = "http://127.0.0.1:%d" % srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(i18n.render(i18n.system_lang(), "cli.url", {"url": url}))
    if not open_browser:  # 콘솔이 없는 exe 에서도 주소를 알 수 있게 파일로 남긴다
        (data_dir() / "server.txt").write_text(url, encoding="utf-8")
    if open_browser:
        open_window(url)
    start = time.monotonic()
    try:
        while True:
            time.sleep(1)
            idle = time.monotonic() - (hub.beat or start)
            if idle > (BEAT_TIMEOUT if hub.beat else START_GRACE):
                break
    except KeyboardInterrupt:
        pass
    srv.shutdown()
    hub.close()


def rate_reset():
    """구조 명령: 폴링레이트 필터(bInterval, LowerFilters)를 지우고 장치를 다시 시작한다."""
    from . import ratectl
    lang, ops = i18n.system_lang(), ratectl.plan_reset()
    if not ops:
        print(i18n.render(lang, "cli.already"))
        return 0
    res = ratectl.run_admin(ops)
    print(i18n.render(lang, "cli.done") if res.get("ok") else i18n.render(
        lang, "cli.fail", {"reason": res.get("error", "")}))
    return 0 if res.get("ok") else 1


def main():
    if "--admin" in sys.argv:  # 관리자로 다시 띄워진 프로세스: 작업 파일 하나를 처리하고 끝낸다
        from .ratectl import admin_main
        sys.exit(admin_main(sys.argv[sys.argv.index("--admin") + 1]))
    if "--rate-reset" in sys.argv:
        sys.exit(rate_reset())
    if "--dump" in sys.argv:
        dev = Device()
        try:
            data = dump(dev)
        finally:
            dev.close()
        name = "backup_%s.json" % time.strftime("%Y%m%d_%H%M%S")
        with open(data_dir("backups") / name, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print(i18n.render(i18n.system_lang(), "cli.saved", {"path": data_dir("backups") / name}))
        return
    serve("--no-browser" not in sys.argv)


if __name__ == "__main__":
    main()
