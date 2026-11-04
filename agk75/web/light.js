// 조명: 값을 바꾸면 300ms 뒤 자동 적용하고, 장치가 되돌려 준 값으로 확정한다. 본체 조명과 측면 조명은 같은 편집기를 쓴다.
(() => {
  // 영문 원명은 그대로 두고 언어별 병기명만 붙인다(원명과 같으면 생략)
  const gloss = (n) => { const g = I18N.has("fx." + n) ? t("fx." + n) : ""; return g.toLowerCase() === n.toLowerCase() ? "" : g; };
  const hex = (c) => "#" + c.map((x) => x.toString(16).padStart(2, "0")).join("");
  const rgbOf = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));

  // id: 요소 접두어, path: API, key: A.s 의 키, effects: 효과 표를 돌려주는 함수, onChange: 값이 바뀔 때 부를 함수
  function zone(id, path, key, effects, onChange) {
    let L, timer, busy = false, again = false;
    const root = () => A.$(`[data-z="${id}"]`);
    const state = (text, c = "") => { const e = A.$("#" + id + "state"); if (e) { e.textContent = text; e.className = "state " + c; } };

    function change() {
      clearTimeout(timer);
      state(t("light.changed"));
      if (onChange) onChange(L);
      timer = setTimeout(send, 300);
    }

    async function send() {
      if (busy) { again = true; return; }
      busy = true;
      state(t("light.applying"));
      const j = await A.api("POST", path, L);
      busy = false;
      if (again) { again = false; send(); return; }
      const ok = A.report(j, t("toast.light_applied"));
      if (j.ok) A.s[key] = j[key];
      state(ok ? t("state.match0") : j.ok ? t("light.mismatch_detail", { effect: j[key].effect, bright: j[key].bright }) : j.error, ok ? "ok" : "bad");
    }

    function sync(skipColor) {
      const r = root();
      r.querySelectorAll("[data-e]").forEach((b) => b.classList.toggle("on", +b.dataset.e === L.effect));
      r.querySelectorAll("[data-o]").forEach((b) => b.classList.toggle("on", +b.dataset.o === L.option));
      r.querySelectorAll("[data-c]").forEach((b) => b.classList.toggle("on", hex(A.s.meta.presets[+b.dataset.c]) === hex(L.rgb) && !L.dazzle));
      r.querySelector("[data-d]").classList.toggle("on", L.dazzle);
      if (!skipColor) A.$("#" + id + "color").value = hex(L.rgb);
    }

    return {
      get value() { return L; },
      html() {
        L = { ...A.s[key], rgb: [...A.s[key].rgb] };
        const presets = A.s.meta.presets;
        return `<div class="zone" data-z="${id}"><h3>${t("light.effect")}</h3><div class="grid">${Object.entries(effects()).map(([k, n]) =>
            `<button data-e="${k}" class="${+k === L.effect ? "on" : ""}">${n}<small>${gloss(n)}</small></button>`).join("")}</div>
          <h3>${t("light.color")}</h3><div class="row"><input type="color" id="${id}color" value="${hex(L.rgb)}">
            <div class="swatches">${presets.map((c, i) => `<button data-c="${i}" style="background:${hex(c)}" title="${hex(c)}"></button>`).join("")}</div></div>
          <div class="row"><label>${t("light.rainbow")}</label><button class="switch ${L.dazzle ? "on" : ""}" data-d="1"></button></div>
          <h3>${t("light.bright_speed")}</h3>${A.rangeRow(t("light.bright"), id + "bright", 0, 4, 1, L.bright)}${A.rangeRow(t("light.speed"), id + "speed", 0, 4, 1, L.speed)}
          <h3>${t("light.option")}</h3><div class="seg">${[...new Set([0, 1, 2, 3, L.option])].map((o) =>
            `<button data-o="${o}" class="${o === L.option ? "on" : ""}">${o}</button>`).join("")}</div>
          <div class="state" id="${id}state"></div></div>`;
      },
      click(b) {
        if (b.dataset.e !== undefined) L.effect = +b.dataset.e;
        else if (b.dataset.c !== undefined) { L.rgb = [...A.s.meta.presets[+b.dataset.c]]; L.dazzle = false; }
        else if (b.dataset.o !== undefined) L.option = +b.dataset.o;
        else if (b.dataset.d !== undefined) L.dazzle = !L.dazzle;
        else return;
        sync();
        change();
      },
      input(t) {
        if (t.id === id + "color") { L.rgb = rgbOf(t.value); L.dazzle = false; }
        else if (t.id === id + "bright") L.bright = +t.value;
        else if (t.id === id + "speed") L.speed = +t.value;
        else return;
        sync(t.id === id + "color");
        change();
      },
    };
  }

  function glow(L) {
    const kb = A.$("#kb");
    kb.style.setProperty("--glow", L.effect === 0 ? "transparent" : L.dazzle ? "#fff" : hex(L.rgb));
    kb.style.opacity = 0.55 + L.bright * 0.1125;
  }

  const main = zone("l", "/api/light", "light", () => A.s.meta.effects, glow);
  const side = zone("s", "/api/sidelight", "sidelight", () => A.s.meta.side_effects);

  A.views.light = {
    label: "nav.light", icon: "light", stage: true,
    legend: "light.legend",
    render(p) {
      p.innerHTML = `<h2>${t("light.title")}</h2><p class="sub">${t("light.sub")}</p>${main.html()}
        <hr><h2>${t("light.side_title")}</h2>${A.s.sidelight ? side.html() : `<p class="sub">${t("light.side_fail")}</p>`}`;
      glow(main.value);
      const pick = (e) => { const z = e.target.closest(".zone"); return z && (z.dataset.z === "l" ? main : side); };
      p.onclick = (e) => {
        const b = e.target.closest("button"), z = pick(e);
        if (b && z) z.click(b);
      };
      p.oninput = (e) => { const z = pick(e); if (z) z.input(e.target); };
    },
  };
})();
