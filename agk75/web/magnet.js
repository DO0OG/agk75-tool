// 래피드 트리거(자기 축): 키를 여러 개 골라 거리·데드존·RT 를 쓴다. 키마다 작동 거리를 열지도로 보여 준다.
(() => {
  const FIELDS = [["travel", 0.1, 3.5], ["lift", 0.1, 3.5], ["dead", 0, 1], ["rt_press", 0.1, 2], ["rt_lift", 0.1, 2]];
  const rows = (list) => list.map(([k, lo, hi]) => A.rangeRow(t("mag." + k), "m-" + k, lo, hi, 0.1, vals[k], " mm")).join("");
  const touched = new Set();
  let vals = null, busy = false;
  const state = (text, c = "") => { const e = A.$("#mstate"); if (e) { e.textContent = text; e.className = "state " + c; } };
  const first = () => A.s.magnet[[...A.sel][0] ?? 0];

  function loadVals() {
    vals = { ...first() };
    touched.clear();
  }

  function sync() {
    for (const [k] of FIELDS) {
      const r = A.$("#m-" + k);
      if (r) { r.value = vals[k]; r.dispatchEvent(new Event("input", { bubbles: true })); }
    }
    A.$("#mrt").classList.toggle("on", vals.rt);
    A.$("#mrtbox").style.opacity = vals.rt ? 1 : 0.4;
    A.$("#mcount").textContent = A.sel.size ? t("mag.count", { n: A.sel.size }) : t("mag.none_sel");
    A.$("#mapply").disabled = A.$("#mall").disabled = busy;
  }

  async function applyKeys() {
    const idxs = [...A.sel];
    const body = {};
    touched.forEach((k) => { body[k] = vals[k]; });
    if (!idxs.length) return A.toast(t("mag.need_sel"), "bad");
    if (!touched.size) return A.toast(t("mag.no_change"), "bad");
    busy = true; sync();
    const bad = [];
    for (const [n, idx] of idxs.entries()) {
      state(t("mag.progress", { n: n + 1, total: idxs.length, idx }));
      A.$("#mbar").style.width = ((n + 1) / idxs.length * 100) + "%";
      const j = await A.api("POST", "/api/magnet", { idx, ...body });
      if (j.ok) A.s.magnet[idx] = j.magnet;
      if (!j.ok || !j.applied) bad.push(idx);
      if (!j.ok) { A.toast(j.error, "bad", 5000); break; }
    }
    busy = false;
    finish(bad.length ? t("mag.bad_keys", { keys: bad.join(", ") }) : "", idxs.length);
  }

  async function applyAll() {
    if (!touched.size) return A.toast(t("mag.no_change"), "bad");
    if (!confirm(t("mag.confirm_all"))) return;
    const body = {};
    touched.forEach((k) => { body[k] = vals[k]; });
    busy = true; sync();
    const poll = setInterval(async () => {
      const p = await A.api("GET", "/api/progress");
      if (p.ok) { state(t("mag.all_progress", { n: p.n, total: p.total })); A.$("#mbar").style.width = (p.n / p.total * 100) + "%"; }
    }, 700);
    const j = await A.api("POST", "/api/magnet_all", body);
    clearInterval(poll);
    busy = false;
    const r = await A.api("GET", "/api/state");
    if (r.ok) A.s.magnet = r.magnet;
    finish(j.ok && !j.applied ? t("mag.bad_all", { keys: j.failed.join(", ") }) : j.ok ? "" : j.error, 128);
  }

  function finish(bad, n) {
    if (bad) { const b = A.$("#banner"); b.textContent = bad; b.hidden = false; A.toast(bad, "bad", 5000); }
    else A.report({ ok: true, applied: true }, t("mag.done", { n }));
    A.paint();
    sync();
    state(bad || t("state.match0"), bad ? "bad" : "ok");
    if (!bad) touched.clear();
  }

  A.views.magnet = {
    label: "nav.magnet", icon: "magnet", stage: true, multi: true,
    legend: "mag.legend",
    keyText: (i) => `${A.label(i)}<small>${A.s.magnet[i].travel.toFixed(1)}</small>`,
    keyStyle: (i) => `hsl(${215 - 210 * (A.s.magnet[i].travel - 0.1) / 3.4} 60% 30%)`,
    select() { loadVals(); sync(); },
    render(p) {
      A.sel.add(0);
      loadVals();
      p.innerHTML = `<h2>${t("mag.title")}</h2><p class="sub" id="mcount"></p>
        <div class="row"><button class="btn" id="mselall">${t("mag.selall")}</button><button class="btn" id="mclear">${t("mag.clear")}</button></div>
        <h3>${t("mag.dist")}</h3>
        ${rows(FIELDS.slice(0, 3))}
        <div class="row"><label>${t("mag.rt")}</label><button class="switch" id="mrt"></button></div>
        <div id="mrtbox">${rows(FIELDS.slice(3))}</div>
        <p class="sub">${t("mag.hint")}</p>
        <div class="row"><button class="btn primary" id="mapply">${t("mag.apply_sel")}</button><button class="btn" id="mall">${t("mag.apply_all")}</button></div>
        <div class="progress"><i id="mbar"></i></div><div class="state" id="mstate"></div>`;
      p.oninput = (e) => {
        const k = e.target.id.slice(2);
        if (e.isTrusted && FIELDS.some((f) => f[0] === k)) { vals[k] = +e.target.value; touched.add(k); }
      };
      p.onclick = (e) => {
        const id = e.target.closest("button")?.id;
        if (id === "mrt") { vals.rt = !vals.rt; touched.add("rt"); sync(); }
        else if (id === "mselall") { A.sel = new Set(LAYOUT.map((k) => k[0])); A.paint(); sync(); }
        else if (id === "mclear") { A.sel.clear(); A.paint(); sync(); }
        else if (id === "mapply") applyKeys();
        else if (id === "mall") applyAll();
      };
      sync();
    },
  };
})();
