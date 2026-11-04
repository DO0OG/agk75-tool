// 키 설정: 키보드 그림에서 키를 고르고, 바꿀 키를 그림/목록/실제 키 입력으로 지정한다.
(() => {
  // KeyboardEvent.code -> HID 사용 코드
  const CODE = { Enter: 40, Escape: 41, Backspace: 42, Tab: 43, Space: 44, Minus: 45, Equal: 46, BracketLeft: 47,
    BracketRight: 48, Backslash: 49, Semicolon: 51, Quote: 52, Backquote: 53, Comma: 54, Period: 55, Slash: 56,
    CapsLock: 57, PrintScreen: 70, ScrollLock: 71, Pause: 72, Insert: 73, Home: 74, PageUp: 75, Delete: 76, End: 77,
    PageDown: 78, ArrowRight: 79, ArrowLeft: 80, ArrowDown: 81, ArrowUp: 82, IntlBackslash: 100, ContextMenu: 101,
    ControlLeft: 224, ShiftLeft: 225, AltLeft: 226, MetaLeft: 227, ControlRight: 228, ShiftRight: 229, AltRight: 230, MetaRight: 231 };
  for (let i = 0; i < 26; i++) CODE["Key" + String.fromCharCode(65 + i)] = 4 + i;
  for (let i = 1; i <= 10; i++) CODE["Digit" + (i % 10)] = 29 + i;
  for (let i = 1; i <= 12; i++) CODE["F" + i] = 57 + i;

  const st = { layer: null, fn: false, mode: "board", armed: false, listening: false, filter: "" };
  const cur = () => (st.fn ? A.s.fn : A.s.keymap)[st.layer];
  const target = () => [...A.sel][0];
  const seg = (items, act, on) => '<div class="seg">' + items.map(([k, label]) =>
    `<button data-act="${act}" data-v="${k}" class="${k === on ? "on" : ""}">${label}</button>`).join("") + "</div>";
  const stateLine = (text, c = "") => { const e = A.$("#kstate"); if (e) { e.textContent = text; e.className = "state " + c; } };

  // 폴링레이트: PC 쪽 USB 필터 드라이버(hidusbf)로 바꾼다. bInterval 과 Hz 의 대응은 실기기 확인 전 가설이다.
  const RATES = [8000, 4000, 2000, 1000];
  const rt = { s: null, busy: false, step: "", res: "", cls: "" };
  const usbHz = () => { const u = (rt.s && rt.s.usb) || A.s.usb; return (u && u.max_hz) || null; };
  const rateDraw = () => { const e = A.$("#ratecard"); if (e) e.innerHTML = rateHtml(); };
  function rateStatus(s) {
    if (!s) return t("rate.status.checking");
    if (!s.device) return s.device_error || t("rate.status.nodev");
    if (!s.service || !s.sys) return t(s.package ? "rate.status.nodriver_ready" : "rate.status.nodriver_need");
    if (!s.filter) return t("rate.status.nofilter");
    return s.configured_hz ? t("rate.status.active_hz", { hz: s.configured_hz }) : t("rate.status.active_bi", { b: s.binterval });
  }
  function rateHtml() {
    const s = rt.s && rt.s.state, hz = usbHz(), cur = !s ? null : s.filter ? s.configured_hz : 8000;
    const off = rt.busy || !s || !s.device ? "disabled" : "";
    const btn = (r) => `<button data-act="rate" data-v="${r}" ${off} class="${r === cur ? "on" : ""}">${r === 8000 ? t("rate.off8000") : r + "Hz"}</button>`;
    return `<div class="card" style="padding:14px;margin-bottom:12px"><b>${t("rate.title")}</b> <span class="sub">${hz ? t("rate.usb_now", { hz }) : ""}</span>
      <div style="margin:8px 0" class="row"><div class="seg">${RATES.map(btn).join("")}</div>
      <button class="btn" data-act="rprep" ${rt.busy ? "disabled" : ""}>${t("rate.prepare")}</button></div>
      <div class="state">${A.esc(rateStatus(s))}</div>
      ${s && s.hvci ? `<div class="state bad">${t("rate.hvci")}</div>` : ""}
      <div class="state bad">${t("rate.table_warn")}</div>
      ${rt.busy ? `<div class="state">${A.esc(rt.step)}</div>` : ""}
      ${rt.res ? `<div class="state ${rt.cls}">${A.esc(rt.res)}</div>` : ""}
      <div class="state">${t("rate.note")}</div></div>`;
  }
  async function rateLoad() {
    const j = await A.api("GET", "/api/rate/state");
    if (j.ok) rt.s = j; else { rt.res = j.error || t("rate.load_fail"); rt.cls = "bad"; }
    rateDraw();
  }
  function rateResult(j, hz) {
    if (!j.ok) return ["bad", j.error || t("err.generic")];
    if (j.prepared) return ["ok", t(j.nopatch ? "rate.res.prepared_nopatch" : "rate.res.prepared")];
    if (!j.applied) return ["bad", t("rate.res.failed", { msg: j.message || t("rate.res.unknown") })];
    if (j.reboot_needed) return ["bad", t("rate.res.reboot")];
    const u = j.usb && j.usb.max_hz;
    if (!u) return ["", t("rate.res.nocheck")];
    return u === hz ? ["ok", t("rate.res.ok", { hz: u })] : ["bad", t("rate.res.mismatch", { got: u, want: hz })];
  }
  async function rateRun(path, body, step) {
    if (rt.busy) return;
    Object.assign(rt, { busy: true, step, res: "", cls: "" });
    rateDraw();
    const timer = setInterval(async () => {
      const p = await A.api("GET", "/api/rate/progress");
      if (p.ok && p.step) { rt.step = p.step; rateDraw(); }
    }, 1000);
    const j = await A.api("POST", path, body);
    clearInterval(timer);
    rt.busy = false;
    [rt.cls, rt.res] = rateResult(j, body.hz || 8000);
    if (j.ok && j.usb && !j.usb.error) A.s.usb = j.usb;
    await rateLoad();
  }
  function rateApply(hz) {
    const s = rt.s && rt.s.state;
    if (s && !s.service && !confirm(t("rate.confirm_install"))) return;
    rateRun(hz === 8000 ? "/api/rate/reset" : "/api/rate/set", { hz }, t("rate.step.applying"));
  }

  const view = A.views.keys = {
    label: "nav.keys", icon: "keys", stage: true,
    keyText(i) {
      if (i === FN_KEY) return "Fn";
      const n = A.itemName(cur()[i]);
      return st.fn && n === t("key.none") ? "" : A.short(n);
    },
    keyDim: (i) => i === FN_KEY,

    onKey(idx) {
      if (!st.armed) return false;
      st.armed = false;
      const hid = A.s.meta.default_hid[idx];
      if (hid) apply(hid); else A.toast(t("keys.cannot"), "bad");
      editor();
      return true;
    },

    select: () => editor(),

    render(p) {
      if (st.layer === null) st.layer = A.s.profile || 0;
      st.armed = st.listening = false;
      p.innerHTML = `<h2>${t("keys.title")}</h2><p class="sub">${t("keys.sub")}</p>
        <div id="ratecard">${rateHtml()}</div><h3>${t("keys.layer")}</h3><div class="row wrap">${seg([[0, "1"], [1, "2"], [2, "3"], [3, "4"]], "layer", st.layer)}
        ${seg([["n", t("keys.kind.n")], ["f", t("keys.kind.f")]], "kind", st.fn ? "f" : "n")}</div><hr><div id="kedit"></div>`;
      p.onclick = onClick;
      rateLoad();
      p.oninput = (e) => { if (e.target.id === "kfilter") { st.filter = e.target.value; listHtml(); } };
      editor();
    },
  };

  function editor() {
    const box = A.$("#kedit");
    if (!box) return;
    const idx = target();
    if (idx === undefined) { box.innerHTML = `<p class="sub">${t("keys.none_selected")}</p>`; return; }
    const it = cur()[idx], def = A.s.meta.default_hid[idx];
    box.innerHTML = `<h3>${t("keys.selected", { idx })}</h3>
      <div class="row"><span class="keycap">${A.esc(A.itemName(it))}</span>
      <span class="sub">${st.fn ? t("keys.kind.f") : t("keys.std_pos", { name: A.esc(def ? A.hidName(def) : "-") })}${A.itemName(it) === t("key.special") ? "<br>" + t("keys.value", { hex: it.map((b) => b.toString(16).padStart(2, "0")).join(" ") }) : ""}</span></div>
      <h3>${t("keys.pick_title")}</h3>
      ${seg([["board", t("keys.mode.board")], ["list", t("keys.mode.list")], ["press", t("keys.mode.press")]], "mode", st.mode)}
      <div id="kmode" style="margin-top:10px"></div>
      <div class="row" style="margin-top:14px"><button class="btn" data-act="def"${A.s.factory ? "" : " disabled"}>${t("keys.def")}</button><button class="btn" data-act="none">${t("keys.setnone")}</button></div>
      ${A.s.factory ? "" : `<p class="sub">${t("keys.nofactory")}</p>`}
      <div class="state" id="kstate"></div>`;
    modeHtml();
  }

  function modeHtml() {
    const m = A.$("#kmode");
    if (!m) return;
    if (st.mode === "board") m.innerHTML = `<button class="btn ${st.armed ? "primary" : ""}" data-act="arm">${t(st.armed ? "keys.arm_on" : "keys.arm_off")}</button>`;
    else if (st.mode === "press") m.innerHTML = `<button class="btn ${st.listening ? "primary" : ""}" data-act="listen">${t(st.listening ? "keys.listen_on" : "keys.listen_off")}</button>`;
    else { m.innerHTML = '<input type="text" id="kfilter" placeholder="' + A.esc(t("keys.search_ph")) + '" value="' + A.esc(st.filter) + '"><div class="pick" id="klist"></div>'; listHtml(); }
  }

  function listHtml() {
    const names = Object.entries(A.s.meta.hid_names).map(([h, n]) => [+h, n]).sort((a, b) => a[0] - b[0])
      .filter(([, n]) => n.toLowerCase().includes(st.filter.toLowerCase()));
    A.$("#klist").innerHTML = names.map(([h, n]) => `<button data-act="pick" data-v="${h}">${A.esc(n)}</button>`).join("");
  }

  async function apply(hid, useDefault) {
    const idx = target(), { layer, fn } = st;
    if (idx === undefined) return;
    stateLine(t("keys.applying"));
    const j = await A.api("POST", fn ? "/api/fn" : "/api/key", useDefault ? { layer, idx, default: true } : { layer, idx, hid });
    const ok = A.report(j, t("toast.key_applied", { idx }));
    if (j.ok) (fn ? A.s.fn : A.s.keymap)[layer][idx] = j.item;
    A.paint();
    editor();
    const nm = j.ok ? A.itemName(j.item) : "";
    stateLine(ok ? t("state.match", { name: nm }) : j.ok ? t("state.mismatch", { name: nm }) : j.error, ok ? "ok" : "bad");
  }

  function onKey(e) {
    if (!st.listening) return;
    e.preventDefault();
    st.listening = false;
    document.removeEventListener("keydown", onKey, true);
    const hid = CODE[e.code];
    modeHtml();
    if (hid) apply(hid); else A.toast(t("keys.unsupported", { code: e.code }), "bad");
  }

  function onClick(e) {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    const v = b.dataset.v, a = b.dataset.act;
    if (a === "rate") return rateApply(+v);
    if (a === "rprep") return rateRun("/api/rate/prepare", {}, t("rate.step.downloading"));
    if (a === "layer" || a === "kind") {
      if (a === "layer") st.layer = +v; else st.fn = v === "f";
      A.render();
    } else if (a === "mode") { st.mode = v; st.armed = st.listening = false; editor(); }
    else if (a === "arm") { st.armed = !st.armed; modeHtml(); }
    else if (a === "listen") {
      st.listening = !st.listening;
      document[st.listening ? "addEventListener" : "removeEventListener"]("keydown", onKey, true);
      modeHtml();
    } else if (a === "pick") apply(+v);
    else if (a === "none") apply(0);
    else if (a === "def") apply(0, true);
  }
})();
