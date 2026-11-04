import json
import sys
import time

from . import i18n
from .protocol import Device, dump
from .service import data_dir


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
    from .ui.app import run  # 화면이 필요한 실행에서만 Qt 를 불러온다
    sys.exit(run())


if __name__ == "__main__":
    main()
