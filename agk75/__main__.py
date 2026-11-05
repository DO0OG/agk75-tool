import json
import sys
import time

from . import i18n
from .protocol import Device, dump
from .service import data_dir


def main():
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
    if "--trace" in sys.argv:  # 폴링레이트 측정의 관리자 쪽(작업 파일 경로 하나만 받는다)
        from .usbtrace import admin_main
        i = sys.argv.index("--trace") + 1
        sys.exit(admin_main(sys.argv[i] if i < len(sys.argv) else ""))
    from .ui.app import run  # 화면이 필요한 실행에서만 Qt 를 불러온다
    sys.exit(run())


if __name__ == "__main__":
    main()
