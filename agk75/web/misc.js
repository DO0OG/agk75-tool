// 성능·기타(디바운스, 절전, 장치 옵션, 폴링레이트 측정, 고정 정보)와 백업·복원 화면.
(() => {
  const dur = (s) => (s >= 60 ? t("dur.min", { n: Math.round(s / 60) }) : t("dur.sec", { n: s }));
  const OPTIONS = ["win_lock", "mac", "wasd_arrow", "led_off", "side_led_off", "keyboard_lock", "fn_matrix", "power_save"];
  let mtimer = null;

  const optionsHtml = (o) => o ? OPTIONS.map((k) =>
    `<div class="row"><label>${t("opt." + k)}</label><button class="switch ${o[k] ? "on" : ""}" data-opt="${k}"></button></div>`).join("")
    : `<span>${t("opt.unreadable")}</span>`;

  function measureHtml(j) {
    if (j.error) return `<div class="state bad">${A.esc(j.error)}</div>`;
    if (j.running) {
      return `<div class="state">${t("measure.running", { remaining: Math.ceil(j.remaining), events: j.events })}</div>`;
    }
    const r = j.result;
    if (!r) return "";
    if (r.min_ms === null) return `<div class="state bad">${t("measure.noevents")}</div>`;
    const max = Math.max(1, ...r.hist.map((h) => h.count));
    const rough = r.cluster_n < 10 ? "<br>" + t("measure.rough") : "";
    return `<b>${r.hz_at_least ? t("measure.summary", { atleast: r.hz_at_least, est: r.hz_estimate, n: r.cluster_n, ms: r.cluster_ms.toFixed(3) }) : t("measure.insufficient")}</b> <small>${r.note}</small>${r.hz_at_least ? rough : ""}
      <span>${t("measure.mininfo", { min: r.min_ms.toFixed(3), samples: r.samples })}${r.enough ? "" : t("measure.notenough")}</span>
      <div class="hist">${r.hist.map((h) => `<span>${h.label} ms</span><i style="width:${h.count / max * 100}%"></i><span>${h.count}</span>`).join("")}</div>`;
  }

  async function measureTick() {
    const box = A.$("#mres");
    if (!box) { clearInterval(mtimer); mtimer = null; return; }
    const j = await A.api("GET", "/api/measure/status");
    if (!j.ok) { box.innerHTML = `<div class="state bad">${A.esc(j.error || t("err.generic"))}</div>`; return; }
    box.innerHTML = measureHtml(j);
    A.$("#mbar2").style.width = j.running ? (1 - j.remaining / j.seconds) * 100 + "%" : j.result ? "100%" : "0";
    A.$("#mstart").disabled = j.running;
    if (!j.running) { clearInterval(mtimer); mtimer = null; }
  }

  async function measureStart() {
    const j = await A.api("POST", "/api/measure/start", { seconds: 10 });
    if (!j.ok) { A.toast(j.error || t("err.generic"), "bad", 5000); return; }
    if (!mtimer) mtimer = setInterval(measureTick, 500);
    measureTick();
  }

  async function usbRefresh() {
    const el = A.$("#usbpoll");
    if (!el) return;
    el.textContent = t("usb.reading");
    const j = await A.api("GET", "/api/usbinfo");
    const e = A.$("#usbpoll");
    if (!e) return;
    e.textContent = j.error || !j.ok ? (j.error || t("err.generic"))
      : t("usb.result", { us: j.poll_us, hz: j.max_hz, speed: j.speed });
  }

  async function setOption(k) {
    const o = A.s.options;
    if (!o) return;
    if (k === "keyboard_lock" && !o[k] && !confirm(t("opt.confirm_lock"))) return;
    const j = await A.api("POST", "/api/options", { [k]: !o[k] });
    A.report(j, t("toast.opt_applied"));
    if (j.ok && j.options) A.s.options = j.options;
    A.$("#optbox").innerHTML = optionsHtml(A.s.options);
  }

  A.views.misc = {
    label: "nav.misc", icon: "misc", stage: false,
    render(p) {
      const s = A.s;
      p.innerHTML = `<h2>${t("misc.title")}</h2><p class="sub">${t("misc.sub")}</p><div class="info">
        <div class="card"><span>${t("misc.debounce")}</span>${A.rangeRow(t("misc.time"), "deb", 0, 20, 1, s.debounce, " ms")}
          <button class="btn primary" id="debapply">${t("misc.apply")}</button><div class="state" id="debstate"></div></div>
        <div class="card"><span>${t("misc.sleep")}</span><b>${(s.sleep || []).map(dur).join(" / ") || "-"}</b>
          <span>${t("misc.sleep_note")}</span></div>
        <div class="card"><span>${t("misc.options")}</span><div id="optbox">${optionsHtml(s.options)}</div>
          <span>${t("misc.options_note")}</span></div>
        <div class="card"><span>${t("misc.measure")}</span>
          <div class="row"><b id="usbpoll">${t("usb.reading")}</b><button class="btn" id="usbrefresh">${t("misc.refresh")}</button></div>
          <span>${t("misc.usb_note")}</span>
          <div class="row"><button class="btn primary" id="mstart">${t("misc.start")}</button></div>
          <span>${t("misc.measure_note")}</span>
          <div class="progress"><i id="mbar2"></i></div><div id="mres"></div>
          <span>${t("misc.rate_hint")}</span></div>
        <div class="card"><span>${t("misc.battery")}</span><b>${t("misc.wired")}</b><span>${t("misc.hidden")}</span></div>
        <div class="card"><span>${t("misc.device")}</span><b>${t("misc.dev_id", { id: s.device.id ?? "-" })}</b><span>${t("top.rev", { rev: (s.device.revision || 0).toString(16).padStart(4, "0") })}</span></div></div>`;
      p.onclick = async (e) => {
        const opt = e.target.closest("[data-opt]");
        if (opt) return setOption(opt.dataset.opt);
        if (e.target.id === "mstart") return measureStart();
        if (e.target.id === "usbrefresh") return usbRefresh();
        if (e.target.id !== "debapply") return;
        const st = A.$("#debstate");
        st.textContent = t("rate.step.applying");
        const j = await A.api("POST", "/api/debounce", { ms: +A.$("#deb").value });
        if (A.report(j, t("toast.deb_applied"))) s.debounce = j.debounce;
        st.textContent = j.ok ? t(j.applied ? "misc.deb_match" : "misc.deb_mismatch", { v: j.debounce }) : j.error;
        st.className = "state " + (j.ok && j.applied ? "ok" : "bad");
      };
      usbRefresh();
      measureTick();
    },
  };

  A.views.backup = {
    label: "nav.backup", icon: "backup", stage: false,
    async render(p) {
      p.innerHTML = `<h2>${t("backup.title")}</h2><p class="sub">${t("backup.sub")}</p>
        <div class="row"><button class="btn primary" id="bk">${t("backup.now")}</button><button class="btn" id="restore" disabled>${t("backup.restore")}</button></div>
        <label><input type="checkbox" id="allp"> ${t("backup.all")}</label>
        <div class="state" id="bkstate"></div><div class="list" id="bklist"></div>`;
      let sel = null;
      p.onclick = async (e) => {
        const row = e.target.closest("[data-name]");
        if (row) {
          sel = row.dataset.name;
          A.$("#bklist").querySelectorAll("[data-name]").forEach((r) => r.classList.toggle("sel", r === row));
          A.$("#restore").disabled = false;
          return;
        }
        if (e.target.id === "restore") return restore(sel, e.target);
        if (e.target.id !== "bk") return;
        e.target.disabled = true;
        A.$("#bkstate").textContent = t("backup.running");
        const j = await A.api("POST", "/api/backup", { all_profiles: A.$("#allp").checked });
        e.target.disabled = false;
        A.$("#bkstate").textContent = j.ok ? t("backup.saved", { name: j.name }) : j.error;
        A.report(j, t("toast.backup_saved"));
        list();
      };
      list();
    },
  };

  async function restore(name, btn) {
    if (!name || !confirm(t("backup.confirm", { name }))) return;
    btn.disabled = true;
    const st = A.$("#bkstate");
    st.className = "state";
    st.textContent = t("backup.restoring");
    const j = await A.api("POST", "/api/restore", { file: name });
    btn.disabled = false;
    A.report(j, t("toast.restore_done"));
    st.className = "state " + (j.ok && j.applied ? "ok" : "bad");
    st.textContent = !j.ok ? j.error : j.partial ? j.message : j.applied ? t("backup.verified")
      : t("backup.diff", { diff: j.diff.join(", ") }) + (j.skipped.length ? t("backup.skipped", { skipped: j.skipped.join(", ") }) : "");
    const r = await A.api("GET", "/api/state");
    if (r.ok) { A.s = r; A.drawTop(); }
  }

  async function list() {
    const j = await A.api("GET", "/api/backups");
    const el = A.$("#bklist");
    if (el) el.innerHTML = j.ok && j.backups.length ? j.backups.map((b) =>
      `<div data-name="${A.esc(b.name)}"><span>${A.esc(b.name)}</span><span class="sub">${b.time} · ${Math.round(b.size / 1024)} KB</span></div>`).join("") : `<div><span class="sub">${t("backup.empty")}</span></div>`;
  }
})();
