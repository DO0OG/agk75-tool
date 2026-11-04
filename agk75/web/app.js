// 공통 뼈대: API 호출, 상단 바, 내비, 키보드 그림, 알림. 화면별 코드는 keys/light/magnet/misc.js.
const A = {
  s: null, view: "keys", sel: new Set(), views: {}, conn: null, reconn: 0,
  $: (s, el = document) => el.querySelector(s),
  esc: (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])),
  SHORT: { CapsLock: "Caps", Backspace: "Bksp", PageUp: "PgUp", PageDown: "PgDn", ScrollLock: "ScrLk", Delete: "Del",
    Insert: "Ins", LShift: "Shift", RShift: "Shift", LCtrl: "Ctrl", RCtrl: "Ctrl", LAlt: "Alt", RAlt: "Alt",
    LWin: "Win", RWin: "Win", PrtSc: "PrtSc", Right: "→", Left: "←", Up: "↑", Down: "↓" },
  ICONS: {
    keys: '<svg viewBox="0 0 24 24"><rect x="2" y="6" width="20" height="12" rx="3"/><path d="M6 10h2M11 10h2M16 10h2M7 14h10"/></svg>',
    light: '<svg viewBox="0 0 24 24"><path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"/></svg>',
    magnet: '<svg viewBox="0 0 24 24"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg>',
    misc: '<svg viewBox="0 0 24 24"><path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/></svg>',
    backup: '<svg viewBox="0 0 24 24"><path d="M5 3h11l3 3v15H5zM8 3v5h7V3M8 21v-7h8v7"/></svg>',
  },

  async api(method, path, body) {
    try {
      const r = await fetch(path, { method, headers: { "Content-Type": "application/json", "X-Lang": I18N.lang },
        body: method === "POST" ? JSON.stringify(body || {}) : undefined });
      const j = await r.json();
      if (j.connected === false) A.setConn(false);
      return j;
    } catch (e) {
      A.setConn(false);
      return { ok: false, error: t("err.network") };
    }
  },

  toast(msg, kind = "ok", ms = 2600) {
    const t = document.createElement("div");
    t.className = "toast " + kind;
    t.textContent = msg;
    A.$("#toasts").append(t);
    setTimeout(() => t.remove(), ms);
  },

  // 쓰기 응답 처리: applied 가 아니면 빨간 경고. 반환값 = 정상 적용 여부
  report(j, okMsg = t("toast.applied")) {
    const banner = A.$("#banner");
    if (!j.ok) { A.toast(j.error || t("err.generic"), "bad", 5000); return false; }
    if (j.applied === false) {
      banner.textContent = t("banner.mismatch");
      banner.hidden = false;
      A.toast(t("toast.mismatch"), "bad", 5000);
      return false;
    }
    banner.hidden = true;
    A.toast(okMsg);
    return true;
  },

  setConn(on) {
    if (A.conn === on) return;
    A.conn = on;
    const c = A.$("#conn");
    c.className = "conn " + (on ? "on" : "off");
    c.lastElementChild.textContent = t(on ? "conn.on" : "conn.off");
  },

  hidName: (hid) => A.s.meta.hid_names[hid] || "HID" + hid,
  // 4바이트 항목 -> 이름("없음" / "특수" 포함)
  itemName(it) {
    if (it[0] === 0 && it[1] === 0 && it[3] === 0 && it[2]) return A.hidName(it[2]);
    return it.some((b) => b) ? t("key.special") : t("key.none");
  },
  short: (n) => A.SHORT[n] || n,
  label: (i) => (i === FN_KEY ? "Fn" : A.short(A.itemName(A.s.keymap[A.s.profile][i]))),

  // 언어를 바꾸면 선택 상태는 그대로 두고 문구만 다시 그린다
  setLang(l) {
    I18N.set(l);
    A.drawTop();
    A.drawNav();
    if (A.conn !== null) { const c = A.$("#conn"); c.lastElementChild.textContent = t(A.conn ? "conn.on" : "conn.off"); }
    A.$("#legend").innerHTML = A.views[A.view].legend ? t(A.views[A.view].legend) : "";
    A.render();
  },

  // ---------- 상단 바 / 내비 ----------
  drawTop() {
    const s = A.s;
    A.$("#rev").textContent = s ? t("top.rev", { rev: (s.device.revision || 0).toString(16).padStart(4, "0") }) : "";
    A.$("#lang").innerHTML = I18N.langs.map(([k, n]) => `<button data-l="${k}" class="${k === I18N.lang ? "on" : ""}">${n}</button>`).join("");
    const seg = A.$("#profile");
    seg.innerHTML = [0, 1, 2, 3].map((i) => `<button data-p="${i}" class="${s && s.profile === i ? "on" : ""}">${i + 1}</button>`).join("");
  },

  drawNav() {
    A.$("#nav").innerHTML = Object.entries(A.views).map(([k, v]) =>
      `<button data-v="${k}" class="${k === A.view ? "on" : ""}">${A.ICONS[v.icon]}<span>${t(v.label)}</span></button>`).join("");
  },

  // ---------- 키보드 그림 ----------
  buildKb() {
    A.$("#kb").innerHTML = LAYOUT.map(([i, x, y, w]) =>
      `<button class="key" data-i="${i}" style="left:calc(var(--u)*${x});top:calc(var(--u)*${y});width:calc(var(--u)*${w} - 4px);height:calc(var(--u) - 4px)"></button>`).join("");
  },

  fit() {
    const st = A.$("#stage");
    if (st.classList.contains("hidden")) return;
    A.$("#kb").style.setProperty("--u", Math.max(30, Math.min(58, Math.floor((st.clientWidth - 40) / LAYOUT_W))) + "px");
    A.$("#kb").style.width = "calc(var(--u) * " + LAYOUT_W + ")";
  },

  paint() {
    const v = A.views[A.view];
    for (const k of A.$("#kb").children) {
      const i = +k.dataset.i;
      const st = v.keyStyle ? v.keyStyle(i) : "";
      k.style.background = st;
      k.innerHTML = v.keyText ? v.keyText(i) : A.label(i);
      k.classList.toggle("sel", A.sel.has(i));
      k.classList.toggle("dim", !!(v.keyDim && v.keyDim(i)));
    }
  },

  select(idx, add, drag) {
    const v = A.views[A.view];
    if (v.onKey && v.onKey(idx)) return;
    if (!v.multi || (!add && !drag)) A.sel.clear();
    if (v.multi && add && !drag && A.sel.has(idx)) A.sel.delete(idx);
    else A.sel.add(idx);
    A.paint();
    if (v.select) v.select();
  },

  // ---------- 화면 전환 ----------
  show(name) {
    A.view = name;
    const v = A.views[name], st = A.$("#stage");
    A.sel.clear();
    A.drawNav();
    st.classList.toggle("hidden", !v.stage || !A.s);
    A.$("#kb").classList.toggle("glow", name === "light");
    A.$("#kb").style.opacity = "";
    A.$("#legend").innerHTML = v.legend ? t(v.legend) : "";
    A.render();
  },

  render() {
    const v = A.views[A.view], p = A.$("#panel");
    if (!A.s) {
      A.$("#stage").classList.add("hidden");
      p.innerHTML = `<h2>${t("nodev.title")}</h2><p class="sub">${t("nodev.body")}</p><button class="btn primary" id="retry">${t("nodev.retry")}</button>`;
      A.$("#retry").onclick = () => A.load();
      return;
    }
    if (v.stage) A.$("#stage").classList.remove("hidden");
    A.fit();
    v.render(p);
    A.paint();
  },

  async load() {
    if (A.loading) return;
    A.loading = true;
    const j = await A.api("GET", "/api/state");
    A.loading = false;
    A.s = j.ok ? j : null;
    if (j.ok) A.setConn(true);
    A.drawTop();
    A.show(A.view);
  },

  // 입력창 아래 range/output 표시 갱신
  rangeRow(label, id, min, max, step, val, unit = "") {
    return `<div class="row"><label for="${id}">${label}</label><input type="range" id="${id}" min="${min}" max="${max}" step="${step}" value="${val}" data-unit="${unit}"><output id="${id}-o">${(+val).toFixed(step < 1 ? 1 : 0)}${unit}</output></div>`;
  },

  start() {
    I18N.lang = I18N.detect();
    I18N.apply();
    A.buildKb();
    A.drawTop();
    A.drawNav();
    let drag = false;
    A.$("#lang").onclick = (e) => { const b = e.target.closest("button"); if (b) A.setLang(b.dataset.l); };
    A.$("#nav").onclick = (e) => { const b = e.target.closest("button"); if (b) A.show(b.dataset.v); };
    if (A.views[location.hash.slice(1)]) A.show(location.hash.slice(1));  // #light 처럼 화면을 바로 열 수 있다
    A.$("#profile").onclick = async (e) => {
      const b = e.target.closest("button");
      if (!b || !A.s) return;
      const j = await A.api("POST", "/api/profile", { layer: +b.dataset.p });
      if (A.report(j, t("toast.profile", { n: +b.dataset.p + 1 }))) { A.s.profile = j.profile; A.drawTop(); A.paint(); }
    };
    A.$("#panel").addEventListener("input", (e) => {
      const t = e.target, o = A.$("#" + t.id + "-o");
      if (t.type === "range" && o) o.textContent = (+t.value).toFixed(+t.step < 1 ? 1 : 0) + (t.dataset.unit || "");
    });
    A.$("#kb").onmousedown = (e) => {
      const k = e.target.closest(".key");
      if (!k || e.button || k.classList.contains("dim")) return;
      drag = true;
      A.select(+k.dataset.i, e.shiftKey || e.ctrlKey, false);
      e.preventDefault();
    };
    A.$("#kb").onmouseover = (e) => {
      const k = e.target.closest(".key");
      if (drag && k && !k.classList.contains("dim") && !A.sel.has(+k.dataset.i)) A.select(+k.dataset.i, true, true);
    };
    addEventListener("mouseup", () => { drag = false; });
    addEventListener("resize", () => { A.fit(); });
    const beat = async () => {
      const j = await A.api("GET", "/api/heartbeat");
      if (!j.ok) return;
      const was = A.conn;
      A.setConn(j.connected);
      if (j.connected && was === false) A.reconn++;  // 재연결 횟수(폴링레이트 적용 확인용)
      if (j.connected && (!A.s || was === false)) A.load();
      else if (j.connected && j.profile !== A.s.profile && j.profile != null) { A.s.profile = j.profile; A.drawTop(); A.paint(); }
    };
    setInterval(beat, 2000);
    A.load();
  },
};
