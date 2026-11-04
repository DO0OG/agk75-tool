"""백업·복원: 현재 설정을 JSON 으로 저장하고, 목록에서 고른 파일로 되돌린다."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QListWidget, QListWidgetItem

from ..i18n import t
from ..service import describe_error
from .page import Page
from .widgets import StateLabel, alive, button, h2, row, sub


class BackupPage(Page):
    name, label_key, icon, stage = "backup", "nav.backup", "backup", False

    def __init__(self, win):
        super().__init__(win)
        self.bk = self.restore_btn = self.all_cb = self.state_lbl = self.listw = None
        self.selected = None

    def state(self, text, kind=""):
        if alive(self.state_lbl):
            self.state_lbl.set(text, kind)

    def build(self):
        self.selected = None
        self.lay.addWidget(h2(t("backup.title")))
        self.lay.addWidget(sub(t("backup.sub")))
        self.bk, self.restore_btn = button(t("backup.now"), primary=True), button(t("backup.restore"), enabled=False)
        self.bk.clicked.connect(self.backup)
        self.restore_btn.clicked.connect(self.restore)
        self.lay.addWidget(row(self.bk, self.restore_btn, stretch=True))
        self.all_cb = QCheckBox(t("backup.all"))
        self.lay.addWidget(self.all_cb)
        self.state_lbl = StateLabel()
        self.lay.addWidget(self.state_lbl)
        self.listw = QListWidget()
        self.listw.setMaximumWidth(640)
        self.listw.setMinimumHeight(220)
        self.listw.itemSelectionChanged.connect(self._picked)
        self.lay.addWidget(self.listw)
        self.refresh()

    def _picked(self):
        items = self.listw.selectedItems()
        self.selected = items[0].data(256) if items else None
        self.restore_btn.setEnabled(self.selected is not None)

    def refresh(self):
        def done(j, err):
            if not alive(self.listw):
                return
            if err is not None:
                return self.win.fail(err)
            self.listw.clear()
            for b in j["backups"]:
                item = QListWidgetItem("%s    %s · %d KB" % (b["name"], b["time"], round(b["size"] / 1024)))
                item.setData(256, b["name"])
                self.listw.addItem(item)
            if not j["backups"]:
                empty = QListWidgetItem(t("backup.empty"))
                empty.setFlags(Qt.NoItemFlags)  # 선택 불가
                self.listw.addItem(empty)
        self.win.run(self.win.svc.backups, done)

    def backup(self):
        allp = self.all_cb.isChecked()
        self.bk.setEnabled(False)
        self.state(t("backup.running"))

        def done(j, err):
            ok = self.win.report(j, err, t("toast.backup_saved"))
            if alive(self.bk):
                self.bk.setEnabled(True)
            if err is not None:
                self.state(describe_error(err), "bad")
            else:
                self.state(t("backup.saved", name=j["name"]), "ok" if ok else "bad")
            if alive(self.listw):
                self.refresh()
        self.win.run(lambda: self.win.svc.backup(all_profiles=allp), done)

    def restore(self):
        name = self.selected
        if not name or not self.win.confirm(t("backup.confirm", name=name)):
            return
        self.restore_btn.setEnabled(False)
        self.state(t("backup.restoring"))
        self.win.long_start()

        def done(j, err):
            self.win.long_end()
            self.win.report(j, err, t("toast.restore_done"))
            if alive(self.restore_btn):
                self.restore_btn.setEnabled(self.selected is not None)
            if err is not None:
                self.state(describe_error(err), "bad")
            elif j.get("partial"):
                self.state(j["message"], "bad")
            elif j["applied"]:
                self.state(t("backup.verified"), "ok")
            else:
                text = t("backup.diff", diff=", ".join(j["diff"]))
                self.state(text + (t("backup.skipped", skipped=", ".join(j["skipped"])) if j["skipped"] else ""), "bad")
            self._reread()
        self.win.run(lambda: self.win.svc.restore(file=name), done)

    def _reread(self):
        def done(j, err):
            if err is None:
                self.win.s = j
                self.win.draw_top()
            else:
                self.win.fail(err)
        self.win.run(self.win.svc.state, done)
