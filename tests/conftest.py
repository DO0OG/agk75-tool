import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # 화면 시험은 보이는 창 없이 돌린다


@pytest.fixture(autouse=True)
def korean():
    from agk75 import i18n
    i18n.set_lang("ko")
    yield
    i18n.set_lang("ko")
