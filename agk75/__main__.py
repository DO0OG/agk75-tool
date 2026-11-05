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
    from .ui.app import run  # 화면이 필요한 실행에서만 Qt 를 불러온다
    sys.exit(run())


if __name__ == "__main__":
    main()
